# Slack Agent Threads Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire up the documented `thread.require_explicit_mention=False` default in the Slack channel runtime so that any bot reply in a Slack thread auto-claims the thread, and subsequent non-mention replies in that thread route to the same agent without re-mention.

**Architecture:** Add a `thread_bindings` table to the existing `RoutesStore` (sqlite + postgres). Extract the on-message routing policy into a pure `threads.py` module mirroring the existing `resolver.py` pattern. Wire `server_template.py`'s `SERVER_PY` string to (1) write a binding after every successful `on_mention` reply, (2) consult the binding via `threads.py` for non-DM `message` events.

**Tech Stack:** Python 3.11+, slack-bolt (AsyncApp), SQLite/Postgres via psycopg, pytest. Edits land entirely inside `packages/python/vystak-channel-slack/`.

**Spec:** [`docs/superpowers/specs/2026-04-25-slack-agent-threads-design.md`](../specs/2026-04-25-slack-agent-threads-design.md)

---

## File map

| Path | Action | Responsibility |
|------|--------|----------------|
| `packages/python/vystak-channel-slack/src/vystak_channel_slack/store.py` | Modify | Add `thread_bindings` table + ABC methods + sqlite/postgres impls. |
| `packages/python/vystak-channel-slack/src/vystak_channel_slack/threads.py` | Create | Pure policy: given an inbound event's facts + a store, return the agent name to forward to (or None). |
| `packages/python/vystak-channel-slack/src/vystak_channel_slack/server_template.py` | Modify | Wire `SERVER_PY`: import + call `route_thread_message`; sticky-check + post-success write in `on_mention`; binding consult in `on_message` non-DM branch. |
| `packages/python/vystak-channel-slack/tests/test_store.py` | Modify | Functional tests for the new store methods. |
| `packages/python/vystak-channel-slack/tests/test_threads.py` | Create | Functional tests for the policy function. |
| `packages/python/vystak-channel-slack/tests/test_plugin.py` | Modify | String-content assertions confirming `SERVER_PY` calls the new APIs (consistent with the existing `TestServerTemplateTransportBootstrap` pattern). |
| `website/docs/channels/slack.md` | Modify | Add a paragraph in the "Thread context" section documenting the default-on follow-thread behavior + the opt-out flag. |

---

## Task 1: Add `thread_bindings` to `RoutesStore`

**Files:**
- Modify: `packages/python/vystak-channel-slack/src/vystak_channel_slack/store.py`
- Modify: `packages/python/vystak-channel-slack/tests/test_store.py`

- [ ] **Step 1.1: Write failing tests for `thread_bindings`**

Add the following tests to the **end of** `packages/python/vystak-channel-slack/tests/test_store.py` (the existing `store` fixture and imports are reused):

```python
def test_set_and_get_thread_binding(store):
    store.set_thread_binding("T1", "C1", "1700.111", "weather-agent")
    assert store.thread_binding("T1", "C1", "1700.111") == "weather-agent"


def test_unknown_thread_returns_none(store):
    assert store.thread_binding("T1", "C1", "1700.999") is None


def test_overwrite_thread_binding(store):
    store.set_thread_binding("T1", "C1", "1700.111", "weather-agent")
    store.set_thread_binding("T1", "C1", "1700.111", "support-agent")
    assert store.thread_binding("T1", "C1", "1700.111") == "support-agent"


def test_unbind_thread(store):
    store.set_thread_binding("T1", "C1", "1700.111", "weather-agent")
    store.unbind_thread("T1", "C1", "1700.111")
    assert store.thread_binding("T1", "C1", "1700.111") is None


def test_thread_bindings_isolated_by_channel_and_team(store):
    store.set_thread_binding("T1", "C1", "1700.111", "weather-agent")
    # Different channel, same thread_ts
    assert store.thread_binding("T1", "C2", "1700.111") is None
    # Different team, same channel + thread_ts
    assert store.thread_binding("T2", "C1", "1700.111") is None


def test_migrate_creates_thread_bindings_table(tmp_path):
    """Re-uses the existing idempotent migration test pattern."""
    import sqlite3
    from vystak_channel_slack.store import SqliteStore

    db = tmp_path / "state.db"
    s = SqliteStore(path=str(db))
    s.migrate()
    s.migrate()  # idempotent

    conn = sqlite3.connect(str(db))
    try:
        names = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    finally:
        conn.close()
    assert "thread_bindings" in names
```

- [ ] **Step 1.2: Run the new tests and confirm they fail**

