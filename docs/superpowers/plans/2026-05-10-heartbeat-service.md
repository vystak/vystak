# Heartbeat Service v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the heartbeat scheduler out of channel runtimes into a new per-platform `vystak-heartbeat` deployable that calls agents via Transport (HTTP/NATS) and pushes alerts via a new ChannelDelivery interface (HTTP/NATS). Add per-heartbeat model override with session-pinned model storage.

**Architecture:** Heartbeat schedulers move into a new `vystak-heartbeat` container (auto-spawned per platform when any agent has heartbeat). Channels gain a new `deliver_message` abstract method served by an HTTP `POST /deliver` route or NATS subscription. Agents gain multi-model dispatch (`Agent.default_model` + `Agent.models`) and a sidecar `heartbeat_session_models` table. Strict 8-step migration: each step ends `just ci` green; the v1 channel-hosted scaffolding lives until step 8 lands.

**Tech Stack:** Python 3.11+, Pydantic v2, asyncio, croniter, FastAPI/uvicorn (HTTP delivery receiver), nats-py (NATS delivery), aiosqlite (sidecar tables), pytest. Touched packages: `vystak`, `vystak-channel-runtime`, `vystak-channel-{slack,discord,chat}`, `vystak-template-langchain-python`, `vystak-adapter-langchain`, `vystak-transport-{http,nats}`, `vystak-provider-{docker,azure}`, plus new `vystak-heartbeat`.

**Spec:** [`docs/superpowers/specs/2026-05-10-heartbeat-service-design.md`](../specs/2026-05-10-heartbeat-service-design.md)

---

## File map

### New files

| Path | Purpose |
|---|---|
| `packages/python/vystak-heartbeat/pyproject.toml` | New package metadata |
| `packages/python/vystak-heartbeat/src/vystak_heartbeat/__init__.py` | Package init |
| `packages/python/vystak-heartbeat/src/vystak_heartbeat/__main__.py` | Container entrypoint |
| `packages/python/vystak-heartbeat/src/vystak_heartbeat/scheduler.py` | `HeartbeatScheduler` (v2, transport-based) |
| `packages/python/vystak-heartbeat/src/vystak_heartbeat/session_store.py` | `HeartbeatSessionStore` ABC + InMemory + Sqlite impls |
| `packages/python/vystak-heartbeat/src/vystak_heartbeat/server_template.py` | Codegen `DOCKERFILE` + `REQUIREMENTS` strings |
| `packages/python/vystak-heartbeat/src/vystak_heartbeat/plugin.py` | `generate_code()` for the heartbeat container |
| `packages/python/vystak-heartbeat/tests/test_scheduler.py` | Unit tests for scheduler |
| `packages/python/vystak-heartbeat/tests/test_session_store.py` | Unit tests for session store |
| `packages/python/vystak-heartbeat/tests/test_plugin.py` | Codegen tests |
| `packages/python/vystak-channel-runtime/src/vystak_channel_runtime/delivery.py` | `DeliveryRequest` + `ChannelDelivery` ABC |
| `packages/python/vystak-channel-runtime/tests/test_delivery_receiver.py` | Receiver tests |
| `packages/python/vystak-transport-http/src/vystak_transport_http/delivery.py` | `HttpChannelDelivery` |
| `packages/python/vystak-transport-nats/src/vystak_transport_nats/delivery.py` | `NatsChannelDelivery` |
| `packages/python/vystak-transport-http/tests/test_delivery.py` | HTTP delivery tests |
| `packages/python/vystak-transport-nats/tests/test_delivery.py` | NATS delivery tests |
| `packages/python/vystak-provider-docker/src/vystak_provider_docker/nodes/heartbeat.py` | `DockerHeartbeatNode` |

### Modified files

| Path | Change |
|---|---|
| `packages/python/vystak/src/vystak/schema/agent.py` | Rename `model` → `default_model`; add `models: list[Model] = []` |
| `packages/python/vystak/src/vystak/schema/heartbeat.py` | Add `model: str \| None = None` |
| `packages/python/vystak/src/vystak/schema/multi_loader.py` | Extend `_validate_heartbeat_targets` to validate `heartbeat.model` against agent pool |
| `packages/python/vystak/src/vystak/hash/tree.py` | `brain` slot includes `Agent.models` (already covers `default_model`) |
| `packages/python/vystak-template-langchain-python/_vystak/runtime/graph.py` | Multi-model dispatcher; replaces single-model `build_model` |
| `packages/python/vystak-template-langchain-python/_vystak/runtime/app_factory.py` | A2A handler reads `metadata.model_override`/`session_id`; persists chosen model; echoes `model_resolved` in reply |
| `packages/python/vystak-template-langchain-python/_vystak/runtime/config.py` | Adds `heartbeat_session_models` sidecar table |
| `packages/python/vystak-channel-runtime/src/vystak_channel_runtime/runtime.py` | Add abstract `deliver_message`; `_start/_stop_delivery_receiver`; remove `_start_heartbeats`/`_stop_heartbeats`/`_handle_synthetic_event`/`_heartbeat_for_route`/`_heartbeats` (step 8) |
| `packages/python/vystak-channel-runtime/src/vystak_channel_runtime/heartbeat.py` | Remove `HeartbeatScheduler`/`enrich_routes_with_heartbeat`; keep only `is_heartbeat_ok`/`HEARTBEAT_OK`/`DEFAULT_PROMPT` (step 8) |
| `packages/python/vystak-channel-slack/src/vystak_channel_slack/runtime.py` | Implement `deliver_message`; remove `post_reply` heartbeat branch (step 8) |
| `packages/python/vystak-channel-slack/src/vystak_channel_slack/server_template.py` | Add `EXPOSE 9999` for HTTP delivery receiver |
| `packages/python/vystak-channel-slack/src/vystak_channel_slack/plugin.py` | Add `delivery_port` to channel_config; remove `_enrich_routes_with_heartbeat` call (step 8) |
| `packages/python/vystak-channel-discord/...` | Same shape as Slack |
| `packages/python/vystak-channel-chat/...` | Same shape as Slack |
| `packages/python/vystak-provider-docker/src/vystak_provider_docker/provider.py` | Auto-spawn `DockerHeartbeatNode` when any agent has heartbeat; build channel delivery URL map |
| `packages/python/vystak-provider-azure/src/vystak_provider_azure/...` | Mirror docker auto-spawn (lighter touch since release tests are gated) |
| `packages/python/vystak-provider-docker/tests/release/test_heartbeat.py` | Replace v1 channel-hosted test with v2 service-based cell |
| Every example with `model:` on agents | Sweep rename `model:` → `default_model:` |

---

## Task 1 — Step 1: Schema rename + `Agent.models` pool

**Why:** Mechanical rename. No behavior change. Sets up the pool that step 3 dispatches against.

**Files:**
- Modify: `packages/python/vystak/src/vystak/schema/agent.py`
- Modify: `packages/python/vystak/tests/test_agent.py` (and any test that constructs `Agent`)
- Modify: every `examples/*/vystak.yaml` and `examples/*/vystak.py` with `model:` on agents
- Modify: every generated `agent.model.*` reference in templates / codegen / tests

- [ ] **Step 1: Update Agent schema**

Edit `packages/python/vystak/src/vystak/schema/agent.py`. Find the line `model: Model` in the `Agent` class and replace:

```python
    default_model: Model
    models: list[Model] = []
```

- [ ] **Step 2: Sweep references in `vystak` package**

Search and replace within `packages/python/vystak/`:

```bash
grep -rln "agent\.model\b\|\.model:\s*Model\b\|^[^#]*\.model =" packages/python/vystak/src
```

For every match in non-test code, rename `agent.model` → `agent.default_model`. Pay attention to:
- `packages/python/vystak/src/vystak/hash/tree.py` (brain hash)
- `packages/python/vystak/src/vystak/schema/multi_loader.py` (model resolution from string ref)

- [ ] **Step 3: Sweep references in `vystak-adapter-langchain` codegen**

```bash
grep -rln "agent\.model\." packages/python/vystak-adapter-langchain
```

In `templates.py`, `a2a.py`, `responses.py`, `turn_core.py`, `compaction.py`: rename `agent.model` → `agent.default_model`. Do not rename inside generated string templates that say `agent.model` for a reason; check each occurrence in context.

- [ ] **Step 4: Sweep references in `vystak-template-langchain-python`**

```bash
grep -rln "agent\.model" packages/python/vystak-template-langchain-python
```

In `_vystak/runtime/graph.py:25`, `_vystak/runtime/graph.py:31`: `agent.model.provider.type` → `agent.default_model.provider.type`; `agent.model.model_name` → `agent.default_model.model_name`.

- [ ] **Step 5: Sweep all examples**

```bash
for f in examples/*/vystak.yaml; do sed -i '' 's/^\(    model:\)/    default_model:/' "$f"; done
for f in examples/*/vystak.py; do sed -i '' 's/Agent(\([^)]*\), model=/Agent(\1, default_model=/g' "$f"; done
```

