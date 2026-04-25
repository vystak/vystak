# Slack Agent Threads — Design

**Date:** 2026-04-25
**Status:** Approved
**Scope:** `packages/python/vystak-channel-slack/` runtime + tests. No
schema changes, no agent-side changes, no other packages touched.

## Goal

Honor the documented `thread.require_explicit_mention=False` default that
the schema and `website/docs/channels/slack.md:182` already promise, but
the runtime never delivers. Once an agent has replied in a Slack thread,
all subsequent non-bot messages in that thread are forwarded to the same
agent without requiring re-mention. Each thread is its own conversation
session (already true via `_session_id`).

## Why

Today, only DMs and direct `@mention`s reach an agent. A user who wants
a back-and-forth in a channel must paste `@<agent>` on every line, which
is friction Slack threads were designed to remove. The schema and docs
already advertise the desired behavior; the runtime has the gap.

## Decisions captured during brainstorm

| # | Question | Decision |
|---|----------|----------|
| 1 | Frame check | Close the gap on the existing `require_explicit_mention=False` default. No new top-level concept. |
| 2 | What claims a thread? | Any bot reply (mention or auto-routed via `default_agent`/`ai_fallback`). |
| 3 | Mid-thread `@other-agent`? | Sticky — bound agent keeps the thread; mention text is read as input. |
| 4 | Binding lifetime | Never expire in v1. Slack threads naturally die; `/vystak release` and TTL deferred. |

## Architecture

Two-line runtime change inside `vystak-channel-slack`:

1. **Write** a `thread_binding` after every successful bot reply in
   `on_mention`.
2. **Read** the `thread_binding` at the top of `on_message` for non-DM
   events with a `thread_ts`; if hit, route to the bound agent.

No changes to `resolver.py`, `commands.py`, `welcome.py`, `plugin.py`,
schema, examples, or any other package.

## Data model

New table `thread_bindings` in `RoutesStore` (sqlite + postgres),
mirroring the existing `channel_bindings` pattern.

SQLite schema (added to `_SCHEMA` in `store.py`):

```sql
CREATE TABLE IF NOT EXISTS thread_bindings (
    team_id    TEXT    NOT NULL,
    channel_id TEXT    NOT NULL,
    thread_ts  TEXT    NOT NULL,
    agent_name TEXT    NOT NULL,
    created_at INTEGER NOT NULL,
    PRIMARY KEY (team_id, channel_id, thread_ts)
);
```

Postgres mirrors with `BIGINT created_at`, consistent with the existing
`_PG_SCHEMA` shape.

New `RoutesStore` ABC methods (with implementations on both stores):

```python
thread_binding(team: str, channel: str, thread_ts: str) -> str | None
set_thread_binding(team: str, channel: str, thread_ts: str, agent: str) -> None
unbind_thread(team: str, channel: str, thread_ts: str) -> None
```

`unbind_thread` is unused in v1 but scaffolded so a future `/vystak
release` slash command does not require another store migration.

`migrate()` runs the new `CREATE TABLE IF NOT EXISTS` alongside existing
schema. Idempotent on existing deployments — running against a Slack
state DB created before this change just adds the new table.

## Runtime flow

### `on_mention` — sticky binding + write after success

At the top of `on_mention`, before `_resolve()`:

```python
incoming_thread_ts = event.get("thread_ts")
if incoming_thread_ts and incoming_thread_ts != event.get("ts"):
    bound = _store.thread_binding(event.get("team", ""), channel, incoming_thread_ts)
    if bound is not None:
        agent_name = bound  # binding wins over the mention (Q3 sticky rule)
    else:
        agent_name = _resolve(ev, _resolver_cfg, _store)
else:
    agent_name = _resolve(ev, _resolver_cfg, _store)
```

After `_finalize()` posts the reply successfully (current line ~459),
write the binding:

```python
thread_key_ts = event.get("thread_ts") or event.get("ts")
_store.set_thread_binding(
    team=event.get("team", ""),
    channel=channel,
    thread_ts=thread_key_ts,
    agent=agent_name,
)
```