```bash
uv run pytest packages/python/vystak-channel-slack/tests/test_store.py -v -k "thread_binding or thread_bindings"
```

Expected: failures with `AttributeError: 'SqliteStore' object has no attribute 'set_thread_binding'` (or similar). Six tests fail.

- [ ] **Step 1.3: Add `thread_bindings` to the SQLite schema**

Edit `packages/python/vystak-channel-slack/src/vystak_channel_slack/store.py`. Replace the existing `_SCHEMA = """ ... """` block (around line 46) with:

```python
_SCHEMA = """
CREATE TABLE IF NOT EXISTS channel_bindings (
    team_id TEXT NOT NULL, channel_id TEXT NOT NULL,
    agent_name TEXT NOT NULL, inviter_id TEXT,
    created_at INTEGER NOT NULL,
    PRIMARY KEY (team_id, channel_id));
CREATE TABLE IF NOT EXISTS user_prefs (
    team_id TEXT NOT NULL, user_id TEXT NOT NULL,
    agent_name TEXT NOT NULL, created_at INTEGER NOT NULL,
    PRIMARY KEY (team_id, user_id));
CREATE TABLE IF NOT EXISTS inviters (
    team_id TEXT NOT NULL, channel_id TEXT NOT NULL,
    user_id TEXT NOT NULL, joined_at INTEGER NOT NULL,
    PRIMARY KEY (team_id, channel_id));
CREATE TABLE IF NOT EXISTS thread_bindings (
    team_id TEXT NOT NULL, channel_id TEXT NOT NULL,
    thread_ts TEXT NOT NULL, agent_name TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    PRIMARY KEY (team_id, channel_id, thread_ts));
"""
```

- [ ] **Step 1.4: Add `thread_bindings` to the Postgres schema**

In the same file, replace the existing `_PG_SCHEMA = """ ... """` block (around line 178) with:

```python
_PG_SCHEMA = """
CREATE TABLE IF NOT EXISTS channel_bindings (
    team_id TEXT NOT NULL, channel_id TEXT NOT NULL,
    agent_name TEXT NOT NULL, inviter_id TEXT,
    created_at BIGINT NOT NULL,
    PRIMARY KEY (team_id, channel_id));
CREATE TABLE IF NOT EXISTS user_prefs (
    team_id TEXT NOT NULL, user_id TEXT NOT NULL,
    agent_name TEXT NOT NULL, created_at BIGINT NOT NULL,
    PRIMARY KEY (team_id, user_id));
CREATE TABLE IF NOT EXISTS inviters (
    team_id TEXT NOT NULL, channel_id TEXT NOT NULL,
    user_id TEXT NOT NULL, joined_at BIGINT NOT NULL,
    PRIMARY KEY (team_id, channel_id));
CREATE TABLE IF NOT EXISTS thread_bindings (
    team_id TEXT NOT NULL, channel_id TEXT NOT NULL,
    thread_ts TEXT NOT NULL, agent_name TEXT NOT NULL,
    created_at BIGINT NOT NULL,
    PRIMARY KEY (team_id, channel_id, thread_ts));
"""
```

- [ ] **Step 1.5: Add three abstract methods to `RoutesStore`**

In the same file, inside the `class RoutesStore(ABC):` block, after the existing `inviter` abstract method (around line 43), add:

```python
    @abstractmethod
    def thread_binding(
        self, team: str, channel: str, thread_ts: str
    ) -> str | None: ...

    @abstractmethod
    def set_thread_binding(
        self, team: str, channel: str, thread_ts: str, agent: str
    ) -> None: ...

    @abstractmethod
    def unbind_thread(
        self, team: str, channel: str, thread_ts: str
    ) -> None: ...
```

- [ ] **Step 1.6: Implement the three methods on `SqliteStore`**

In the same file, append these methods to `class SqliteStore(RoutesStore):` (after the existing `inviter` method, around line 175):

```python
    def thread_binding(
        self, team: str, channel: str, thread_ts: str
    ) -> str | None:
        conn = self._conn()
        try:
            row = conn.execute(
                "SELECT agent_name FROM thread_bindings "
                "WHERE team_id=? AND channel_id=? AND thread_ts=?",
                (team, channel, thread_ts),
            ).fetchone()
            return row[0] if row else None
        finally:
            conn.close()

    def set_thread_binding(
        self, team: str, channel: str, thread_ts: str, agent: str
    ) -> None:
        conn = self._conn()
        try:
            conn.execute(
                "INSERT OR REPLACE INTO thread_bindings "
                "(team_id, channel_id, thread_ts, agent_name, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (team, channel, thread_ts, agent, int(time.time())),
            )
        finally:
            conn.close()

    def unbind_thread(
        self, team: str, channel: str, thread_ts: str
    ) -> None:
        conn = self._conn()
        try:
            conn.execute(
                "DELETE FROM thread_bindings "
                "WHERE team_id=? AND channel_id=? AND thread_ts=?",
                (team, channel, thread_ts),
            )
        finally:
            conn.close()
```