(Manually verify each diff — the regex won't catch every shape.)

- [ ] **Step 6: Sweep tests**

```bash
grep -rln "model=Model\|agent\.model\b" packages/python/*/tests
```

For every test that constructs `Agent(model=...)`, rename the kwarg to `default_model=`. For every assertion/access on `agent.model`, rename to `agent.default_model`.

- [ ] **Step 7: Add `Agent.models` to hash brain slot**

Edit `packages/python/vystak/src/vystak/hash/tree.py`. Find the `brain = hash_model(agent.default_model)` line (formerly `agent.model`). Update to compose with `models`:

```python
    brain_pieces = [hash_model(agent.default_model)]
    brain_pieces.extend(hash_model(m) for m in sorted(agent.models, key=lambda m: m.name))
    brain = hashlib.sha256("|".join(brain_pieces).encode()).hexdigest()
```

- [ ] **Step 8: Run full test suite**

```bash
just lint-python
uv run pytest packages/python/ -q
```

Expected: all green. The diff is large but mechanical; if any test fails it's a missed reference.

- [ ] **Step 9: Commit**

```bash
git add packages/python/ examples/
git commit -m "refactor(schema): rename Agent.model → default_model + add Agent.models pool"
```

---

## Task 2 — Step 2: Add `Heartbeat.model` field

**Files:**
- Modify: `packages/python/vystak/src/vystak/schema/heartbeat.py`
- Modify: `packages/python/vystak/tests/test_heartbeat_schema.py`

- [ ] **Step 1: Write failing tests**

Append to `packages/python/vystak/tests/test_heartbeat_schema.py`:

```python
def test_heartbeat_model_default_none():
    hb = Heartbeat(schedule="*/30 * * * *", target_channel="x.channels.dev")
    assert hb.model is None


def test_heartbeat_model_round_trips():
    hb = Heartbeat(
        schedule="*/30 * * * *",
        target_channel="x.channels.dev",
        model="haiku",
    )
    restored = Heartbeat.model_validate(hb.model_dump())
    assert restored.model == "haiku"
```

- [ ] **Step 2: Run tests**

```bash
uv run pytest packages/python/vystak/tests/test_heartbeat_schema.py::test_heartbeat_model_default_none -v
```

Expected: FAIL — `Heartbeat` has no `model` field.

- [ ] **Step 3: Add field**

Edit `packages/python/vystak/src/vystak/schema/heartbeat.py`. Inside `Heartbeat`, after `enabled: bool = True`, add:

```python
    model: str | None = Field(
        None,
        description=(
            "Name of a Model in the agent's pool "
            "(default_model, *models). When set, agents honor it as a "
            "model_override in metadata. None → agent's default_model."
        ),
    )
```

- [ ] **Step 4: Verify**

```bash
uv run pytest packages/python/vystak/tests/test_heartbeat_schema.py -v
just lint-python
```

Expected: all heartbeat schema tests pass.

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak/src/vystak/schema/heartbeat.py packages/python/vystak/tests/test_heartbeat_schema.py
git commit -m "feat(schema): add Heartbeat.model override field"
```

---

## Task 3 — Step 3a: Multi-model dispatcher in langchain template

**Files:**
- Modify: `packages/python/vystak-template-langchain-python/_vystak/runtime/graph.py`
- Create: `packages/python/vystak-template-langchain-python/tests/test_multi_model.py`

- [ ] **Step 1: Write failing tests**

Create `packages/python/vystak-template-langchain-python/tests/test_multi_model.py`:

```python
"""Tests for multi-model dispatch in the langchain template runtime."""

from types import SimpleNamespace

import pytest

from _vystak.runtime.graph import build_models_pool, pick_model_name


def _model(name: str, provider_type: str = "anthropic", model_name: str = "x"):
    return SimpleNamespace(
        name=name,
        model_name=model_name,
        provider=SimpleNamespace(type=provider_type),
        parameters={},
    )


def _agent(default, extras):
    return SimpleNamespace(default_model=default, models=extras)


def test_pool_includes_default_and_models():
    a = _agent(_model("opus"), [_model("haiku"), _model("sonnet")])
    pool = build_models_pool(a)
    assert set(pool) == {"opus", "haiku", "sonnet"}


def test_pick_default_when_no_inputs():
    a = _agent(_model("opus"), [_model("haiku")])
    assert pick_model_name(a, session_stored=None, override=None) == "opus"


def test_pick_override_when_in_pool():
    a = _agent(_model("opus"), [_model("haiku")])
    assert pick_model_name(a, session_stored=None, override="haiku") == "haiku"


def test_pick_session_wins_over_override():
    a = _agent(_model("opus"), [_model("haiku"), _model("sonnet")])
    assert pick_model_name(a, session_stored="sonnet", override="haiku") == "sonnet"


def test_pick_falls_back_when_override_missing():
    """An override naming a model NOT in the pool falls back to default."""
    a = _agent(_model("opus"), [_model("haiku")])
    assert pick_model_name(a, session_stored=None, override="ghost") == "opus"
```

- [ ] **Step 2: Run tests**

```bash
uv run pytest packages/python/vystak-template-langchain-python/tests/test_multi_model.py -v
```

Expected: FAIL — `build_models_pool` and `pick_model_name` don't exist.

- [ ] **Step 3: Replace `graph.py` with multi-model dispatcher**

Edit `packages/python/vystak-template-langchain-python/_vystak/runtime/graph.py`:

```python
"""LangGraph react agent assembly with multi-model dispatch."""

from typing import Any

PROVIDER_FACTORIES = {
    "anthropic": ("langchain_anthropic", "ChatAnthropic"),
    "openai": ("langchain_openai", "ChatOpenAI"),
}


def build_models_pool(agent: Any) -> dict[str, Any]:
    """Return name → Model schema dict for default_model + every entry in models."""
    pool = {agent.default_model.name: agent.default_model}
    for m in agent.models:
        if m.name in pool:
            raise ValueError(f"duplicate model name {m.name!r} in agent pool")
        pool[m.name] = m
    return pool


def pick_model_name(agent: Any, *, session_stored: str | None, override: str | None) -> str:
    """Pick the model name to use for this turn.

    Precedence: session_stored > override > default. An override that
    names a model not in the pool falls back to default (a runtime
    warning is logged in app_factory; plan-time validation should
    catch this case before deploy).
    """
    pool = build_models_pool(agent)
    if session_stored and session_stored in pool:
        return session_stored
    if override and override in pool:
        return override
    return agent.default_model.name


def build_model(model_schema: Any, *, callbacks: list[Any] | None = None):
    """Construct one LangChain chat model from a single Model schema entry."""
    import importlib

    provider_type = model_schema.provider.type
    if provider_type not in PROVIDER_FACTORIES:
        raise ValueError(f"Unsupported provider: {provider_type}")
    module_name, cls_name = PROVIDER_FACTORIES[provider_type]
    module = importlib.import_module(module_name)
    cls = getattr(module, cls_name)
    kwargs: dict[str, Any] = {"model": model_schema.model_name}
    kwargs.update(model_schema.parameters or {})
    if callbacks:
        kwargs["callbacks"] = callbacks
    return cls(**kwargs)


def build_models_bindings(agent: Any, *, callbacks: list[Any] | None = None) -> dict[str, Any]:
    """Construct LangChain bindings for every model in the agent's pool.

    Returns name → bound model. Used by app_factory to dispatch turns.
    """
    return {
        name: build_model(schema, callbacks=callbacks)
        for name, schema in build_models_pool(agent).items()
    }


def build_graph(agent: Any, *, prompt, tools: list[Any], checkpointer: Any | None,
                model_name: str | None = None):
    """Build a react agent graph bound to a single chosen model.

    `model_name` selects from the agent's pool. None falls back to default.
    """
    from langgraph.prebuilt import create_react_agent

    from _vystak.runtime.token_usage import build_token_usage_callback

    callbacks = [build_token_usage_callback()]
    bindings = build_models_bindings(agent, callbacks=callbacks)
    chosen = model_name if model_name in bindings else agent.default_model.name
    return create_react_agent(
        model=bindings[chosen],
        tools=tools,
        prompt=prompt,
        checkpointer=checkpointer,
    )
```

- [ ] **Step 4: Verify tests pass**

```bash
uv run pytest packages/python/vystak-template-langchain-python/tests/test_multi_model.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Run full template test suite for regressions**

```bash
uv run pytest packages/python/vystak-template-langchain-python/ -v
```

Expected: all pre-existing tests still pass. (Existing tests use `agent.default_model` from Task 1's sweep.)

- [ ] **Step 6: Commit**

```bash
git add packages/python/vystak-template-langchain-python/_vystak/runtime/graph.py \
        packages/python/vystak-template-langchain-python/tests/test_multi_model.py
git commit -m "feat(template-langchain): multi-model pool + dispatcher in graph.py"
```

---

## Task 4 — Step 3b: A2A handler honors `model_override` + persists session-stored model

**Files:**
- Modify: `packages/python/vystak-template-langchain-python/_vystak/runtime/app_factory.py`
- Modify: `packages/python/vystak-template-langchain-python/_vystak/runtime/config.py`
- Modify: `packages/python/vystak-template-langchain-python/tests/test_app_factory.py` (or create if absent)

- [ ] **Step 1: Add sidecar table DDL**

Edit `packages/python/vystak-template-langchain-python/_vystak/runtime/config.py`. Add a constant near the top:

```python
HEARTBEAT_SESSIONS_DDL_SQLITE = """
CREATE TABLE IF NOT EXISTS heartbeat_session_models (
    session_id TEXT PRIMARY KEY,
    model_name TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

HEARTBEAT_SESSIONS_DDL_POSTGRES = """
CREATE TABLE IF NOT EXISTS heartbeat_session_models (
    session_id TEXT PRIMARY KEY,
    model_name TEXT NOT NULL,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""
```

Wherever `config.py` runs the existing checkpointer DDL, run the heartbeat DDL right after — same connection.

- [ ] **Step 2: Write failing tests for handler**

Append to `packages/python/vystak-template-langchain-python/tests/test_app_factory.py` (or create if file is absent):

```python
"""Tests for A2A handler model dispatch."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from _vystak.runtime.app_factory import (
    pick_model_for_turn,
    persist_model_choice,
)


@pytest.mark.asyncio
async def test_pick_model_uses_session_stored():
    sessions = AsyncMock()
    sessions.get_model = AsyncMock(return_value="haiku")
    agent = MagicMock(default_model=MagicMock(name="opus"),
                      models=[MagicMock(name="haiku")])
    chosen = await pick_model_for_turn(
        agent, sessions=sessions, session_id="t1", override="sonnet",
    )
    assert chosen == "haiku"


@pytest.mark.asyncio
async def test_pick_model_uses_override_when_no_session_stored():
    sessions = AsyncMock()
    sessions.get_model = AsyncMock(return_value=None)
    agent = MagicMock()
    agent.default_model.name = "opus"
    haiku = MagicMock(); haiku.name = "haiku"
    agent.models = [haiku]
    chosen = await pick_model_for_turn(
        agent, sessions=sessions, session_id="t1", override="haiku",
    )
    assert chosen == "haiku"


@pytest.mark.asyncio
async def test_persist_model_writes_only_when_no_session_stored():
    sessions = AsyncMock()
    sessions.get_model = AsyncMock(return_value=None)
    sessions.set_model = AsyncMock()
    await persist_model_choice(
        sessions=sessions, session_id="t1", chosen="haiku",
    )
    sessions.set_model.assert_awaited_once_with("t1", "haiku")


@pytest.mark.asyncio
async def test_persist_model_skips_when_session_already_has_one():
    sessions = AsyncMock()
    sessions.get_model = AsyncMock(return_value="haiku")
    sessions.set_model = AsyncMock()
    await persist_model_choice(
        sessions=sessions, session_id="t1", chosen="haiku",
    )
    sessions.set_model.assert_not_called()
```

- [ ] **Step 3: Implement helpers in `app_factory.py`**

Edit `packages/python/vystak-template-langchain-python/_vystak/runtime/app_factory.py`. Add (near the existing turn-handling code):

```python
from _vystak.runtime.graph import pick_model_name


async def pick_model_for_turn(
    agent: Any, *, sessions, session_id: str, override: str | None,
) -> str:
    """Resolve the model name to use for this turn.

    Reads session-stored first; falls back to override; falls back to default.
    Does NOT persist — call persist_model_choice after the LLM call succeeds.
    """
    stored = await sessions.get_model(session_id)
    return pick_model_name(agent, session_stored=stored, override=override)


async def persist_model_choice(
    *, sessions, session_id: str, chosen: str,
) -> None:
    """Persist `chosen` only if the session does not already have a model."""
    stored = await sessions.get_model(session_id)
    if stored is None:
        await sessions.set_model(session_id, chosen)
```

In the existing A2A turn handler (find the function that calls `build_graph` and runs the LLM), wire in:

```python
session_id = request.metadata.get("session_id") or request.thread_id or correlation_id
override = request.metadata.get("model_override")
chosen = await pick_model_for_turn(
    agent, sessions=heartbeat_sessions, session_id=session_id, override=override,
)
graph = build_graph(agent, prompt=prompt, tools=tools, checkpointer=checkpointer,
                   model_name=chosen)
# ... run graph ...
await persist_model_choice(sessions=heartbeat_sessions, session_id=session_id, chosen=chosen)
# ... include in reply ...
reply.metadata = {**(reply.metadata or {}), "model_resolved": chosen}
```

(`heartbeat_sessions` is a new `HeartbeatSessionStore`-typed dependency; resolved from the same DB connection as the checkpointer in app startup.)

- [ ] **Step 4: Tests pass**

```bash
uv run pytest packages/python/vystak-template-langchain-python/tests/test_app_factory.py -v
just lint-python
```

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-template-langchain-python/
git commit -m "feat(template-langchain): A2A handler honors model_override + persists choice"
```

---

## Task 5 — Step 3c: Heartbeat session-store sidecar in agent

**Note:** Task 4 introduces `heartbeat_sessions` as a parameter; this task implements it on the agent side.

**Files:**
- Create: `packages/python/vystak-template-langchain-python/_vystak/runtime/heartbeat_sessions.py`
- Modify: `packages/python/vystak-template-langchain-python/_vystak/runtime/app_factory.py` (wire into startup)
- Create: `packages/python/vystak-template-langchain-python/tests/test_heartbeat_sessions.py`

- [ ] **Step 1: Write failing tests**

```python
"""Sidecar `heartbeat_session_models` table tests."""
from pathlib import Path

import pytest

from _vystak.runtime.heartbeat_sessions import (
    SqliteHeartbeatSessions,
    InMemoryHeartbeatSessions,
)


@pytest.mark.asyncio
async def test_in_memory_get_set_round_trip():
    s = InMemoryHeartbeatSessions()
    assert await s.get_model("t1") is None
    await s.set_model("t1", "haiku")
    assert await s.get_model("t1") == "haiku"


@pytest.mark.asyncio
async def test_sqlite_persistence_across_instances(tmp_path: Path):
    db = tmp_path / "x.db"
    s1 = SqliteHeartbeatSessions(str(db))
    await s1.set_model("t1", "haiku")
    await s1.close()
    s2 = SqliteHeartbeatSessions(str(db))
    assert await s2.get_model("t1") == "haiku"
    await s2.close()


@pytest.mark.asyncio
async def test_sqlite_overwrite():
    s = SqliteHeartbeatSessions(":memory:")
    await s.set_model("t1", "haiku")
    await s.set_model("t1", "sonnet")
    assert await s.get_model("t1") == "sonnet"
```

- [ ] **Step 2: Run tests, verify FAIL**

- [ ] **Step 3: Implement**

Create `packages/python/vystak-template-langchain-python/_vystak/runtime/heartbeat_sessions.py`:

```python
"""Sidecar store for the per-thread chosen model."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod

import aiosqlite


class HeartbeatSessions(ABC):
    @abstractmethod
    async def get_model(self, session_id: str) -> str | None: ...

    @abstractmethod
    async def set_model(self, session_id: str, model_name: str) -> None: ...

    async def close(self) -> None:
        return None


class InMemoryHeartbeatSessions(HeartbeatSessions):
    def __init__(self) -> None:
        self._d: dict[str, str] = {}

    async def get_model(self, session_id: str) -> str | None:
        return self._d.get(session_id)

    async def set_model(self, session_id: str, model_name: str) -> None:
        self._d[session_id] = model_name


_DDL = """
CREATE TABLE IF NOT EXISTS heartbeat_session_models (
    session_id TEXT PRIMARY KEY,
    model_name TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


class SqliteHeartbeatSessions(HeartbeatSessions):
    def __init__(self, path: str) -> None:
        self._path = path
        self._conn: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()

    async def _ensure(self) -> aiosqlite.Connection:
        if self._conn is not None:
            return self._conn
        async with self._lock:
            if self._conn is not None:
                return self._conn
            conn = await aiosqlite.connect(self._path)
            await conn.execute(_DDL)
            await conn.commit()
            self._conn = conn
            return conn

    async def get_model(self, session_id: str) -> str | None:
        conn = await self._ensure()
        cur = await conn.execute(
            "SELECT model_name FROM heartbeat_session_models WHERE session_id=?",
            (session_id,),
        )
        row = await cur.fetchone()
        return row[0] if row else None

    async def set_model(self, session_id: str, model_name: str) -> None:
        conn = await self._ensure()
        await conn.execute(
            """
            INSERT INTO heartbeat_session_models (session_id, model_name)
            VALUES (?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                model_name = excluded.model_name,
                updated_at = CURRENT_TIMESTAMP
            """,
            (session_id, model_name),
        )
        await conn.commit()

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None
```

- [ ] **Step 4: Wire into `app_factory.py` startup**

In the FastAPI lifespan / startup hook, instantiate based on the agent's session config:

```python
from _vystak.runtime.heartbeat_sessions import (
    InMemoryHeartbeatSessions,
    SqliteHeartbeatSessions,
)

# Inside startup:
sessions_cfg = agent.sessions  # ServiceType
if sessions_cfg and sessions_cfg.type == "sqlite":
    heartbeat_sessions = SqliteHeartbeatSessions(sessions_cfg.path)
else:
    # Postgres or no config → in-memory for now (Postgres impl in a follow-up)
    heartbeat_sessions = InMemoryHeartbeatSessions()
```

For Postgres backends, add a follow-up implementation later; in-memory is acceptable for v1 since the existing langgraph postgres checkpointer covers conversation continuity. Mark this with a `# TODO(heartbeat): Postgres impl` comment.

- [ ] **Step 5: Tests + commit**

```bash
uv run pytest packages/python/vystak-template-langchain-python/tests/test_heartbeat_sessions.py -v
just lint-python
git add packages/python/vystak-template-langchain-python/
git commit -m "feat(template-langchain): heartbeat_session_models sidecar table + store"
```

---

## Task 6 — Step 4: Plan-time validation for `Heartbeat.model`

**Files:**
- Modify: `packages/python/vystak/src/vystak/schema/multi_loader.py`
- Modify: `packages/python/vystak/tests/test_heartbeat_schema.py`

- [ ] **Step 1: Tests**

Append:

```python
def test_heartbeat_model_in_pool_passes(tmp_path):
    import yaml
    from vystak.schema.multi_loader import load_multi_yaml
    text = """
providers: {anthropic: {type: anthropic}, docker: {type: docker}}
platforms: {local: {type: docker, provider: docker, namespace: dev}}
models:
  opus:   {provider: anthropic, model_name: claude-opus-4-7}
  haiku:  {provider: anthropic, model_name: claude-haiku-4-5}
agents:
  - name: bot
    framework: langchain-python
    default_model: opus
    models: [haiku]
    platform: local
    heartbeat:
      schedule: "*/30 * * * *"
      target_channel: chat-main.channels.dev
      model: haiku
channels:
  - {name: chat-main, type: chat, platform: local, agents: [bot]}
"""
    load_multi_yaml(yaml.safe_load(text))   # must not raise


def test_heartbeat_model_not_in_pool_rejected():
    import yaml
    from vystak.schema.multi_loader import load_multi_yaml
    text = """
providers: {anthropic: {type: anthropic}, docker: {type: docker}}
platforms: {local: {type: docker, provider: docker, namespace: dev}}
models:
  opus:  {provider: anthropic, model_name: claude-opus-4-7}
agents:
  - name: bot
    framework: langchain-python
    default_model: opus
    platform: local
    heartbeat:
      schedule: "*/30 * * * *"
      target_channel: chat-main.channels.dev
      model: ghost
channels:
  - {name: chat-main, type: chat, platform: local, agents: [bot]}
"""
    with pytest.raises(ValueError, match="not in agent's model pool"):
        load_multi_yaml(yaml.safe_load(text))
```

- [ ] **Step 2: Verify FAIL**

- [ ] **Step 3: Extend validator**

Edit `packages/python/vystak/src/vystak/schema/multi_loader.py`. In `_validate_heartbeat_targets`, after the existing `routed = …` check:

```python
        if agent.heartbeat.model is not None:
            pool = {agent.default_model.name, *(m.name for m in agent.models)}
            if agent.heartbeat.model not in pool:
                raise ValueError(
                    f"agent '{agent.name}' heartbeat.model "
                    f"'{agent.heartbeat.model}' not in agent's model pool "
                    f"(have: {sorted(pool)})"
                )
```

- [ ] **Step 4: Verify pass + commit**

```bash
uv run pytest packages/python/vystak/tests/test_heartbeat_schema.py -v
git add packages/python/vystak/
git commit -m "feat(schema): plan-time validation of Heartbeat.model against agent pool"
```

---

## Task 7 — Step 5a: `vystak-heartbeat` package scaffold

**Files:**
- Create: `packages/python/vystak-heartbeat/pyproject.toml`
- Create: `packages/python/vystak-heartbeat/src/vystak_heartbeat/__init__.py` (empty)
- Create: `packages/python/vystak-heartbeat/src/vystak_heartbeat/__main__.py` (placeholder; full impl in Task 8)
- Modify: `pnpm-workspace.yaml` and root `pyproject.toml` to register the new uv workspace member

- [ ] **Step 1: Scaffold pyproject.toml**

Mirror `vystak-channel-runtime/pyproject.toml`'s shape:

```toml
[project]
name = "vystak-heartbeat"
dynamic = ["version"]
description = "Vystak heartbeat service — periodic agent invocation + channel push delivery"
readme = "README.md"
requires-python = ">=3.11"
license = "Apache-2.0"
authors = [{ name = "Anatoliy Kolodkin", email = "11351966+akolodkin@users.noreply.github.com" }]
dependencies = [
    "vystak>=0.1.0",
    "vystak-channel-runtime>=0.1.0",
    "httpx>=0.27",
    "aiosqlite>=0.20",
    "pydantic>=2.7",
    "nats-py>=2.6",
    "croniter>=2.0",
    "opentelemetry-api>=1.27",
    "opentelemetry-sdk>=1.27",
    "opentelemetry-exporter-otlp-proto-grpc>=1.27",
]
[build-system]
requires = ["hatchling", "hatch-vcs"]
build-backend = "hatchling.build"
[tool.hatch.build.targets.wheel]
packages = ["src/vystak_heartbeat"]
[tool.hatch.version]
source = "vcs"
raw-options = {root = "../../.."}
[tool.uv.sources]
vystak = { workspace = true }
vystak-channel-runtime = { workspace = true }
[tool.pytest.ini_options]
asyncio_mode = "auto"
```

- [ ] **Step 2: Touch `__init__.py`** (empty file)

- [ ] **Step 3: Stub `__main__.py`**

```python
"""vystak-heartbeat container entrypoint. Full impl in Task 8."""

if __name__ == "__main__":
    raise NotImplementedError
```

- [ ] **Step 4: Verify uv sees the package**

```bash
uv sync
uv run python -c "import vystak_heartbeat"
```

Expected: import succeeds.

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-heartbeat/ pyproject.toml uv.lock
git commit -m "feat(vystak-heartbeat): package scaffold"
```

---

## Task 8 — Step 5b: `HeartbeatScheduler` v2

**Files:**
- Create: `packages/python/vystak-heartbeat/src/vystak_heartbeat/scheduler.py`
- Create: `packages/python/vystak-heartbeat/tests/test_scheduler.py`

- [ ] **Step 1: Tests** — copy and adapt the v1 scheduler tests, swapping `runtime._handle_synthetic_event` for `transport.send_task` and `delivery.deliver`. Eight tests covering:
  - skip_when_busy
  - thread resolution (pinned + missing)
  - isolated_session synthetic id
  - prompt default vs override
  - busy flag resets on transport error
  - is_heartbeat_ok suppresses delivery
  - non-OK reply triggers delivery
  - session_store records `model_resolved` on first resolve only

```python
"""Tests for v2 HeartbeatScheduler (transport + delivery)."""

from unittest.mock import AsyncMock

import pytest
from vystak.schema.heartbeat import Heartbeat

from vystak_heartbeat.scheduler import HeartbeatScheduler
from vystak_heartbeat.session_store import InMemoryStore


def _hb(**overrides):
    base = {"schedule": "*/30 * * * *", "target_channel": "x.channels.dev"}
    base.update(overrides)
    return Heartbeat(**base)


def _scheduler(**deps):
    base = dict(
        agent_name="bot",
        agent_canonical="bot.agents.dev",
        channel_canonical="x.channels.dev",
        heartbeat=_hb(target_thread="C1"),
        transport=AsyncMock(),
        delivery=AsyncMock(),
        sessions=InMemoryStore(),
    )
    base.update(deps)
    return HeartbeatScheduler(**base)


@pytest.mark.asyncio
async def test_fire_calls_transport_with_metadata():
    sch = _scheduler()
    sch.transport.send_task = AsyncMock(return_value=AsyncMock(text="hi", metadata={}))
    await sch._fire()
    args, kwargs = sch.transport.send_task.call_args
    md = kwargs.get("metadata") or args[2]
    assert md["heartbeat"] is True
    assert md["session_id"]


@pytest.mark.asyncio
async def test_fire_delivers_alert_when_not_ok():
    sch = _scheduler()
    sch.transport.send_task = AsyncMock(
        return_value=AsyncMock(text="alert!", metadata={"model_resolved": "haiku"}),
    )
    await sch._fire()
    sch.delivery.deliver.assert_awaited_once()


@pytest.mark.asyncio
async def test_fire_skips_delivery_when_heartbeat_ok():
    sch = _scheduler()
    sch.transport.send_task = AsyncMock(
        return_value=AsyncMock(text="HEARTBEAT_OK", metadata={"model_resolved": "haiku"}),
    )
    await sch._fire()
    sch.delivery.deliver.assert_not_called()


@pytest.mark.asyncio
async def test_fire_persists_model_on_first_resolve():
    sessions = InMemoryStore()
    sch = _scheduler(
        heartbeat=_hb(target_thread="C1", isolated_session=False, model="opus"),
        sessions=sessions,
    )
    sch.transport.send_task = AsyncMock(
        return_value=AsyncMock(text="alert", metadata={"model_resolved": "haiku"}),
    )
    await sch._fire()
    assert await sessions.get_model("C1") == "haiku"


@pytest.mark.asyncio
async def test_fire_does_not_overwrite_stored_model():
    sessions = InMemoryStore()
    await sessions.set_model("C1", "haiku")
    sch = _scheduler(
        heartbeat=_hb(target_thread="C1", isolated_session=False),
        sessions=sessions,
    )
    sch.transport.send_task = AsyncMock(
        return_value=AsyncMock(text="alert", metadata={"model_resolved": "sonnet"}),
    )
    await sch._fire()
    assert await sessions.get_model("C1") == "haiku"


@pytest.mark.asyncio
async def test_skip_when_busy():
    sch = _scheduler()
    sch._busy = True
    await sch._fire()
    sch.transport.send_task.assert_not_called()


@pytest.mark.asyncio
async def test_busy_resets_on_transport_error():
    sch = _scheduler()
    sch.transport.send_task = AsyncMock(side_effect=RuntimeError("boom"))
    with pytest.raises(RuntimeError):
        await sch._fire()
    assert sch._busy is False


@pytest.mark.asyncio
async def test_no_thread_skips_silently():
    sch = _scheduler(heartbeat=_hb())  # no target_thread, no binding store
    await sch._fire()
    sch.transport.send_task.assert_not_called()
```

- [ ] **Step 2: Verify FAIL**

- [ ] **Step 3: Implement**

Create `packages/python/vystak-heartbeat/src/vystak_heartbeat/scheduler.py`:

```python
"""HeartbeatScheduler v2 — uses Transport + ChannelDelivery."""

from __future__ import annotations

import asyncio
import logging
import secrets
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from croniter import croniter
from vystak.schema.heartbeat import Heartbeat
from vystak.transport import A2AMessage, AgentRef, Transport
from vystak.transport.message import TextPart
from vystak_channel_runtime.delivery import ChannelDelivery, DeliveryRequest
from vystak_channel_runtime.heartbeat import (
    DEFAULT_PROMPT,
    HEARTBEAT_OK,
    is_heartbeat_ok,
)
from vystak_heartbeat.session_store import HeartbeatSessionStore

logger = logging.getLogger("vystak.heartbeat.scheduler")


class HeartbeatScheduler:
    def __init__(
        self,
        *,
        agent_name: str,
        agent_canonical: str,
        channel_canonical: str,
        heartbeat: Heartbeat,
        transport: Transport,
        delivery: ChannelDelivery,
        sessions: HeartbeatSessionStore,
    ) -> None:
        self.agent_name = agent_name
        self.agent_canonical = agent_canonical
        self.channel_canonical = channel_canonical
        self.hb = heartbeat
        self.transport = transport
        self.delivery = delivery
        self.sessions = sessions
        self._task: asyncio.Task | None = None
        self._busy: bool = False

    async def start(self) -> None:
        if not self.hb.enabled:
            return
        self._task = asyncio.create_task(self._run(), name=f"hb-{self.agent_name}")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("scheduler task exited with error on stop")

    async def _resolve_thread(self) -> str | None:
        if self.hb.target_thread is not None:
            return self.hb.target_thread
        # No last-binding lookup in v2 — heartbeat service has no
        # ChannelStore. If `target_thread` is unset, skip.
        return None

    async def _fire(self) -> None:
        if self.hb.skip_when_busy and self._busy:
            logger.info("heartbeat.skipped agent=%s reason=busy", self.agent_name)
            return
        thread_id = await self._resolve_thread()
        if thread_id is None:
            logger.debug("heartbeat.skipped agent=%s reason=no-thread", self.agent_name)
            return

        if self.hb.isolated_session:
            session_id = f"__heartbeat__{int(time.time())}_{secrets.token_hex(4)}"
        else:
            session_id = thread_id

        stored = await self.sessions.get_model(session_id)
        request_model = stored or self.hb.model

        self._busy = True
        try:
            logger.info(
                "heartbeat.fired agent=%s thread=%s",
                self.agent_name, thread_id,
            )
            reply = await self.transport.send_task(
                AgentRef(canonical_name=self.agent_canonical),
                A2AMessage(
                    parts=[TextPart(text=self.hb.prompt or DEFAULT_PROMPT)],
                    correlation_id=session_id,
                ),
                metadata={
                    "heartbeat": True,
                    "model_override": request_model,
                    "session_id": session_id,
                },
                timeout=120,
            )
            chosen = (getattr(reply, "metadata", None) or {}).get("model_resolved")
            if chosen and stored is None:
                await self.sessions.set_model(session_id, chosen)

            if is_heartbeat_ok(reply.text or "", self.hb.ack_max_chars):
                logger.info("heartbeat.acked agent=%s thread=%s",
                            self.agent_name, thread_id)
                return

            await self.delivery.deliver(
                self.channel_canonical,
                DeliveryRequest(
                    thread_id=thread_id,
                    text=reply.text,
                    metadata={
                        "heartbeat": True,
                        "agent": self.agent_name,
                        "fired_at": datetime.utcnow().isoformat() + "Z",
                    },
                ),
            )
        finally:
            self._busy = False

    async def _run(self) -> None:
        try:
            tz = ZoneInfo(self.hb.timezone)
        except Exception:
            logger.exception("invalid timezone %s — disabling scheduler %s",
                             self.hb.timezone, self.agent_name)
            return
        cron = croniter(self.hb.schedule, datetime.now(tz))
        while True:
            try:
                next_at = cron.get_next(datetime)
            except Exception:
                logger.exception("cron error agent=%s — sleeping 60s",
                                 self.agent_name)
                await asyncio.sleep(60)
                continue
            delay = max(0.0, (next_at - datetime.now(tz)).total_seconds())
            try:
                await asyncio.sleep(delay)
            except asyncio.CancelledError:
                raise
            try:
                await self._fire()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("fire failed agent=%s", self.agent_name)
```

- [ ] **Step 4: Verify pass + commit**

```bash
uv run pytest packages/python/vystak-heartbeat/tests/test_scheduler.py -v
just lint-python
git add packages/python/vystak-heartbeat/
git commit -m "feat(vystak-heartbeat): HeartbeatScheduler v2 with Transport + ChannelDelivery"
```

---

## Task 9 — Step 5c: Heartbeat session store

**Files:**
- Create: `packages/python/vystak-heartbeat/src/vystak_heartbeat/session_store.py`
- Create: `packages/python/vystak-heartbeat/tests/test_session_store.py`

Implementation is identical in shape to Task 5's `HeartbeatSessions` (same DDL, same SQLite logic) but lives in the heartbeat service package. Reuse the code; do not import from the langchain template (different package).

- [ ] **Step 1: Tests** — same three tests from Task 5 (in-memory round-trip, sqlite persistence across instances, sqlite overwrite). Adjust the import:

```python
from vystak_heartbeat.session_store import (
    InMemoryStore,
    SqliteStore,
    HeartbeatSessionStore,
)
```

- [ ] **Step 2: Implement** — copy Task 5's body to `packages/python/vystak-heartbeat/src/vystak_heartbeat/session_store.py`, renaming class `HeartbeatSessions` → `HeartbeatSessionStore` and `InMemoryHeartbeatSessions` → `InMemoryStore`, `SqliteHeartbeatSessions` → `SqliteStore`. Keep DDL identical to the agent-side version so future migration to a shared package is mechanical.

- [ ] **Step 3: Verify + commit**

```bash
uv run pytest packages/python/vystak-heartbeat/tests/test_session_store.py -v
git add packages/python/vystak-heartbeat/
git commit -m "feat(vystak-heartbeat): session_store with InMemory + Sqlite impls"
```

---

## Task 10 — Step 5d: Heartbeat service entrypoint + plugin

**Files:**
- Modify: `packages/python/vystak-heartbeat/src/vystak_heartbeat/__main__.py` (full impl)
- Create: `packages/python/vystak-heartbeat/src/vystak_heartbeat/server_template.py`
- Create: `packages/python/vystak-heartbeat/src/vystak_heartbeat/plugin.py`
- Create: `packages/python/vystak-heartbeat/tests/test_plugin.py`

- [ ] **Step 1: `server_template.py`**

```python
"""Build-time artifacts for the vystak-heartbeat container."""

from __future__ import annotations

REQUIREMENTS = """\
httpx>=0.27
aiosqlite>=0.20
pydantic>=2.0
nats-py>=2.6
croniter>=2.0
opentelemetry-api>=1.27
opentelemetry-sdk>=1.27
opentelemetry-exporter-otlp-proto-grpc>=1.27
"""

DOCKERFILE = """\
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN mkdir -p /etc/vystak /data
COPY . .
RUN cp service_config.json routes.json /etc/vystak/ 2>/dev/null || true
ENV VYSTAK_CONFIG_DIR=/etc/vystak PYTHONPATH=/app
CMD ["python", "-m", "vystak_heartbeat"]
"""
```

- [ ] **Step 2: `__main__.py`**

```python
"""vystak-heartbeat container entrypoint."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
from pathlib import Path

from vystak.schema.heartbeat import Heartbeat
from vystak_channel_runtime.delivery import ChannelDelivery
from vystak_heartbeat.scheduler import HeartbeatScheduler
from vystak_heartbeat.session_store import (
    InMemoryStore,
    SqliteStore,
    HeartbeatSessionStore,
)

logger = logging.getLogger("vystak.heartbeat.main")


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text())


def _build_transport(cfg: dict):
    """Construct a Transport based on service_config.json transport.type."""
    t = cfg.get("transport", {})
    if t.get("type") == "nats":
        from vystak_transport_nats.transport import NatsTransport
        return NatsTransport(t["url"], routes=cfg.get("agent_addresses", {}))
    from vystak_transport_http.transport import HttpTransport
    return HttpTransport(routes=cfg.get("agent_addresses", {}))


def _build_delivery(cfg: dict, channel_routes: dict) -> ChannelDelivery:
    t = cfg.get("transport", {})
    if t.get("type") == "nats":
        from vystak_transport_nats.delivery import NatsChannelDelivery
        return NatsChannelDelivery(t["url"])
    from vystak_transport_http.delivery import HttpChannelDelivery
    return HttpChannelDelivery(channel_routes)


def _build_session_store(cfg: dict) -> HeartbeatSessionStore:
    s = cfg.get("session_store", {})
    if s.get("type") == "sqlite":
        return SqliteStore(s["path"])
    return InMemoryStore()


async def _run() -> None:
    logging.basicConfig(level=os.environ.get("VYSTAK_LOG_LEVEL", "INFO").upper())
    cfg_dir = Path(os.environ.get("VYSTAK_CONFIG_DIR", "/etc/vystak"))
    cfg = _load_json(cfg_dir / "service_config.json")
    routes = _load_json(cfg_dir / "routes.json")

    transport = _build_transport(cfg)
    channel_routes = {
        r["delivery"]["channel_canonical_name"]: r["delivery"].get("url", "")
        for r in routes.values() if "delivery" in r
    }
    delivery = _build_delivery(cfg, channel_routes)
    sessions = _build_session_store(cfg)

    schedulers: list[HeartbeatScheduler] = []
    for agent_name, route in routes.items():
        if "heartbeat" not in route:
            continue
        hb = Heartbeat.model_validate(route["heartbeat"])
        if not hb.enabled:
            continue
        schedulers.append(HeartbeatScheduler(
            agent_name=agent_name,
            agent_canonical=route["canonical"],
            channel_canonical=route["delivery"]["channel_canonical_name"],
            heartbeat=hb,
            transport=transport,
            delivery=delivery,
            sessions=sessions,
        ))

    for s in schedulers:
        await s.start()

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            pass
    await stop.wait()
    for s in schedulers:
        await s.stop()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: `plugin.py`**

```python
"""HeartbeatPlugin — codegen for the vystak-heartbeat container."""

from __future__ import annotations

import json
from typing import Any

from vystak.providers.base import GeneratedCode

from vystak_heartbeat.server_template import DOCKERFILE, REQUIREMENTS


def generate_code(
    *,
    agents_with_heartbeat: list[Any],            # list of Agent
    agent_addresses: dict[str, str],              # canonical_name → /a2a URL
    channel_addresses: dict[str, str],            # canonical_name → http://host:port
    transport_cfg: dict,                          # {"type": "http"|"nats", ...}
    session_store_cfg: dict,                      # {"type": "memory"|"sqlite", ...}
) -> GeneratedCode:
    routes: dict[str, dict] = {}
    for agent in agents_with_heartbeat:
        if agent.heartbeat is None:
            continue
        target = agent.heartbeat.target_channel
        routes[agent.name] = {
            "canonical": agent.canonical_name,
            "address": agent_addresses[agent.canonical_name],
            "heartbeat": agent.heartbeat.model_dump(mode="json"),
            "delivery": {
                "channel_canonical_name": target,
                "url": channel_addresses.get(target, ""),
            },
        }

    service_config = {
        "transport": transport_cfg,
        "session_store": session_store_cfg,
        "agent_addresses": agent_addresses,
    }

    return GeneratedCode(
        files={
            "Dockerfile": DOCKERFILE,
            "requirements.txt": REQUIREMENTS,
            "service_config.json": json.dumps(service_config, indent=2),
            "routes.json": json.dumps(routes, indent=2),
        },
        entrypoint="python -m vystak_heartbeat",
    )
```

- [ ] **Step 4: `test_plugin.py`**

```python
"""Codegen tests for the heartbeat plugin."""

import json

from vystak.schema.heartbeat import Heartbeat

from vystak_heartbeat.plugin import generate_code


def _agent(name: str, canonical: str, heartbeat: Heartbeat | None = None):
    from types import SimpleNamespace
    return SimpleNamespace(
        name=name, canonical_name=canonical, heartbeat=heartbeat,
    )


def test_routes_json_includes_heartbeat_and_delivery():
    a = _agent(
        "bot", "bot.agents.dev",
        Heartbeat(schedule="*/30 * * * *", target_channel="x.channels.dev"),
    )
    out = generate_code(
        agents_with_heartbeat=[a],
        agent_addresses={"bot.agents.dev": "http://vystak-bot:8000/a2a"},
        channel_addresses={"x.channels.dev": "http://vystak-channel-x:9999"},
        transport_cfg={"type": "http"},
        session_store_cfg={"type": "memory"},
    )
    routes = json.loads(out.files["routes.json"])
    assert "bot" in routes
    assert routes["bot"]["heartbeat"]["schedule"] == "*/30 * * * *"
    assert routes["bot"]["delivery"]["url"] == "http://vystak-channel-x:9999"


def test_dockerfile_uses_python_module():
    out = generate_code(
        agents_with_heartbeat=[],
        agent_addresses={},
        channel_addresses={},
        transport_cfg={"type": "http"},
        session_store_cfg={"type": "memory"},
    )
    assert "python -m vystak_heartbeat" in out.files["Dockerfile"]
```

- [ ] **Step 5: Verify + commit**

```bash
uv run pytest packages/python/vystak-heartbeat/tests/ -v
just lint-python
git add packages/python/vystak-heartbeat/
git commit -m "feat(vystak-heartbeat): __main__ + plugin + server_template"
```

---

## Task 11 — Step 6a: `ChannelDelivery` ABC + `DeliveryRequest`

**Files:**
- Create: `packages/python/vystak-channel-runtime/src/vystak_channel_runtime/delivery.py`
- Modify: `packages/python/vystak-channel-runtime/src/vystak_channel_runtime/__init__.py` (export)

- [ ] **Step 1: Tests**

Append to `packages/python/vystak-channel-runtime/tests/test_delivery.py` (new file):

```python
"""Tests for DeliveryRequest schema."""

from vystak_channel_runtime.delivery import DeliveryRequest


def test_delivery_request_round_trips():
    r = DeliveryRequest(thread_id="C1", text="hello", metadata={"a": 1})
    restored = DeliveryRequest.model_validate(r.model_dump())
    assert restored == r


def test_delivery_request_metadata_defaults_empty():
    r = DeliveryRequest(thread_id="C1", text="hello")
    assert r.metadata == {}
```

- [ ] **Step 2: Implement**

```python
"""ChannelDelivery interface — heartbeat-service-side push to channels."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, Field


class DeliveryRequest(BaseModel):
    thread_id: str
    text: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChannelDelivery(ABC):
    """Sender-side push to a channel runtime. Used by vystak-heartbeat."""

    @abstractmethod
    async def deliver(
        self,
        channel_canonical_name: str,
        request: DeliveryRequest,
        *,
        timeout: float = 30,
    ) -> None: ...
```

- [ ] **Step 3: Verify + commit**

```bash
uv run pytest packages/python/vystak-channel-runtime/tests/test_delivery.py -v
just lint-python
git add packages/python/vystak-channel-runtime/
git commit -m "feat(channel-runtime): ChannelDelivery ABC + DeliveryRequest"
```

---

## Task 12 — Step 6b: `HttpChannelDelivery` + `NatsChannelDelivery`

**Files:**
- Create: `packages/python/vystak-transport-http/src/vystak_transport_http/delivery.py`
- Create: `packages/python/vystak-transport-http/tests/test_delivery.py`
- Create: `packages/python/vystak-transport-nats/src/vystak_transport_nats/delivery.py`
- Create: `packages/python/vystak-transport-nats/tests/test_delivery.py`

### HTTP

- [ ] **Step 1: Test**

```python
"""HttpChannelDelivery test."""

from unittest.mock import AsyncMock, patch

import pytest

from vystak_channel_runtime.delivery import DeliveryRequest

from vystak_transport_http.delivery import HttpChannelDelivery


@pytest.mark.asyncio
async def test_post_to_channel_url():
    routes = {"x.channels.dev": "http://vystak-channel-x:9999"}
    d = HttpChannelDelivery(routes)
    with patch("httpx.AsyncClient") as ac:
        client = AsyncMock()
        ac.return_value.__aenter__.return_value = client
        client.post = AsyncMock(return_value=AsyncMock(raise_for_status=lambda: None))
        await d.deliver("x.channels.dev", DeliveryRequest(thread_id="t", text="x"))
        client.post.assert_awaited_once()
        url = client.post.call_args.args[0]
        assert url == "http://vystak-channel-x:9999/deliver"
```

- [ ] **Step 2: Implement**

```python
"""HttpChannelDelivery — POST /deliver to the channel's HTTP delivery port."""

from __future__ import annotations

import httpx
from vystak_channel_runtime.delivery import ChannelDelivery, DeliveryRequest


class HttpChannelDelivery(ChannelDelivery):
    def __init__(self, channel_routes: dict[str, str]) -> None:
        # canonical_name → base URL like http://host:9999
        self._routes = dict(channel_routes)

    async def deliver(
        self,
        channel_canonical_name: str,
        request: DeliveryRequest,
        *,
        timeout: float = 30,
    ) -> None:
        url = self._routes[channel_canonical_name].rstrip("/") + "/deliver"
        async with httpx.AsyncClient(timeout=timeout) as c:
            r = await c.post(url, json=request.model_dump(mode="json"))
            r.raise_for_status()
```

### NATS

- [ ] **Step 3: Test**

```python
"""NatsChannelDelivery test."""

from unittest.mock import AsyncMock

import pytest

from vystak_channel_runtime.delivery import DeliveryRequest

from vystak_transport_nats.delivery import NatsChannelDelivery


@pytest.mark.asyncio
async def test_publish_to_canonical_subject(monkeypatch):
    nc = AsyncMock()
    nc.publish = AsyncMock()
    d = NatsChannelDelivery("nats://x:4222")
    monkeypatch.setattr(d, "_connect", AsyncMock(return_value=nc))
    await d.deliver("x.channels.dev", DeliveryRequest(thread_id="t", text="x"))
    args, _ = nc.publish.call_args
    assert args[0] == "vystak.channel.x.channels.dev.deliver"
```

- [ ] **Step 4: Implement**

```python
"""NatsChannelDelivery — publish to vystak.channel.<canonical>.deliver."""

from __future__ import annotations

import nats
from nats.aio.client import Client as NATSClient
from vystak_channel_runtime.delivery import ChannelDelivery, DeliveryRequest


class NatsChannelDelivery(ChannelDelivery):
    SUBJECT_FMT = "vystak.channel.{canonical_name}.deliver"

    def __init__(self, url: str) -> None:
        self._url = url
        self._nc: NATSClient | None = None

    async def _connect(self) -> NATSClient:
        if self._nc is None:
            self._nc = await nats.connect(self._url)
        return self._nc

    async def deliver(
        self,
        channel_canonical_name: str,
        request: DeliveryRequest,
        *,
        timeout: float = 30,
    ) -> None:
        nc = await self._connect()
        await nc.publish(
            self.SUBJECT_FMT.format(canonical_name=channel_canonical_name),
            request.model_dump_json().encode(),
        )
```

- [ ] **Step 5: Verify + commit**

```bash
uv run pytest packages/python/vystak-transport-http/tests/test_delivery.py packages/python/vystak-transport-nats/tests/test_delivery.py -v
just lint-python
git add packages/python/vystak-transport-http/ packages/python/vystak-transport-nats/
git commit -m "feat(transports): HttpChannelDelivery + NatsChannelDelivery impls"
```

---

## Task 13 — Step 6c: Channel-side `_start_delivery_receiver` + abstract `deliver_message`

**Files:**
- Modify: `packages/python/vystak-channel-runtime/src/vystak_channel_runtime/runtime.py`
- Modify: `packages/python/vystak-channel-runtime/tests/test_delivery_receiver.py` (new)

- [ ] **Step 1: Test**

```python
"""Tests for ChannelRuntime delivery receiver."""

import json
from unittest.mock import AsyncMock

import pytest

from vystak_channel_runtime.delivery import DeliveryRequest


@pytest.mark.asyncio
async def test_on_inbound_delivery_dispatches_to_subclass():
    from vystak_channel_runtime.tests.test_runtime import TrivialRuntime, _config
    from vystak_channel_runtime.store import MemoryChannelStore

    rt = TrivialRuntime(
        config=_config(canonical_name="x.channels.dev", transport_type="http"),
        routes={}, store=MemoryChannelStore(),
    )
    rt.deliver_message = AsyncMock()
    body = DeliveryRequest(thread_id="C1", text="hi", metadata={"k": "v"}).model_dump(mode="json")
    await rt._on_inbound_delivery(body)
    rt.deliver_message.assert_awaited_once_with("C1", "hi", {"k": "v"})


@pytest.mark.asyncio
async def test_on_inbound_invalid_body_drops():
    from vystak_channel_runtime.tests.test_runtime import TrivialRuntime, _config
    from vystak_channel_runtime.store import MemoryChannelStore
    rt = TrivialRuntime(
        config=_config(canonical_name="x.channels.dev"), routes={}, store=MemoryChannelStore(),
    )
    rt.deliver_message = AsyncMock()
    await rt._on_inbound_delivery({"bogus": True})
    rt.deliver_message.assert_not_called()
```

- [ ] **Step 2: Add to `runtime.py`**

```python
# Add abstract method:
@abstractmethod
async def deliver_message(
    self,
    thread_id: str,
    text: str,
    metadata: dict[str, Any],
) -> None: ...

# Add helpers:
async def _on_inbound_delivery(self, body: dict) -> None:
    from pydantic import ValidationError
    from vystak_channel_runtime.delivery import DeliveryRequest

    try:
        req = DeliveryRequest.model_validate(body)
    except ValidationError as exc:
        logger.warning("deliver: invalid body: %s", exc)
        return
    try:
        await self.deliver_message(req.thread_id, req.text, req.metadata)
    except Exception:
        logger.exception("deliver_message failed for thread=%s", req.thread_id)

async def _start_delivery_receiver(self) -> None:
    """Mount HTTP /deliver or subscribe to NATS subject based on
    config['transport_type']. Default: HTTP."""
    transport_type = self.config.get("transport_type", "http")
    if transport_type == "http":
        await self._start_http_delivery_receiver()
    elif transport_type == "nats":
        await self._start_nats_delivery_receiver()

async def _stop_delivery_receiver(self) -> None:
    if hasattr(self, "_delivery_server") and self._delivery_server is not None:
        self._delivery_server.should_exit = True
    if hasattr(self, "_delivery_sub") and self._delivery_sub is not None:
        await self._delivery_sub.unsubscribe()

async def _start_http_delivery_receiver(self) -> None:
    import asyncio
    from fastapi import FastAPI
    import uvicorn

    port = int(self.config.get("delivery_port", 9999))
    app = FastAPI()

    @app.post("/deliver")
    async def _deliver(payload: dict):
        await self._on_inbound_delivery(payload)
        return {"ok": True}

    cfg = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="warning")
    self._delivery_server = uvicorn.Server(cfg)
    self._delivery_task = asyncio.create_task(self._delivery_server.serve(),
                                              name=f"delivery-{self.canonical_name}")

async def _start_nats_delivery_receiver(self) -> None:
    import json
    import nats

    url = self.config.get("nats_url") or os.environ.get("VYSTAK_NATS_URL")
    if not url:
        raise RuntimeError("nats transport requested but no nats_url configured")
    self._delivery_nc = await nats.connect(url)
    subject = f"vystak.channel.{self.canonical_name}.deliver"

    async def _cb(msg):
        try:
            await self._on_inbound_delivery(json.loads(msg.data.decode()))
        except Exception:
            logger.exception("delivery message handler failed")

    self._delivery_sub = await self._delivery_nc.subscribe(subject, cb=_cb)
```

- [ ] **Step 3: Verify + commit**

```bash
uv run pytest packages/python/vystak-channel-runtime/tests/test_delivery_receiver.py -v
just lint-python
git add packages/python/vystak-channel-runtime/
git commit -m "feat(channel-runtime): _start_delivery_receiver + abstract deliver_message"
```

---

## Task 14 — Step 6d: Per-channel `deliver_message` impls + lifecycle wiring

**Files:**
- Modify: `packages/python/vystak-channel-slack/src/vystak_channel_slack/runtime.py`
- Modify: `packages/python/vystak-channel-discord/src/vystak_channel_discord/runtime.py`
- Modify: `packages/python/vystak-channel-chat/src/vystak_channel_chat/runtime.py`
- Modify: each channel's `tests/test_runtime.py`
- Modify: each channel's `server_template.py` (Dockerfile `EXPOSE 9999` for HTTP)

- [ ] **Step 1: Slack `deliver_message`**

In `SlackChannelRuntime`:

```python
async def deliver_message(self, thread_id: str, text: str, metadata: dict) -> None:
    if self._app is None:
        logger.warning("slack delivery: app not initialized")
        return
    await self._app.client.chat_postMessage(channel=thread_id, text=text)
```

In `start()`, after the existing socket handler is up: `await self._start_delivery_receiver()`.
In `stop()`, before socket close: `await self._stop_delivery_receiver()`.

- [ ] **Step 2: Discord `deliver_message`**

```python
async def deliver_message(self, thread_id: str, text: str, metadata: dict) -> None:
    if self._client is None:
        logger.warning("discord delivery: client not initialized")
        return
    channel = self._client.get_channel(int(thread_id))
    if channel is None:
        channel = await self._client.fetch_channel(int(thread_id))
    for chunk in _chunk(text or "", MAX_DISCORD_MESSAGE_CHARS):
        await channel.send(chunk)
```

Same `_start_delivery_receiver` / `_stop_delivery_receiver` lifecycle calls.

- [ ] **Step 3: Chat `deliver_message`**

The chat channel already runs FastAPI/uvicorn. Mount `/deliver` directly into the existing app rather than spawning a sidecar:

```python
# Override _start_delivery_receiver to register on the existing app.
async def _start_delivery_receiver(self) -> None:
    @self._app.post("/deliver")
    async def _deliver(payload: dict):
        await self._on_inbound_delivery(payload)
        return {"ok": True}

async def _stop_delivery_receiver(self) -> None:
    return None  # Route lives until app shuts down

async def deliver_message(self, thread_id: str, text: str, metadata: dict) -> None:
    await self._broadcast(thread_id, text, metadata)
```

- [ ] **Step 4: Update each `server_template.py`**

For Slack and Discord: in `DOCKERFILE`, add `EXPOSE 9999` after the existing `EXPOSE` line. For chat, no change (uses existing port).

- [ ] **Step 5: Tests for each channel**

Per channel: one test asserting `deliver_message` calls the native API. Mock the underlying client. Example for Slack (already in v2 test suite — keep it).

- [ ] **Step 6: Verify + commit**

```bash
just lint-python
uv run pytest packages/python/vystak-channel-{slack,discord,chat}/tests/ -v
git add packages/python/vystak-channel-{slack,discord,chat}/
git commit -m "feat(channels): deliver_message impls + delivery receiver lifecycle"
```

---

## Task 15 — Step 7a: Docker provider auto-spawn `DockerHeartbeatNode`

**Files:**
- Create: `packages/python/vystak-provider-docker/src/vystak_provider_docker/nodes/heartbeat.py`
- Modify: `packages/python/vystak-provider-docker/src/vystak_provider_docker/provider.py`
- Modify: `packages/python/vystak-provider-docker/tests/test_nodes.py`

- [ ] **Step 1: `DockerHeartbeatNode`**

Mirror `OtelLgtmNode`'s shape. Builds the heartbeat container's image from emitted Dockerfile + sources, runs it on `vystak-net`, depends on agent containers + channel containers.

```python
"""DockerHeartbeatNode — runs the vystak-heartbeat container."""

from __future__ import annotations

from pathlib import Path

from vystak.provisioning.health import NoopHealthCheck
from vystak.provisioning.node import Provisionable, ProvisionResult


class DockerHeartbeatNode(Provisionable):
    CONTAINER_NAME = "vystak-heartbeat"
    IMAGE_NAME = "vystak-heartbeat"

    def __init__(self, client, generated_code, build_dir: Path,
                 depends: list[str]) -> None:
        self._client = client
        self._generated = generated_code
        self._build_dir = build_dir
        self._depends = depends

    @property
    def name(self) -> str:
        return "heartbeat"

    @property
    def depends_on(self) -> list[str]:
        return ["network", *self._depends]

    def provision(self, context: dict) -> ProvisionResult:
        # Materialize generated files to build_dir, copy package source
        # alongside, build image, run on vystak-net.
        # (Standard pattern, mirror DockerChannelNode.)
        ...
```

(Implementation parallels `DockerChannelNode` — copying the package source, materializing generated files, building, running. ~120 lines, mechanical.)

- [ ] **Step 2: Wire into provider**

In `vystak_provider_docker.provider.DockerProvider.apply()`, after channel application:

```python
agents_with_heartbeat = [a for a in resolved_agents if getattr(a, "heartbeat", None)]
if agents_with_heartbeat:
    from vystak_heartbeat.plugin import generate_code as hb_generate
    code = hb_generate(
        agents_with_heartbeat=agents_with_heartbeat,
        agent_addresses={a.canonical_name: f"http://vystak-{a.name}-agent:8000/a2a"
                         for a in agents_with_heartbeat},
        channel_addresses={c.canonical_name: f"http://vystak-channel-{c.name}:9999"
                           for c in resolved_channels},
        transport_cfg={"type": platform.transport.type if platform.transport else "http"},
        session_store_cfg={"type": "sqlite", "path": "/data/heartbeat.db"},
    )
    graph.add(DockerHeartbeatNode(self._client, code, build_dir, depends=[
        f"agent:{a.name}" for a in agents_with_heartbeat
    ] + [f"channel:{c.name}" for c in resolved_channels]))
```

- [ ] **Step 3: Test the wiring**

Add a unit test asserting that when the agent set has a heartbeat config, the provision graph contains a `DockerHeartbeatNode`. Mock the Docker client so no actual containers spin up.

- [ ] **Step 4: Verify + commit**

```bash
just lint-python
uv run pytest packages/python/vystak-provider-docker/tests/ -q
git add packages/python/vystak-provider-docker/
git commit -m "feat(provider-docker): auto-spawn vystak-heartbeat when any agent has heartbeat"
```

---

## Task 16 — Step 7b: Channel plugin emits `delivery_port`

**Files:**
- Modify: `packages/python/vystak-channel-{slack,discord,chat}/src/.../plugin.py` (channel_config injection)
- Modify: each `server_template.py` (Dockerfile `EXPOSE 9999`)
- Modify: each plugin's `test_plugin.py`

- [ ] **Step 1: Plugin update**

For each of Slack / Discord / Chat plugins, inside `_build_channel_config` (Slack) or its equivalent dict construction (Discord/Chat), add:

```python
"delivery_port": int(channel.config.get("delivery_port", 9999)),
"transport_type": platform.transport.type if platform.transport else "http",
```

For now, accept that `platform` is reachable in `generate_code(channel, resolved_routes)` — extend the signature if needed (`def generate_code(self, channel, resolved_routes, platform)`). Update all call sites. (This is one extra param — not a churn.)

- [ ] **Step 2: Dockerfile EXPOSE**

```python
DOCKERFILE = """\
... existing ...
EXPOSE 9999
... existing ...
"""
```

- [ ] **Step 3: Plugin tests**

Add one test per channel asserting `channel_config["delivery_port"] == 9999` by default and the configured value when overridden.

- [ ] **Step 4: Provider wiring update**

In `vystak-provider-docker`, the `DockerChannelNode` already publishes the channel's primary port; it now also exposes 9999 internally. No host port mapping (heartbeat reaches it on the docker network only).

- [ ] **Step 5: Verify + commit**

```bash
just lint-python
uv run pytest packages/python/vystak-channel-{slack,discord,chat}/tests/ -v
git add packages/python/vystak-channel-{slack,discord,chat}/ packages/python/vystak-provider-docker/
git commit -m "feat(channels): emit delivery_port + transport_type in channel_config"
```

---

## Task 17 — Step 8: Remove channel-hosted heartbeat scaffolding

**Files:**
- Modify: `packages/python/vystak-channel-runtime/src/vystak_channel_runtime/runtime.py`
- Modify: `packages/python/vystak-channel-runtime/src/vystak_channel_runtime/heartbeat.py`
- Modify: `packages/python/vystak-channel-{slack,discord,chat}/src/.../runtime.py`
- Modify: `packages/python/vystak-channel-{slack,discord,chat}/src/.../plugin.py`
- Delete: `packages/python/vystak-provider-docker/tests/release/test_heartbeat.py` (replaced in Task 18)

- [ ] **Step 1: Remove from `runtime.py` (base)**

Delete:
- `self._heartbeats: list[HeartbeatScheduler] = []` from `__init__`
- `_heartbeat_for_route` helper
- `_start_heartbeats` method
- `_stop_heartbeats` method
- `_handle_synthetic_event` method
- The import `from vystak_channel_runtime.heartbeat import HeartbeatScheduler` and `enrich_routes_with_heartbeat`
- `from vystak.schema.heartbeat import Heartbeat` if no longer needed

Keep the import `is_heartbeat_ok` only if any base method still uses it (it shouldn't after this task).

- [ ] **Step 2: Trim `heartbeat.py`**

Delete `HeartbeatScheduler` and `enrich_routes_with_heartbeat`. Keep `is_heartbeat_ok`, `HEARTBEAT_OK`, `DEFAULT_PROMPT` — these still serve as constants the new heartbeat service imports.

- [ ] **Step 3: Remove from each concrete channel**

In Slack, Discord, Chat `runtime.py`:
- Delete the `_start_heartbeats()` / `_stop_heartbeats()` calls in `start()` / `stop()`.
- Delete the `post_reply` heartbeat branch (`if event.metadata.get("heartbeat")` block).

In each `plugin.py`:
- Delete the `enrich_routes_with_heartbeat(channel, resolved_routes)` call. Use `resolved_routes` directly.

- [ ] **Step 4: Delete the v1 release test**

```bash
git rm packages/python/vystak-provider-docker/tests/release/test_heartbeat.py
```

- [ ] **Step 5: Verify**

```bash
just lint-python
uv run pytest packages/python/ -q
```

Expected: green. Any red here means a removed-name reference still exists somewhere.

- [ ] **Step 6: Commit**

```bash
git add packages/python/
git commit -m "refactor(channels): remove channel-hosted heartbeat scaffolding"
```

---

## Task 18 — Final: New release integration cell

**Files:**
- Create: `packages/python/vystak-provider-docker/tests/release/test_heartbeat_v2.py`

- [ ] **Step 1: Write the test**

```python
"""Release integration cell — heartbeat v2: separate service + delivery."""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

import pytest

from .conftest import assert_apply_ok, docker_running

pytestmark = [pytest.mark.release_integration, pytest.mark.docker]


YAML = """\
providers:
  docker: {type: docker}
  anthropic: {type: anthropic}
platforms:
  local: {type: docker, provider: docker, namespace: dev}
models:
  alpha:
    provider: anthropic
    model_name: claude-haiku-4-5-20251001
  beta:
    provider: anthropic
    model_name: claude-sonnet-4-5-20250929
agents:
  - name: hbagent
    framework: langchain-python
    instructions: "Reply with the literal string OK."
    default_model: alpha
    models: [beta]
    platform: local
    secrets:
      - {name: ANTHROPIC_API_KEY}
    sessions:
      type: sqlite
      path: /data/sessions.db
    heartbeat:
      schedule: "* * * * *"
      target_channel: hbchat.channels.dev
      target_thread: hb-test-thread
      isolated_session: false
      model: beta
      prompt: "ping"
      ack_max_chars: 0
channels:
  - name: hbchat
    type: chat
    platform: local
    agents: [hbagent]
    default_agent: hbagent
"""


def _logs(name: str) -> str:
    r = subprocess.run(["docker", "logs", name], capture_output=True, text=True, check=False)
    return (r.stdout or "") + (r.stderr or "")


def _wait_for(name: str, needle: str, t: int) -> bool:
    deadline = time.time() + t
    while time.time() < deadline:
        if needle in _logs(name): return True
        time.sleep(2)
    return False


def test_heartbeat_v2_full_cycle(project: Path):
    (project / "vystak.yaml").write_text(YAML)
    assert_apply_ok(cwd=project)

    assert docker_running("vystak-heartbeat"), "vystak-heartbeat not running"
    assert docker_running("vystak-channel-hbchat"), "channel container not running"

    # 1) heartbeat fires + transports to agent
    assert _wait_for("vystak-heartbeat", "heartbeat.fired agent=hbagent", 90), \
        "heartbeat.fired never appeared:\n" + _logs("vystak-heartbeat")[-2000:]

    # 2) delivery lands on the channel
    assert _wait_for("vystak-channel-hbchat", "deliver_message", 60), \
        "deliver_message never appeared on channel:\n" + _logs("vystak-channel-hbchat")[-2000:]

    # 3) Second fire uses the SAME model as the first.
    #    Agent's heartbeat_session_models row should hold "beta" after fire 1.
    #    Heartbeat service's session_store should also record "beta".
    time.sleep(70)  # let a second fire land
    hb_logs = _logs("vystak-heartbeat")
    assert hb_logs.count("heartbeat.fired") >= 2, "second fire never landed"
    # The reply.metadata.model_resolved should be "beta" both times.
    # (We assert via the session DB rather than parsing logs — log shape varies.)
    sql = subprocess.run(
        ["docker", "exec", "vystak-heartbeat",
         "sqlite3", "/data/heartbeat.db",
         "SELECT model_name FROM heartbeat_session_models"],
        capture_output=True, text=True, check=True,
    )
    assert "beta" in sql.stdout, f"expected stored model 'beta', got {sql.stdout!r}"
```

- [ ] **Step 2: Run locally if Docker + ANTHROPIC_API_KEY available**

```bash
export ANTHROPIC_API_KEY=sk-ant-api03-...
uv run pytest packages/python/vystak-provider-docker/tests/release/test_heartbeat_v2.py -v -m release_integration
```

Expected: PASS in ~3 min (one apply, ~2 fires, one destroy).

- [ ] **Step 3: Commit**

```bash
git add packages/python/vystak-provider-docker/tests/release/test_heartbeat_v2.py
git commit -m "test(release): heartbeat v2 service + multi-model session pin"
```

---

## Task 19 — Final: Spec coverage walk

After all 18 tasks land, verify the spec `docs/superpowers/specs/2026-05-10-heartbeat-service-design.md` is fully satisfied:

| Spec section | Tasks |
|---|---|
| Schema rename + `Agent.models` | Task 1 |
| `Heartbeat.model` field | Task 2 |
| Plan-time validation | Task 6 |
| Multi-model dispatcher | Task 3 |
| A2A handler model selection + persistence | Task 4 |
| Sidecar `heartbeat_session_models` table | Task 5 |
| `vystak-heartbeat` package | Tasks 7, 8, 9, 10 |
| `ChannelDelivery` ABC + impls | Tasks 11, 12 |
| `_start_delivery_receiver` + `deliver_message` | Tasks 13, 14 |
| Provider auto-spawn | Task 15 |
| Channel `delivery_port` codegen | Task 16 |
| Removed v1 scaffolding | Task 17 |
| Integration test | Task 18 |
| Hash propagation | Task 1 (already covered) |
| Tests — unit (5 layers per spec) | Tasks 3-14 inline tests |

Open PR titled `feat: heartbeat service v2 — separate scheduler with transport-based delivery`.

---

## Self-review notes

Performed against the spec on first pass:

- **Spec coverage:** every spec section traced to a task above (see Task 19 mapping table).
- **Placeholder scan:** Task 15 step 1 (`DockerHeartbeatNode` body) and Task 16 step 1 (channel plugin updates) leave some implementation marked `...` to keep the plan a reasonable length. The implementer should mirror the existing `DockerChannelNode` pattern for these — both are mechanical adaptations of an existing template, not novel design. This is the only deferred mechanical detail.
- **Type consistency:** `HeartbeatSessions` (langchain template, Task 5) and `HeartbeatSessionStore` (heartbeat service, Tasks 8/9) intentionally differ — different packages, parallel implementations of the same contract. The DDL (`heartbeat_session_models`) is identical so future consolidation is mechanical. Method names (`get_model`, `set_model`) match across both. `DeliveryRequest.thread_id` is consistently the platform-native id throughout (not a Vystak thread binding).
- **Ambiguity:** `delivery_port` defaults to 9999 everywhere; explicit `channel.config.delivery_port` overrides. The base `_start_delivery_receiver` reads `config["transport_type"]`, which the plugin codegen now injects. No two interpretations.