Write only on success — if the agent forward or post fails, no binding
is written. Re-mentions are idempotent via `INSERT OR REPLACE`.

### `on_message` — route bound thread replies

Replace the current early-return at `server_template.py:479` with:

```python
if not is_dm:
    if _THREAD_REQUIRE_EXPLICIT_MENTION:
        return  # opt-out: classic behavior
    thread_ts = event.get("thread_ts")
    if not thread_ts:
        return  # not a thread reply — ignore
    if BOT_USER_ID and f"<@{BOT_USER_ID}>" in event.get("text", ""):
        return  # on_mention will handle this; avoid double reply
    bound_agent = _store.thread_binding(
        event.get("team", ""), channel, thread_ts,
    )
    if bound_agent is None:
        return  # untracked thread
    agent_name = bound_agent
    # ... fall through to forward + reply (same shape as DM branch)
else:
    # ... existing DM resolution path unchanged
```

The DM branch keeps its current shape (`_resolve()` → user_pref →
default_agent). Only the non-DM branch changes from "always return" to
"look up binding, then forward."

### Forward + reply (shared between branches)

Once `agent_name` is set, the rest mirrors what `on_mention` already
does:

- Compute `session_id` via `_session_id(channel, thread_ts, ts, user)`
  — for thread messages this is `slack:{channel}:{thread_ts}`, the same
  key the original mention used. Continuity is automatic.
- `_post_placeholder` → `_forward_to_agent` → `_finalize` to update with
  the agent's reply, converted via `_to_slack_mrkdwn`.
- On forward failure, post the same `Sorry, I hit an error talking to
  *{agent_name}*` message as `on_mention` does today.

## Config

No new schema fields. The existing `SlackThreadConfig.require_explicit_mention:
bool = False` (`packages/python/vystak/src/vystak/schema/channel.py:43`)
is the toggle. Today it is loaded into `_THREAD_REQUIRE_EXPLICIT_MENTION`
at `server_template.py:267` but never read; this design wires it up.

| `thread.require_explicit_mention` | Behavior in non-DM thread reply |
|-----------------------------------|---------------------------------|
| `False` (default)                 | Look up `thread_binding`; if hit, route to bound agent. |
| `True`                            | Return early — today's behavior, no thread following. |

The legacy top-level alias `thread_require_explicit_mention` continues
to work via the existing merge in `plugin.py:81-84`.

## Documentation update

`website/docs/channels/slack.md`:

- The promise at `:182` ("Thread session continuity is **not** routing.
  Once an agent answers in a thread, subsequent replies inside that
  thread stay with the same agent…") becomes accurate when this ships.
  No edit required.
- The "Thread context" section at `:208` adds a paragraph describing
  the default-on follow-thread behavior and pointing at
  `thread.require_explicit_mention: true` as the opt-out.
- The schema example at `:132-136` already documents the field — no
  change.

## Edge cases

| # | Scenario | Behavior |
|---|----------|----------|
| 1 | Mention at thread root | Write binding under `ts` (which is the `thread_ts` of subsequent replies). |
| 2 | Mention inside existing thread | Sticky check first; if unbound, resolve normally and write binding. Existing `_fetch_thread_history` still runs for cold-start context. |
| 3 | `@agent-B` in `agent-A`-bound thread | Bot does not get `app_mention` (bot user IDs differ). Receives `message.channels` with `<@U_agentB>` in text; `<@BOT_USER_ID>` check sees a different ID, so doesn't short-circuit. Bound lookup hits → A reads the message verbatim. |
| 4 | Same bot mentioned again in its own thread | `app_mention` fires sticky check → bound A handles it. `message.channels` `<@BOT_USER_ID>` check fires → returns early. Exactly one reply. |
| 5 | Threads predating this feature | No `thread_bindings` row → `on_message` returns. Re-mention re-anchors. No back-fill from `conversations.replies`. |
| 6 | Bot in many channels — store load | Triple filter before SQLite: bot/subtype filter (already there) → `if not thread_ts: return` → `<@BOT_USER_ID>` check. Sub-millisecond PK lookup only for filtered survivors. |
| 7 | Agent removed from `channel.agents` after binding written | Lookup returns the now-unknown agent_name; `agent_name not in ROUTES` → post the same "isn't reachable on the transport" warning that `on_mention` emits today. |
| 8 | Postgres state with provider-managed connection | `migrate()` is idempotent — running on an existing state DB just adds the new table. |
| 9 | Race: 2nd message arrives before `on_mention` finishes | `on_message` finds no binding yet, drops it. Acceptable for v1; users almost always wait for a reply before continuing. |

## Testing

### Unit tests

`packages/python/vystak-channel-slack/tests/test_store.py` — extend with
parametrized coverage (sqlite + postgres) for:

- `set_thread_binding` then `thread_binding` returns the agent name
- `set_thread_binding` overwrites duplicate `(team, channel, thread_ts)`
- `thread_binding` returns `None` for unknown keys
- `unbind_thread` clears the row; subsequent `thread_binding` returns `None`
- `migrate()` is idempotent (run twice, no error, no row loss)

### Integration tests

`packages/python/vystak-channel-slack/tests/test_integration.py` —
extend with:

1. **mention writes binding** — simulate `app_mention` → after the
   mocked agent reply, assert `store.thread_binding(...)` returns the
   resolved agent.
2. **non-mention thread reply hits bound agent** — pre-populate a
   binding, simulate `message.channels` with matching `thread_ts` →
   assert agent client called with that agent and session_id
   `slack:{channel}:{thread_ts}`.
3. **non-thread channel message ignored** — `message.channels` with no
   `thread_ts` → assert no forward.
4. **untracked thread reply ignored** — `message.channels` with
   `thread_ts` but no binding row → assert no forward.
5. **bot mention in bound thread doesn't double-reply** — both events
   Slack delivers (`app_mention` + `message.channels` with
   `<@BOT_USER_ID>` in text) → assert exactly one forward.
6. **sticky binding ignores `@other-agent`** — bind thread to A,
   simulate `message.channels` with `<@U_agentB>` → forward goes to A.
7. **`require_explicit_mention=True` disables** — flag set, simulate
   `message.channels` in a bound thread → assert no forward.

Existing tests must keep passing unchanged: `on_mention` for new
threads, DM flow, slash commands, welcome flow, the existing
`_fetch_thread_history` path.

### Manual verification (docker-slack example)

```bash
cd examples/docker-slack && vystak apply
# 1. Mention bot in a channel — expect reply
# 2. Reply in the resulting thread without mention — expect reply
# 3. docker restart vystak-channel-slack-main
# 4. Reply in same thread without mention — expect reply (binding persisted)
# 5. Set thread.require_explicit_mention: true; vystak apply
# 6. Reply without mention — expect no reply
```

### Release tests

Existing Slack cells (D3, D5, D7, D8 from `test_plan.md`) stay as-is.
Optionally add a `release_slack`-marked test that mentions the bot,
posts a follow-up without mention, and asserts a second reply arrives
in the same thread.

## Out of scope (deferred to future work)

- `/vystak release` slash command to clear the current thread's
  binding. The `unbind_thread` store method is scaffolded for this.
- TTL-based pruning of stale `thread_bindings` rows. The `created_at`
  column is written but unread for now.
- Back-filling bindings for threads that predate this feature by
  scanning `conversations.replies` for prior bot turns.
- Multi-replica Slack channel containers — same single-replica caveat
  as the rest of the channel runtime today.

## Acceptance criteria

1. After a bot reply in a Slack channel thread, the next non-bot
   message in that thread is forwarded to the same agent without an
   `@mention`.
2. Behavior survives container restart (binding is in sqlite/postgres,
   not in-memory).
3. Mentioning `@other-agent` in a bound thread does not change the
   binding; the bound agent receives the message verbatim.
4. A bot user mention in a thread the bot is already bound to produces
   exactly one reply (no double from the dual-event delivery).
5. Setting `thread.require_explicit_mention: true` restores the
   pre-feature behavior — only `@mention`s are answered.
6. `just lint-python`, `just test-python`, `just typecheck-typescript`,
   `just test-typescript` all pass.