- [ ] **Step 1.7: Implement the three methods on `PostgresStore`**

In the same file, append these methods to `class PostgresStore(RoutesStore):` (after the existing `inviter` method at the end of the class):

```python
    def thread_binding(
        self, team: str, channel: str, thread_ts: str
    ) -> str | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT agent_name FROM thread_bindings "
                "WHERE team_id=%s AND channel_id=%s AND thread_ts=%s",
                (team, channel, thread_ts),
            ).fetchone()
            return row[0] if row else None

    def set_thread_binding(
        self, team: str, channel: str, thread_ts: str, agent: str
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO thread_bindings "
                "(team_id, channel_id, thread_ts, agent_name, created_at) "
                "VALUES (%s, %s, %s, %s, %s) "
                "ON CONFLICT (team_id, channel_id, thread_ts) DO UPDATE SET "
                "agent_name = EXCLUDED.agent_name, "
                "created_at = EXCLUDED.created_at",
                (team, channel, thread_ts, agent, int(time.time())),
            )

    def unbind_thread(
        self, team: str, channel: str, thread_ts: str
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                "DELETE FROM thread_bindings "
                "WHERE team_id=%s AND channel_id=%s AND thread_ts=%s",
                (team, channel, thread_ts),
            )
```

- [ ] **Step 1.8: Run the store tests and verify they pass**

```bash
uv run pytest packages/python/vystak-channel-slack/tests/test_store.py -v
```

Expected: all tests pass — both new (`thread_binding` family, 6 tests) and pre-existing (`channel_binding`, `user_pref`, `inviter`, `migrate_idempotent`, `make_store_*`).

- [ ] **Step 1.9: Run lint to confirm no regressions**

```bash
just lint-python
```

Expected: clean exit (zero ruff errors).

- [ ] **Step 1.10: Commit**

```bash
git add packages/python/vystak-channel-slack/src/vystak_channel_slack/store.py \
        packages/python/vystak-channel-slack/tests/test_store.py
git commit -m "$(cat <<'EOF'
feat(channel-slack): add thread_bindings table to RoutesStore

New (team, channel, thread_ts) -> agent table on SqliteStore +
PostgresStore, plus matching ABC methods. Lays groundwork for
follow-thread-without-mention behavior in the Slack runtime.

Refs: docs/superpowers/specs/2026-04-25-slack-agent-threads-design.md
EOF
)"
```

---

## Task 2: Create `threads.py` with the pure routing policy

**Files:**
- Create: `packages/python/vystak-channel-slack/src/vystak_channel_slack/threads.py`
- Create: `packages/python/vystak-channel-slack/tests/test_threads.py`

- [ ] **Step 2.1: Write failing tests for `route_thread_message`**

Create `packages/python/vystak-channel-slack/tests/test_threads.py` with:

```python
"""Tests for threads.py — the on-message routing policy."""

from __future__ import annotations

from vystak_channel_slack.threads import route_thread_message


class _FakeStore:
    """Minimal store stub exposing only thread_binding()."""

    def __init__(self, bindings: dict[tuple[str, str, str], str] | None = None):
        self._b = bindings or {}

    def thread_binding(self, team: str, channel: str, thread_ts: str) -> str | None:
        return self._b.get((team, channel, thread_ts))


def _call(**overrides):
    """Build a route_thread_message call with sensible defaults."""
    args = {
        "is_dm": False,
        "require_explicit_mention": False,
        "team": "T1",
        "channel": "C1",
        "thread_ts": "1700.111",
        "text": "hey",
        "bot_user_id": "UBOT",
        "store": _FakeStore({("T1", "C1", "1700.111"): "weather-agent"}),
    }
    args.update(overrides)
    return route_thread_message(**args)


def test_routes_to_bound_agent_when_thread_is_bound():
    assert _call() == "weather-agent"


def test_returns_none_for_dm():
    assert _call(is_dm=True) is None


def test_returns_none_when_explicit_mention_required():
    assert _call(require_explicit_mention=True) is None


def test_returns_none_when_no_thread_ts():
    assert _call(thread_ts=None) is None


def test_returns_none_when_text_mentions_bound_bot():
    """on_mention will already handle these — avoid double-reply."""
    assert _call(text="hi <@UBOT> please help") is None


def test_text_mentioning_other_agent_still_routes_to_bound_agent():
    """Sticky binding: <@U_other> in text doesn't release the thread."""
    assert _call(text="<@U_OTHER> what about you?") == "weather-agent"


def test_returns_none_when_thread_unbound():
    assert _call(store=_FakeStore({})) is None


def test_empty_bot_user_id_does_not_short_circuit():
    """A misconfigured BOT_USER_ID="" must not block all routing."""
    # text contains "<@>" which would never appear from real Slack; this just
    # checks the empty-string guard.
    result = _call(bot_user_id="", text="hello <@> world")
    assert result == "weather-agent"
```

- [ ] **Step 2.2: Run the tests and confirm they fail**

```bash
uv run pytest packages/python/vystak-channel-slack/tests/test_threads.py -v
```

Expected: `ModuleNotFoundError: No module named 'vystak_channel_slack.threads'`. All 8 tests fail at collection.

- [ ] **Step 2.3: Implement `threads.py`**

Create `packages/python/vystak-channel-slack/src/vystak_channel_slack/threads.py` with:

```python
"""On-message routing policy for Slack threads.

Decides whether a non-mention message in a Slack channel should be
forwarded to an agent bound to that thread. Pure function — the caller
hands in everything (event facts + a store) and gets back the agent
name or None.

Mirrors the resolver.py pattern: small, pure, unit-tested in isolation;
the slack-bolt runtime in server_template.py just calls it.
"""

from __future__ import annotations

from typing import Protocol


class _ThreadStore(Protocol):
    def thread_binding(
        self, team: str, channel: str, thread_ts: str
    ) -> str | None: ...


def route_thread_message(
    *,
    is_dm: bool,
    require_explicit_mention: bool,
    team: str,
    channel: str,
    thread_ts: str | None,
    text: str,
    bot_user_id: str,
    store: _ThreadStore,
) -> str | None:
    """Return the agent name to forward to, or None to ignore the message.

    None on any of:
        - DMs (the DM branch handles its own routing)
        - thread.require_explicit_mention=True (opt-out)
        - message is not in a thread (no thread_ts)
        - bot is directly mentioned in text (on_mention will handle it;
          avoid double-reply)
        - thread is not bound to any agent
    """
    if is_dm or require_explicit_mention:
        return None
    if not thread_ts:
        return None
    if bot_user_id and f"<@{bot_user_id}>" in text:
        return None
    return store.thread_binding(team, channel, thread_ts)
```

- [ ] **Step 2.4: Run the tests and verify they pass**

```bash
uv run pytest packages/python/vystak-channel-slack/tests/test_threads.py -v
```

Expected: all 8 tests pass.

- [ ] **Step 2.5: Run lint**

```bash
just lint-python
```

Expected: clean.

- [ ] **Step 2.6: Commit**

```bash
git add packages/python/vystak-channel-slack/src/vystak_channel_slack/threads.py \
        packages/python/vystak-channel-slack/tests/test_threads.py
git commit -m "$(cat <<'EOF'
feat(channel-slack): add threads.route_thread_message policy

Pure function deciding whether a non-mention message in a Slack
channel routes to the thread's bound agent. Mirrors resolver.py
shape: testable in isolation, called by server_template at runtime.
EOF
)"
```

---

## Task 3: Wire the policy into `server_template.py`

**Files:**
- Modify: `packages/python/vystak-channel-slack/src/vystak_channel_slack/server_template.py`
- Modify: `packages/python/vystak-channel-slack/tests/test_plugin.py`

The runtime change has three parts inside `SERVER_PY`:

1. Import `route_thread_message` from `threads`.
2. In `on_mention`: sticky-binding check before `_resolve()`; write binding after `_finalize()` succeeds.
3. In `on_message`: replace the non-DM early-return with a binding lookup + forward.

- [ ] **Step 3.1: Write failing tests confirming `SERVER_PY` content**

Add the following test class at the **end of** `packages/python/vystak-channel-slack/tests/test_plugin.py` (the file already imports `from vystak_channel_slack.server_template import SERVER_PY` in the existing `TestServerTemplateTransportBootstrap` class — these new tests follow the same pattern):

```python
class TestServerTemplateThreadBindings:
    """Slack agent threads — server.py wires up thread_bindings."""

    def test_imports_route_thread_message(self):
        from vystak_channel_slack.server_template import SERVER_PY

        assert "from vystak_channel_slack.threads import route_thread_message" in SERVER_PY

    def test_on_mention_writes_binding_after_finalize(self):
        """After _finalize succeeds, on_mention persists the binding."""
        from vystak_channel_slack.server_template import SERVER_PY

        assert "_store.set_thread_binding(" in SERVER_PY

    def test_on_mention_sticky_check_uses_binding(self):
        """If a binding exists, on_mention must use it instead of resolving."""
        from vystak_channel_slack.server_template import SERVER_PY

        # Sticky check looks up the binding before _resolve().
        assert "_store.thread_binding(" in SERVER_PY

    def test_on_message_calls_route_thread_message(self):
        """The non-DM branch in on_message must consult the policy."""
        from vystak_channel_slack.server_template import SERVER_PY

        assert "route_thread_message(" in SERVER_PY

    def test_on_message_no_longer_blanket_returns_for_non_dm(self):
        """The 'mentions are already handled by on_mention' early-return
        must be gone — replaced by the policy call."""
        from vystak_channel_slack.server_template import SERVER_PY

        assert "mentions are already handled by on_mention" not in SERVER_PY

    def test_require_explicit_mention_is_consulted(self):
        """The opt-out flag is passed to the policy."""
        from vystak_channel_slack.server_template import SERVER_PY

        assert "_THREAD_REQUIRE_EXPLICIT_MENTION" in SERVER_PY
        # Ensure it's no longer a dead variable: it's read after the
        # 'require_explicit_mention=' kwarg in the policy call.
        assert "require_explicit_mention=_THREAD_REQUIRE_EXPLICIT_MENTION" in SERVER_PY
```

- [ ] **Step 3.2: Run the new tests and confirm they fail**

```bash
uv run pytest packages/python/vystak-channel-slack/tests/test_plugin.py::TestServerTemplateThreadBindings -v
```

Expected: all 6 tests fail (none of the new strings are in `SERVER_PY` yet).

- [ ] **Step 3.3: Add the `route_thread_message` import to `SERVER_PY`**

Open `packages/python/vystak-channel-slack/src/vystak_channel_slack/server_template.py`. Find the import block (around lines 100-106 inside the `SERVER_PY = '''…'''` literal):

```python
from vystak.schema.service import Sqlite as _Sqlite  # noqa: E402
from vystak_channel_slack.store import make_store as _make_store  # noqa: E402
from vystak_channel_slack.resolver import ResolverConfig as _ResolverConfig  # noqa: E402
from vystak_channel_slack.resolver import resolve as _resolve  # noqa: E402
from vystak_channel_slack.resolver import Event as _Event  # noqa: E402
from vystak_channel_slack import commands as _commands  # noqa: E402
from vystak_channel_slack import welcome as _welcome  # noqa: E402
```

Add one new import line right after the resolver imports and before the `commands` import:

```python
from vystak_channel_slack.threads import route_thread_message  # noqa: E402
```

Final block looks like:

```python
from vystak.schema.service import Sqlite as _Sqlite  # noqa: E402
from vystak_channel_slack.store import make_store as _make_store  # noqa: E402
from vystak_channel_slack.resolver import ResolverConfig as _ResolverConfig  # noqa: E402
from vystak_channel_slack.resolver import resolve as _resolve  # noqa: E402
from vystak_channel_slack.resolver import Event as _Event  # noqa: E402
from vystak_channel_slack.threads import route_thread_message  # noqa: E402
from vystak_channel_slack import commands as _commands  # noqa: E402
from vystak_channel_slack import welcome as _welcome  # noqa: E402
```

- [ ] **Step 3.4: Add the sticky-binding check at the top of `on_mention`**

In the same file, find `async def on_mention(event, say, client):` (around line 369-370) and the line `agent_name = _resolve(ev, _resolver_cfg, _store)` (around line 386).

Replace just that single `agent_name = _resolve(ev, _resolver_cfg, _store)` line with:

```python
    # Sticky binding: if this thread is already bound, the binding wins
    # over whatever the resolver would return. Skipped at thread root
    # (thread_ts == ts) since no binding can exist yet.
    incoming_thread_ts = event.get("thread_ts")
    bound_agent = None
    if incoming_thread_ts and incoming_thread_ts != event.get("ts"):
        bound_agent = _store.thread_binding(
            event.get("team", ""), channel, incoming_thread_ts,
        )
    if bound_agent is not None:
        agent_name = bound_agent
    else:
        agent_name = _resolve(ev, _resolver_cfg, _store)
```

- [ ] **Step 3.5: Add the post-success binding write to `on_mention`**

In the same `on_mention` function, find the block right after `_finalize` succeeds (currently around lines 458-462):

```python
    reply = _to_slack_mrkdwn(raw_reply)
    try:
        await _finalize(client, say, placeholder, text=reply, thread_ts=reply_thread_ts)
        logger.info("mention posted ok")
    except Exception as exc:
        logger.exception("mention post failed: %s", exc)
```

Replace it with:

```python
    reply = _to_slack_mrkdwn(raw_reply)
    try:
        await _finalize(client, say, placeholder, text=reply, thread_ts=reply_thread_ts)
        logger.info("mention posted ok")
    except Exception as exc:
        logger.exception("mention post failed: %s", exc)
        return
    # Reply succeeded — claim this thread for the agent so subsequent
    # non-mention messages in it route here without re-mention.
    thread_key_ts = event.get("thread_ts") or event.get("ts")
    if thread_key_ts:
        _store.set_thread_binding(
            team=event.get("team", ""),
            channel=channel,
            thread_ts=thread_key_ts,
            agent=agent_name,
        )
```

- [ ] **Step 3.6: Replace the non-DM branch of `on_message` with the policy call**

In the same file, find `async def on_message(event, say, client):` (around line 466). The current shape is:

```python
async def on_message(event, say, client):
    if event.get("bot_id") or event.get("subtype"):
        logger.debug(
            "message ignored: bot_id=%s subtype=%s",
            event.get("bot_id"), event.get("subtype"),
        )
        return

    channel = event.get("channel", "")
    channel_name = event.get("channel_name") or channel
    user = event.get("user", "")
    is_dm = event.get("channel_type") == "im"

    if not is_dm:
        logger.debug("message ignored: not a DM (channel_type=%s)", event.get("channel_type"))
        return  # mentions are already handled by on_mention

    ev = _Event(...)
    agent_name = _resolve(ev, _resolver_cfg, _store)
    # ... rest of DM flow ...
```

Replace the `if not is_dm:` block (the 3 lines: `if not is_dm:`, `logger.debug(...)`, `return  # mentions are already handled by on_mention`) with the following block. Keep everything else (the DM flow below it) untouched:

```python
    if not is_dm:
        agent_name = route_thread_message(
            is_dm=False,
            require_explicit_mention=_THREAD_REQUIRE_EXPLICIT_MENTION,
            team=event.get("team", ""),
            channel=channel,
            thread_ts=event.get("thread_ts"),
            text=event.get("text", ""),
            bot_user_id=BOT_USER_ID,
            store=_store,
        )
        if agent_name is None:
            logger.debug(
                "channel message ignored channel=%s thread_ts=%s: no thread binding",
                channel, event.get("thread_ts"),
            )
            return
        if agent_name not in ROUTES:
            logger.warning(
                "thread message misrouted: agent=%s bound but not in transport routes %s",
                agent_name, list(ROUTES.keys()),
            )
            await say(
                text=(
                    f"Agent `{agent_name}` is bound to this thread but isn't reachable "
                    f"on the transport. Known routes: "
                    + (", ".join(f"`{a}`" for a in ROUTES) or "_none_")
                ),
                thread_ts=event.get("thread_ts"),
            )
            return
        session_id = _session_id(
            channel, event.get("thread_ts"), event.get("ts"), user,
        )
        text = event.get("text", "")
        reply_thread_ts = event.get("thread_ts")
        placeholder = await _post_placeholder(say, thread_ts=reply_thread_ts)
        logger.info(
            "thread-follow forward agent=%s session=%s",
            agent_name, session_id,
        )
        try:
            raw_reply = await _forward_to_agent(agent_name, text, session_id)
        except Exception as exc:
            logger.exception("thread-follow forward failed agent=%s: %s", agent_name, exc)
            await _finalize(
                client, say, placeholder,
                text=f"Sorry, I hit an error talking to *{agent_name}*: `{exc}`",
                thread_ts=reply_thread_ts,
            )
            return
        logger.info(
            "thread-follow reply len=%d preview=%r",
            len(raw_reply or ""), (raw_reply or "")[:120],
        )
        reply = _to_slack_mrkdwn(raw_reply)
        try:
            await _finalize(
                client, say, placeholder, text=reply, thread_ts=reply_thread_ts,
            )
            logger.info("thread-follow posted ok")
        except Exception as exc:
            logger.exception("thread-follow post failed: %s", exc)
        return
```

After this block, the existing DM flow (`ev = _Event(...)`, `agent_name = _resolve(...)`, etc.) continues unchanged.

- [ ] **Step 3.7: Run the plugin tests and verify they pass**

```bash
uv run pytest packages/python/vystak-channel-slack/tests/test_plugin.py -v
```

Expected: all tests pass — both new (`TestServerTemplateThreadBindings`, 6 tests) and pre-existing.

- [ ] **Step 3.8: Run the full slack package tests**

```bash
uv run pytest packages/python/vystak-channel-slack/ -v
```

Expected: every test passes (store, threads, plugin, resolver, commands, welcome). Docker-marked tests in `test_integration.py` skip unless Docker is reachable.

- [ ] **Step 3.9: Run lint**

```bash
just lint-python
```

Expected: clean.

- [ ] **Step 3.10: Commit**

```bash
git add packages/python/vystak-channel-slack/src/vystak_channel_slack/server_template.py \
        packages/python/vystak-channel-slack/tests/test_plugin.py
git commit -m "$(cat <<'EOF'
feat(channel-slack): follow Slack threads after first mention

server.py now persists a thread binding after every successful
on_mention reply, and consults that binding from on_message for
non-DM events via threads.route_thread_message. Honors the
thread.require_explicit_mention opt-out.

The previous "mentions are already handled by on_mention" early-return
on non-DMs is replaced by a thread-binding lookup. Sticky binding:
once a thread is bound to agent A, mentions of @agent-B in that
thread are read as text by A.

Refs: docs/superpowers/specs/2026-04-25-slack-agent-threads-design.md
EOF
)"
```

---

## Task 4: Update Slack channel docs

**Files:**
- Modify: `website/docs/channels/slack.md`

- [ ] **Step 4.1: Locate the "Thread context" section**

Open `website/docs/channels/slack.md`. Find the heading `## Thread context` (around line 207).

- [ ] **Step 4.2: Add a paragraph describing the default-on follow-thread behavior**

Find this block in the section:

```markdown
## Thread context

When the bot is `@mentioned` inside an existing thread (i.e. the event has a `thread_ts` distinct from its own `ts`), the runtime calls `conversations.replies` to fetch prior messages and prepends them to the agent's input wrapped in `<thread_history>...</thread_history>`. Bot's own past replies are labeled `bot` so the agent can distinguish them from user input.
```

Add the following paragraph immediately after it (before the existing `Disable per channel:` text):

```markdown
**Follow-the-thread behavior** — Once the bot has replied in a thread, every subsequent non-bot message in that thread is forwarded to the same agent without requiring re-mention. Each Slack thread is its own conversation session (the agent's session key is `slack:<channel>:<thread_ts>`), so memory stays scoped to the thread. Mentioning a different `@<agent>` inside the thread does **not** transfer the binding — the bound agent reads the new message verbatim and decides what to do.

To require an explicit `@mention` on every message and disable thread following:

```yaml
thread:
  require_explicit_mention: true
```
```

- [ ] **Step 4.3: Verify the docs build clean**

```bash
just docs-build
```

Expected: Docusaurus build succeeds, no broken markdown.

- [ ] **Step 4.4: Commit**

```bash
git add website/docs/channels/slack.md
git commit -m "$(cat <<'EOF'
docs(channels/slack): document follow-the-thread default

Once the bot replies in a thread, subsequent messages in that thread
route to the same agent without re-mention. Document the behavior
plus the thread.require_explicit_mention=true opt-out.
EOF
)"
```

---

## Task 5: Final verification

**Files:** none modified — verification only.

- [ ] **Step 5.1: Run the full Python test suite**

```bash
just test-python
```

Expected: every test passes. Docker-marked tests skip unless Docker is reachable.

- [ ] **Step 5.2: Run TypeScript gates**

```bash
just typecheck-typescript
just test-typescript
```

Expected: clean. (Pure-Python feature; TS gates should be unaffected.)

- [ ] **Step 5.3: Run the Slack release smoke cells**

```bash
uv run pytest packages/python/vystak-provider-docker/tests/release/ -v \
  -m "release_smoke or release_integration"
```

Expected: same pass/skip pattern as before — D1–D7 + A1/A2 cells. Slack-token-gated cells (D3/D5/D7/D8) skip unless `SLACK_BOT_TOKEN` + `SLACK_APP_TOKEN` are exported.

- [ ] **Step 5.4: Manual end-to-end check (docker-slack example)**

Requires real Slack tokens in `examples/docker-slack/.env`. Run:

```bash
cd examples/docker-slack && uv run vystak apply
```

Then in Slack:

1. In a public channel where the bot is invited: post `@<bot> hello`. The bot should reply, opening a thread.
2. In that same thread, reply with `tell me more` (no mention). The bot should reply again.
3. Restart the channel container: `docker restart vystak-channel-slack-main`.
4. In the same thread, reply with `still there?` (no mention). The bot should reply — the binding survived the restart.
5. Edit `examples/docker-slack/vystak.yaml` to add under the slack channel:
   ```yaml
   thread:
     require_explicit_mention: true
   ```
   Re-run `uv run vystak apply`.
6. In the same thread, reply with `now what?` (no mention). The bot should NOT reply — the opt-out is honoured.

If all six steps behave as described, the feature ships. Tear down with `uv run vystak destroy`.

- [ ] **Step 5.5: No commit needed for Task 5** — purely verification.

---

## Spec coverage checklist

| Spec section / requirement | Implemented in |
|---|---|
| Goal: follow-thread without re-mention | Task 3 (`on_message` non-DM branch) |
| Decision Q1: close gap on `require_explicit_mention=False` default | Task 3 (`require_explicit_mention=_THREAD_REQUIRE_EXPLICIT_MENTION` plumbed into `route_thread_message`) |
| Decision Q2: any bot reply claims the thread | Task 3 (`set_thread_binding` after `_finalize` in `on_mention` — the only path to a channel bot reply today) |
| Decision Q3: sticky binding wins over `@other-agent` | Task 3 (sticky check at top of `on_mention` + `<@BOT_USER_ID>` filter in `route_thread_message`) |
| Decision Q4: never expire (v1) | Task 1 (no TTL or pruning logic; `created_at` stored unread) |
| Data model: `thread_bindings` table | Task 1 (`_SCHEMA` + `_PG_SCHEMA`) |
| ABC: `thread_binding` / `set_thread_binding` / `unbind_thread` | Task 1 |
| Sqlite implementation | Task 1 |
| Postgres implementation | Task 1 |
| `migrate()` idempotent | Task 1 (Step 1.1, `test_migrate_creates_thread_bindings_table`) |
| `on_mention` sticky check | Task 3 (Step 3.4) |
| `on_mention` post-success write | Task 3 (Step 3.5) |
| `on_message` non-DM consults binding | Task 3 (Step 3.6) |
| `on_message` short-circuit when bot directly mentioned | Task 2 + Task 3 (`route_thread_message` returns None when text contains `<@BOT_USER_ID>`) |
| `require_explicit_mention=True` disables follow | Task 2 + Task 3 (policy returns None) |
| `unbind_thread` scaffolded for future `/vystak release` | Task 1 |
| Documentation update | Task 4 |
| Edge case 1 (mention at thread root) | Task 3 Step 3.5 (`thread_key_ts = thread_ts or ts`) |
| Edge case 2 (mention inside existing thread) | Task 3 Step 3.4 (sticky check) |
| Edge case 3 (`@agent-B` in `agent-A`-bound thread) | Task 2 (sticky binding test) + Task 3 (`route_thread_message` honours `bot_user_id` filter) |
| Edge case 4 (same bot mentioned in own thread) | Task 2 (`<@UBOT>` short-circuit test) |
| Edge case 5 (legacy threads predating feature) | Implicit: no `thread_bindings` row → `route_thread_message` returns None |
| Edge case 6 (store load on busy channels) | Task 3 Step 3.6 (`route_thread_message` short-circuits before store hit when no `thread_ts` or bot mention) |
| Edge case 7 (agent removed after binding) | Task 3 Step 3.6 (`agent_name not in ROUTES` warning) |
| Edge case 8 (Postgres migration idempotent) | Task 1 (`CREATE TABLE IF NOT EXISTS`) |
| Edge case 9 (race before `on_mention` finishes) | Acceptable per spec; no code needed |
| Acceptance criterion 1–6 | Task 5 manual checklist (1–4 → Steps 5.4.1–5.4.4; 5 → Steps 5.4.5–5.4.6; 6 → Steps 5.1–5.2) |
