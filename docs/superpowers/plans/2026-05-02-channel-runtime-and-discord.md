# Channel Runtime + Discord Channel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract a shared `vystak-channel-runtime` library that defines the runtime shape for every channel container, retrofit Slack and Chat onto it without behavior change, add Discord as the first native consumer, and pivot channel packages off Python source codegen toward pip-installable libraries.

**Architecture:** New `vystak-channel-runtime` package owns the message lifecycle (parse → authorize → resolve route → fetch history → call agent → post reply → persist) as a template-method ABC. Channel packages become real importable libraries with `__main__.py` entrypoints; their plugins emit only JSON config + a generic Dockerfile. Slack and Chat retrofit behavior-preservingly; Discord ships fresh on the new base.

**Tech Stack:** Python 3.11+, `uv` workspace, `pydantic`, `httpx`, `aiosqlite`, `asyncpg`, `slack-bolt` (Slack), `fastapi` (Chat), `discord.py` (Discord). Tests: `pytest`, `pytest-asyncio`. Lint: `ruff`. Type-check: `pyright`.

**Spec:** `docs/superpowers/specs/2026-05-02-channel-runtime-and-discord-design.md`

---

## File Structure

### New files

**`packages/python/vystak-channel-runtime/`** (new package):
- `pyproject.toml` — package metadata, deps on `vystak`, `httpx`, `aiosqlite`, `asyncpg`.
- `src/vystak_channel_runtime/__init__.py` — public re-exports.
- `src/vystak_channel_runtime/types.py` — `InboundEvent`, `AgentReply`, `AgentChunk`, `Message`, `ThreadBinding`, `SkipEvent`, `AgentCallError`.
- `src/vystak_channel_runtime/agent_client.py` — `AgentClient` Protocol + `A2AAgentClient`.
- `src/vystak_channel_runtime/store.py` — `ChannelStore` Protocol + `MemoryChannelStore` + `SqliteChannelStore` + `PostgresChannelStore` + `make_channel_store`.
- `src/vystak_channel_runtime/runtime.py` — `ChannelRuntime` ABC.
- `src/vystak_channel_runtime/launcher.py` — `launch()` helper.
- `src/vystak_channel_runtime/test_endpoint.py` — `/test/event` synthetic dispatch (gated by env var).
- `tests/conftest.py` — shared fixtures.
- `tests/test_types.py`, `tests/test_agent_client.py`, `tests/test_store.py`, `tests/test_runtime.py`, `tests/test_launcher.py`.

**`packages/python/vystak-channel-discord/`** (new package):
- `pyproject.toml`.
- `src/vystak_channel_discord/__init__.py`.
- `src/vystak_channel_discord/__main__.py` — entrypoint.
- `src/vystak_channel_discord/plugin.py` — `DiscordChannelPlugin` (build-time codegen).
- `src/vystak_channel_discord/runtime.py` — `DiscordChannelRuntime`.
- `src/vystak_channel_discord/server_template.py` — `DOCKERFILE` + `REQUIREMENTS` (no `SERVER_PY`).
- `src/vystak_channel_discord/commands.py` — `/vystak` slash command handlers.
- `src/vystak_channel_discord/welcome.py` — bot-join welcome + auto-bind.
- `src/vystak_channel_discord/threads.py` — Discord thread + forum logic.
- `tests/test_plugin.py`, `tests/test_runtime.py`, `tests/test_commands.py`, `tests/test_welcome.py`, `tests/test_threads.py`.
- `tests/release/test_D9_discord_default_chat_http.py`, `test_D10_discord_dm_chat_http.py`, `test_D11_discord_threads.py`, `test_D12_discord_postgres.py`.

### Modified files

- `packages/python/vystak/src/vystak/schema/common.py` — add `ChannelType.DISCORD`.
- `packages/python/vystak/src/vystak/hash/tree.py` — add `channel_package_version` + `channel_runtime_version`.
- `packages/python/vystak-channel-slack/pyproject.toml` — add `vystak-channel-runtime` dep.
- `packages/python/vystak-channel-slack/src/vystak_channel_slack/__main__.py` — new entrypoint.
- `packages/python/vystak-channel-slack/src/vystak_channel_slack/runtime.py` — new, subclasses `ChannelRuntime`.
- `packages/python/vystak-channel-slack/src/vystak_channel_slack/server_template.py` — `SERVER_PY` deleted; `DOCKERFILE` + `REQUIREMENTS` only.
- `packages/python/vystak-channel-slack/src/vystak_channel_slack/plugin.py` — `generate_code()` emits only JSON + Dockerfile.
- `packages/python/vystak-channel-slack/src/vystak_channel_slack/resolver.py` — DELETED (logic moves into `ChannelRuntime.resolve_route`).
- `packages/python/vystak-channel-slack/src/vystak_channel_slack/store.py` — DELETED (replaced by `vystak_channel_runtime.store`); Slack-specific `inviter` tracking moves to a thin `inviters.py` helper backed by a small Slack-only table.
- `packages/python/vystak-channel-slack/src/vystak_channel_slack/inviters.py` — new, ~30 lines.
- `packages/python/vystak-channel-slack/tests/test_resolver.py` — re-pointed at runtime lib.
- `packages/python/vystak-channel-slack/tests/test_store.py` — re-pointed at runtime lib + Slack-only inviter helper.
- `packages/python/vystak-channel-chat/pyproject.toml` — add `vystak-channel-runtime` dep.
- `packages/python/vystak-channel-chat/src/vystak_channel_chat/__main__.py` — new entrypoint.
- `packages/python/vystak-channel-chat/src/vystak_channel_chat/runtime.py` — new, subclasses `ChannelRuntime`.
- `packages/python/vystak-channel-chat/src/vystak_channel_chat/server_template.py` — `SERVER_PY` deleted.
- `packages/python/vystak-channel-chat/src/vystak_channel_chat/plugin.py` — emits configs + Dockerfile only.
- `pyproject.toml` (root) — add `vystak-channel-runtime` and `vystak-channel-discord` to workspace members.
- `Justfile` — no change required (workspace globs cover new packages).
- `website/docs/channels/discord.md` — new docs page.
- `website/docs/channels/internals.md` — new docs page (`ChannelRuntime` developer reference).
- `CHANGELOG.md` (or root `CHANGES.md`) — entry for breaking changes (Slack thread-binding reset + entrypoint change).

---

## Phase 0: Schema prep

### Task 0.1: Add `ChannelType.DISCORD` enum value

**Files:**
- Modify: `packages/python/vystak/src/vystak/schema/common.py:20-27`
- Test: `packages/python/vystak/tests/test_schema_common.py` (create if absent)

- [ ] **Step 1: Write the failing test**

Create `packages/python/vystak/tests/test_schema_common.py` (if it does not exist) and add:

```python
from vystak.schema.common import ChannelType


def test_channel_type_includes_discord():
    assert ChannelType.DISCORD == "discord"
    assert ChannelType("discord") is ChannelType.DISCORD
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/python/vystak/tests/test_schema_common.py::test_channel_type_includes_discord -v`
Expected: FAIL with `AttributeError: DISCORD` or similar.

- [ ] **Step 3: Add the enum value**

Edit `packages/python/vystak/src/vystak/schema/common.py`, locate `class ChannelType` (around line 20) and add `DISCORD = "discord"` between `SLACK` and `WEBHOOK`:

```python
class ChannelType(StrEnum):
    API = "api"
    SLACK = "slack"
    DISCORD = "discord"
    WEBHOOK = "webhook"
    VOICE = "voice"
    CRON = "cron"
    WIDGET = "widget"
    CHAT = "chat"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest packages/python/vystak/tests/test_schema_common.py::test_channel_type_includes_discord -v`
Expected: PASS.

- [ ] **Step 5: Lint + typecheck**

Run: `just lint-python && just typecheck-python` (note: typecheck has known pre-existing failures per CLAUDE.md; ignore unrelated errors).
Expected: no NEW errors in `common.py`.

- [ ] **Step 6: Commit**

```bash
git add packages/python/vystak/src/vystak/schema/common.py packages/python/vystak/tests/test_schema_common.py
git commit -m "feat(schema): add ChannelType.DISCORD enum value"
```

---

## Phase 1: `vystak-channel-runtime` package

### Task 1.1: Create package skeleton

**Files:**
- Create: `packages/python/vystak-channel-runtime/pyproject.toml`
- Create: `packages/python/vystak-channel-runtime/README.md`
- Create: `packages/python/vystak-channel-runtime/src/vystak_channel_runtime/__init__.py`
- Create: `packages/python/vystak-channel-runtime/tests/__init__.py`
- Create: `packages/python/vystak-channel-runtime/tests/conftest.py`
- Modify: `pyproject.toml` (root) — add to workspace members.

- [ ] **Step 1: Create directory structure**

```bash
mkdir -p packages/python/vystak-channel-runtime/src/vystak_channel_runtime
mkdir -p packages/python/vystak-channel-runtime/tests
```

- [ ] **Step 2: Write `pyproject.toml`**

Create `packages/python/vystak-channel-runtime/pyproject.toml`:

```toml
[project]
name = "vystak-channel-runtime"
dynamic = ["version"]
description = "Vystak channel runtime — shared base for all channel containers"
readme = "README.md"
requires-python = ">=3.11"
license = "Apache-2.0"
authors = [
    { name = "Anatoliy Kolodkin", email = "11351966+akolodkin@users.noreply.github.com" },
]
keywords = ["vystak", "channel", "runtime", "agent"]
classifiers = [
    "Development Status :: 3 - Alpha",
    "Intended Audience :: Developers",
    "License :: OSI Approved :: Apache Software License",
    "Operating System :: OS Independent",
    "Programming Language :: Python :: 3",
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
    "Programming Language :: Python :: 3.13",
    "Topic :: Software Development :: Libraries :: Python Modules",
]
dependencies = [
    "vystak>=0.1.0",
    "httpx>=0.27",
    "aiosqlite>=0.20",
    "asyncpg>=0.29",
    "pydantic>=2.7",
]

[project.urls]
Homepage = "https://vystak.dev"
Repository = "https://github.com/vystak/vystak"

[build-system]
requires = ["hatchling", "hatch-vcs"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/vystak_channel_runtime"]

[tool.hatch.version]
source = "vcs"

[tool.uv.sources]
vystak = { workspace = true }

[tool.pytest.ini_options]
asyncio_mode = "auto"
```

- [ ] **Step 3: Write minimal `README.md`**

Create `packages/python/vystak-channel-runtime/README.md`:

```markdown
# vystak-channel-runtime

Shared runtime base for Vystak channel containers. Defines `ChannelRuntime`
(template-method message lifecycle), `AgentClient` (A2A default impl),
and `ChannelStore` (SQLite + Postgres + in-memory).

Imported by `vystak-channel-slack`, `vystak-channel-chat`,
`vystak-channel-discord` inside their generated containers.
```

- [ ] **Step 4: Write empty package `__init__.py`**

Create `packages/python/vystak-channel-runtime/src/vystak_channel_runtime/__init__.py`:

```python
"""Vystak channel runtime — shared base for channel containers."""
```

- [ ] **Step 5: Write empty test `__init__.py` and minimal `conftest.py`**

Create `packages/python/vystak-channel-runtime/tests/__init__.py` (empty file).

Create `packages/python/vystak-channel-runtime/tests/conftest.py`:

```python
"""Shared test fixtures for vystak-channel-runtime."""

import pytest


@pytest.fixture
def anyio_backend():
    return "asyncio"
```

- [ ] **Step 6: Add to workspace**

Read root `pyproject.toml` and locate `[tool.uv.workspace]` (or equivalent). Append `"packages/python/vystak-channel-runtime"` to the `members` list:

```bash
# Inspect first
grep -A 10 "workspace" pyproject.toml
```

If `members = [...]` is a glob like `"packages/python/*"`, no change is required. Otherwise add the explicit path.

- [ ] **Step 7: Sync the workspace**

Run: `uv sync`
Expected: package builds, no errors.

- [ ] **Step 8: Smoke import**

Run: `uv run python -c "import vystak_channel_runtime; print('ok')"`
Expected: prints `ok`.

- [ ] **Step 9: Commit**

```bash
git add packages/python/vystak-channel-runtime pyproject.toml
git commit -m "feat(channel-runtime): scaffold vystak-channel-runtime package"
```

---

### Task 1.2: Write `types` module — core data classes

**Files:**
- Create: `packages/python/vystak-channel-runtime/src/vystak_channel_runtime/types.py`
- Create: `packages/python/vystak-channel-runtime/tests/test_types.py`

- [ ] **Step 1: Write the failing test**

Create `packages/python/vystak-channel-runtime/tests/test_types.py`:

```python
"""Tests for vystak_channel_runtime.types."""

import pytest
from vystak.schema.common import ChannelType
from vystak_channel_runtime.types import (
    AgentCallError,
    AgentChunk,
    AgentReply,
    InboundEvent,
    Message,
    SkipEvent,
    ThreadBinding,
)


def test_inbound_event_round_trip():
    ev = InboundEvent(
        channel_type=ChannelType.SLACK,
        scope_id="T1",
        thread_id="C1:123.45",
        user_id="U1",
        text="hi",
        is_dm=False,
        mentions_bot=True,
        metadata={"channel_name": "general"},
        raw=None,
    )
    dumped = ev.model_dump()
    re = InboundEvent(**dumped)
    assert re.channel_type == ChannelType.SLACK
    assert re.scope_id == "T1"
    assert re.metadata == {"channel_name": "general"}


def test_agent_reply_minimum():
    r = AgentReply(text="hello")
    assert r.text == "hello"
    assert r.tool_calls == []
    assert r.finish_reason is None


def test_agent_chunk_minimum():
    c = AgentChunk(delta="hi")
    assert c.delta == "hi"


def test_message_shape():
    m = Message(role="user", content="hi")
    assert m.role == "user"
    assert m.content == "hi"


def test_thread_binding_shape():
    b = ThreadBinding(
        channel_type="slack",
        scope_id="T1",
        thread_id="C1:123.45",
        agent_name="hero",
    )
    assert b.agent_name == "hero"
    assert b.user_id is None


def test_skip_event_is_exception():
    with pytest.raises(SkipEvent):
        raise SkipEvent("ignored")


def test_agent_call_error_is_exception():
    with pytest.raises(AgentCallError):
        raise AgentCallError("agent down")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/python/vystak-channel-runtime/tests/test_types.py -v`
Expected: collection error / ImportError on `vystak_channel_runtime.types`.

- [ ] **Step 3: Implement `types.py`**

Create `packages/python/vystak-channel-runtime/src/vystak_channel_runtime/types.py`:

```python
"""Core types shared across the channel runtime."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from vystak.schema.common import ChannelType


class Message(BaseModel):
    """A single turn in conversation history (matches A2A history shape)."""

    role: Literal["user", "assistant", "system", "tool"]
    content: str
    name: str | None = None


class AgentReply(BaseModel):
    """Result of a non-streaming agent turn."""

    text: str
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    finish_reason: str | None = None
    raw: dict[str, Any] | None = None


class AgentChunk(BaseModel):
    """One streaming delta from an agent."""

    delta: str
    tool_call_delta: dict[str, Any] | None = None
    finish_reason: str | None = None
    raw: dict[str, Any] | None = None


class InboundEvent(BaseModel):
    """A platform-agnostic event entering the channel runtime."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    channel_type: ChannelType
    scope_id: str
    thread_id: str | None
    user_id: str
    text: str
    is_dm: bool
    mentions_bot: bool
    metadata: dict[str, Any] = Field(default_factory=dict)
    raw: Any = None


class ThreadBinding(BaseModel):
    """A persisted binding between a thread and an agent."""

    channel_type: str
    scope_id: str
    thread_id: str
    agent_name: str
    user_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class SkipEvent(Exception):
    """Raised by parse_event() to silently drop an event from the pipeline."""


class AgentCallError(Exception):
    """Raised by call_agent() when the agent call fails after retries."""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest packages/python/vystak-channel-runtime/tests/test_types.py -v`
Expected: 7 PASSED.

- [ ] **Step 5: Re-export from package `__init__.py`**

Edit `packages/python/vystak-channel-runtime/src/vystak_channel_runtime/__init__.py`:

```python
"""Vystak channel runtime — shared base for channel containers."""

from vystak_channel_runtime.types import (
    AgentCallError,
    AgentChunk,
    AgentReply,
    InboundEvent,
    Message,
    SkipEvent,
    ThreadBinding,
)

__all__ = [
    "AgentCallError",
    "AgentChunk",
    "AgentReply",
    "InboundEvent",
    "Message",
    "SkipEvent",
    "ThreadBinding",
]
```

- [ ] **Step 6: Lint**

Run: `uv run ruff check packages/python/vystak-channel-runtime/`
Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add packages/python/vystak-channel-runtime/
git commit -m "feat(channel-runtime): add types module (InboundEvent, AgentReply, AgentChunk, Message, ThreadBinding)"
```

---

### Task 1.3: `AgentClient` Protocol + `A2AAgentClient.send_turn`

**Files:**
- Create: `packages/python/vystak-channel-runtime/src/vystak_channel_runtime/agent_client.py`
- Create: `packages/python/vystak-channel-runtime/tests/test_agent_client.py`

- [ ] **Step 1: Write the failing test (Protocol shape + send_turn happy path)**

Create `packages/python/vystak-channel-runtime/tests/test_agent_client.py`:

```python
"""Tests for vystak_channel_runtime.agent_client."""

import json
import pytest
import httpx
from vystak_channel_runtime.agent_client import A2AAgentClient, AgentClient
from vystak_channel_runtime.types import AgentCallError


@pytest.mark.asyncio
async def test_a2a_agent_client_implements_protocol():
    client = A2AAgentClient()
    assert isinstance(client, AgentClient)


@pytest.mark.asyncio
async def test_send_turn_returns_text(monkeypatch):
    captured = {}

    async def fake_post(self, url, *, json, timeout):
        captured["url"] = url
        captured["json"] = json
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": json["id"],
                "result": {"messages": [{"role": "assistant", "content": "pong"}]},
            },
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    client = A2AAgentClient()
    reply = await client.send_turn(
        "http://hero:8000",
        text="ping",
        thread_id="t1",
    )
    assert reply.text == "pong"
    assert captured["url"] == "http://hero:8000/a2a"
    assert captured["json"]["method"] == "tasks/send"


@pytest.mark.asyncio
async def test_send_turn_retries_then_fails(monkeypatch):
    calls = {"n": 0}

    async def flaky_post(self, url, *, json, timeout):
        calls["n"] += 1
        return httpx.Response(503, text="upstream down")

    monkeypatch.setattr(httpx.AsyncClient, "post", flaky_post)
    client = A2AAgentClient(max_retries=3, base_backoff=0.01)
    with pytest.raises(AgentCallError):
        await client.send_turn("http://hero:8000", text="ping", thread_id="t1")
    assert calls["n"] == 3


@pytest.mark.asyncio
async def test_send_turn_succeeds_after_retry(monkeypatch):
    calls = {"n": 0}

    async def flaky_post(self, url, *, json, timeout):
        calls["n"] += 1
        if calls["n"] < 2:
            return httpx.Response(503, text="upstream down")
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": json["id"],
                "result": {"messages": [{"role": "assistant", "content": "ok"}]},
            },
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", flaky_post)
    client = A2AAgentClient(max_retries=3, base_backoff=0.01)
    reply = await client.send_turn("http://hero:8000", text="ping", thread_id="t1")
    assert reply.text == "ok"
    assert calls["n"] == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/python/vystak-channel-runtime/tests/test_agent_client.py -v`
Expected: ImportError on `vystak_channel_runtime.agent_client`.

- [ ] **Step 3: Implement `agent_client.py`**

Create `packages/python/vystak-channel-runtime/src/vystak_channel_runtime/agent_client.py`:

```python
"""Pluggable agent client port + A2A default impl."""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import AsyncIterator
from typing import Any, Protocol, runtime_checkable

import httpx

from vystak_channel_runtime.types import (
    AgentCallError,
    AgentChunk,
    AgentReply,
    Message,
)

logger = logging.getLogger("vystak.channel.runtime.agent_client")


@runtime_checkable
class AgentClient(Protocol):
    """Port for talking to an agent. Subclassed by A2A, future media-bridge, etc."""

    async def send_turn(
        self,
        agent_url: str,
        text: str,
        thread_id: str,
        history: list[Message] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AgentReply: ...

    async def stream_turn(
        self,
        agent_url: str,
        text: str,
        thread_id: str,
        history: list[Message] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AsyncIterator[AgentChunk]: ...


class A2AAgentClient:
    """A2A JSON-RPC client. Default for `agent_protocol in {a2a-turn, a2a-stream}`."""

    def __init__(
        self,
        timeout_s: float = 30.0,
        max_retries: int = 3,
        base_backoff: float = 0.5,
    ) -> None:
        self._timeout = timeout_s
        self._max_retries = max_retries
        self._base_backoff = base_backoff

    async def send_turn(
        self,
        agent_url: str,
        text: str,
        thread_id: str,
        history: list[Message] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AgentReply:
        url = agent_url.rstrip("/") + "/a2a"
        request_id = str(uuid.uuid4())
        params: dict[str, Any] = {
            "id": thread_id,
            "message": {"role": "user", "content": text},
        }
        if history:
            params["history"] = [m.model_dump() for m in history]
        if metadata:
            params["metadata"] = metadata
        body = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tasks/send",
            "params": params,
        }
        async with httpx.AsyncClient() as client:
            for attempt in range(1, self._max_retries + 1):
                try:
                    resp = await client.post(url, json=body, timeout=self._timeout)
                    if resp.status_code == 200:
                        return self._reply_from_jsonrpc(resp.json())
                    if 500 <= resp.status_code < 600 and attempt < self._max_retries:
                        await asyncio.sleep(self._base_backoff * (2 ** (attempt - 1)))
                        continue
                    raise AgentCallError(
                        f"agent {agent_url} returned {resp.status_code}: {resp.text[:200]}"
                    )
                except (httpx.ConnectError, httpx.ReadTimeout) as exc:
                    if attempt < self._max_retries:
                        await asyncio.sleep(self._base_backoff * (2 ** (attempt - 1)))
                        continue
                    raise AgentCallError(f"agent {agent_url} connect failed: {exc}") from exc
            raise AgentCallError(f"agent {agent_url} exhausted retries")

    async def stream_turn(
        self,
        agent_url: str,
        text: str,
        thread_id: str,
        history: list[Message] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AsyncIterator[AgentChunk]:
        url = agent_url.rstrip("/") + "/a2a"
        request_id = str(uuid.uuid4())
        params: dict[str, Any] = {
            "id": thread_id,
            "message": {"role": "user", "content": text},
        }
        if history:
            params["history"] = [m.model_dump() for m in history]
        if metadata:
            params["metadata"] = metadata
        body = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tasks/sendSubscribe",
            "params": params,
        }
        async with httpx.AsyncClient() as client:
            try:
                async with client.stream(
                    "POST", url, json=body, timeout=self._timeout
                ) as resp:
                    if resp.status_code != 200:
                        raise AgentCallError(
                            f"agent {agent_url} returned {resp.status_code}"
                        )
                    async for line in resp.aiter_lines():
                        if not line or not line.startswith("data:"):
                            continue
                        chunk = self._chunk_from_sse(line.removeprefix("data:").strip())
                        if chunk is not None:
                            yield chunk
            except (httpx.ConnectError, httpx.ReadTimeout) as exc:
                raise AgentCallError(
                    f"agent {agent_url} stream failed: {exc}"
                ) from exc

    @staticmethod
    def _reply_from_jsonrpc(payload: dict[str, Any]) -> AgentReply:
        if "error" in payload:
            raise AgentCallError(f"agent error: {payload['error']}")
        result = payload.get("result", {})
        messages = result.get("messages", [])
        text = ""
        for m in messages:
            if m.get("role") == "assistant":
                text = m.get("content", "")
                break
        return AgentReply(
            text=text,
            tool_calls=result.get("tool_calls", []),
            finish_reason=result.get("finish_reason"),
            raw=payload,
        )

    @staticmethod
    def _chunk_from_sse(data: str) -> AgentChunk | None:
        import json

        try:
            payload = json.loads(data)
        except json.JSONDecodeError:
            return None
        result = payload.get("result", {})
        delta = result.get("delta", "")
        if not delta and not result.get("finish_reason"):
            return None
        return AgentChunk(
            delta=delta,
            tool_call_delta=result.get("tool_call_delta"),
            finish_reason=result.get("finish_reason"),
            raw=payload,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest packages/python/vystak-channel-runtime/tests/test_agent_client.py -v`
Expected: 4 PASSED.

- [ ] **Step 5: Re-export**

Edit `packages/python/vystak-channel-runtime/src/vystak_channel_runtime/__init__.py` and add the agent client exports:

```python
from vystak_channel_runtime.agent_client import A2AAgentClient, AgentClient
```

Append `"A2AAgentClient", "AgentClient"` to `__all__`.

- [ ] **Step 6: Lint**

Run: `uv run ruff check packages/python/vystak-channel-runtime/`
Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add packages/python/vystak-channel-runtime/
git commit -m "feat(channel-runtime): add AgentClient protocol + A2AAgentClient with retry"
```

---

### Task 1.4: `ChannelStore` Protocol + `MemoryChannelStore`

**Files:**
- Create: `packages/python/vystak-channel-runtime/src/vystak_channel_runtime/store.py`
- Create: `packages/python/vystak-channel-runtime/tests/test_store.py`

- [ ] **Step 1: Write the failing test**

Create `packages/python/vystak-channel-runtime/tests/test_store.py`:

```python
"""Tests for ChannelStore impls."""

import pytest

from vystak_channel_runtime.store import (
    ChannelStore,
    MemoryChannelStore,
)


@pytest.mark.asyncio
async def test_memory_store_implements_protocol():
    s = MemoryChannelStore()
    assert isinstance(s, ChannelStore)


@pytest.mark.asyncio
async def test_thread_binding_round_trip():
    s = MemoryChannelStore()
    assert await s.get_thread_binding("slack", "T1", "C1:1.0") is None
    await s.set_thread_binding("slack", "T1", "C1:1.0", "hero")
    assert await s.get_thread_binding("slack", "T1", "C1:1.0") == "hero"


@pytest.mark.asyncio
async def test_thread_binding_overwrite():
    s = MemoryChannelStore()
    await s.set_thread_binding("slack", "T1", "C1:1.0", "hero")
    await s.set_thread_binding("slack", "T1", "C1:1.0", "villain")
    assert await s.get_thread_binding("slack", "T1", "C1:1.0") == "villain"


@pytest.mark.asyncio
async def test_thread_binding_delete():
    s = MemoryChannelStore()
    await s.set_thread_binding("slack", "T1", "C1:1.0", "hero")
    await s.delete_thread_binding("slack", "T1", "C1:1.0")
    assert await s.get_thread_binding("slack", "T1", "C1:1.0") is None


@pytest.mark.asyncio
async def test_route_pref_round_trip():
    s = MemoryChannelStore()
    assert await s.get_route_pref("slack", "T1") is None
    await s.set_route_pref("slack", "T1", "hero")
    assert await s.get_route_pref("slack", "T1") == "hero"
    await s.delete_route_pref("slack", "T1")
    assert await s.get_route_pref("slack", "T1") is None


@pytest.mark.asyncio
async def test_list_thread_bindings_filter():
    s = MemoryChannelStore()
    await s.set_thread_binding("slack", "T1", "t1", "hero")
    await s.set_thread_binding("slack", "T1", "t2", "villain")
    await s.set_thread_binding("slack", "T2", "t1", "hero")
    rows_t1 = await s.list_thread_bindings("slack", "T1")
    assert {r.thread_id for r in rows_t1} == {"t1", "t2"}
    all_slack = await s.list_thread_bindings("slack")
    assert len(all_slack) == 3


@pytest.mark.asyncio
async def test_isolation_by_channel_type():
    s = MemoryChannelStore()
    await s.set_thread_binding("slack", "T1", "x", "hero")
    assert await s.get_thread_binding("discord", "T1", "x") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/python/vystak-channel-runtime/tests/test_store.py -v`
Expected: ImportError on `vystak_channel_runtime.store`.

- [ ] **Step 3: Implement `store.py` (Protocol + Memory impl only — SQLite/Postgres come next tasks)**

Create `packages/python/vystak-channel-runtime/src/vystak_channel_runtime/store.py`:

```python
"""Channel store: persist thread bindings + route prefs across channel types."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Protocol, runtime_checkable

from vystak_channel_runtime.types import ThreadBinding


@runtime_checkable
class ChannelStore(Protocol):
    """Generic store for runtime channel state.

    All keys are namespaced by (channel_type, scope_id, thread_id).
    Scope id meaning is per-channel:
      slack:   team_id
      discord: f"{guild_id}/{channel_id}" (or "dm/{user_id}")
      chat:    session originator
    """

    async def get_thread_binding(
        self, channel_type: str, scope_id: str, thread_id: str
    ) -> str | None: ...

    async def set_thread_binding(
        self,
        channel_type: str,
        scope_id: str,
        thread_id: str,
        agent_name: str,
        user_id: str | None = None,
    ) -> None: ...

    async def delete_thread_binding(
        self, channel_type: str, scope_id: str, thread_id: str
    ) -> None: ...

    async def get_route_pref(
        self, channel_type: str, scope_id: str
    ) -> str | None: ...

    async def set_route_pref(
        self, channel_type: str, scope_id: str, agent_name: str
    ) -> None: ...

    async def delete_route_pref(
        self, channel_type: str, scope_id: str
    ) -> None: ...

    async def list_thread_bindings(
        self, channel_type: str, scope_id: str | None = None
    ) -> list[ThreadBinding]: ...

    async def close(self) -> None: ...


class MemoryChannelStore:
    """In-memory ChannelStore. Loses state on restart. Test default."""

    def __init__(self) -> None:
        self._threads: dict[tuple[str, str, str], dict[str, Any]] = {}
        self._prefs: dict[tuple[str, str], str] = {}

    async def get_thread_binding(
        self, channel_type: str, scope_id: str, thread_id: str
    ) -> str | None:
        row = self._threads.get((channel_type, scope_id, thread_id))
        return row["agent_name"] if row else None

    async def set_thread_binding(
        self,
        channel_type: str,
        scope_id: str,
        thread_id: str,
        agent_name: str,
        user_id: str | None = None,
    ) -> None:
        now = datetime.now(timezone.utc)
        existing = self._threads.get((channel_type, scope_id, thread_id))
        created = existing["created_at"] if existing else now
        self._threads[(channel_type, scope_id, thread_id)] = {
            "agent_name": agent_name,
            "user_id": user_id,
            "created_at": created,
            "updated_at": now,
        }

    async def delete_thread_binding(
        self, channel_type: str, scope_id: str, thread_id: str
    ) -> None:
        self._threads.pop((channel_type, scope_id, thread_id), None)

    async def get_route_pref(
        self, channel_type: str, scope_id: str
    ) -> str | None:
        return self._prefs.get((channel_type, scope_id))

    async def set_route_pref(
        self, channel_type: str, scope_id: str, agent_name: str
    ) -> None:
        self._prefs[(channel_type, scope_id)] = agent_name

    async def delete_route_pref(
        self, channel_type: str, scope_id: str
    ) -> None:
        self._prefs.pop((channel_type, scope_id), None)

    async def list_thread_bindings(
        self, channel_type: str, scope_id: str | None = None
    ) -> list[ThreadBinding]:
        out: list[ThreadBinding] = []
        for (ct, sid, tid), row in self._threads.items():
            if ct != channel_type:
                continue
            if scope_id is not None and sid != scope_id:
                continue
            out.append(
                ThreadBinding(
                    channel_type=ct,
                    scope_id=sid,
                    thread_id=tid,
                    agent_name=row["agent_name"],
                    user_id=row.get("user_id"),
                    created_at=row.get("created_at"),
                    updated_at=row.get("updated_at"),
                )
            )
        return out

    async def close(self) -> None:
        self._threads.clear()
        self._prefs.clear()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest packages/python/vystak-channel-runtime/tests/test_store.py -v`
Expected: 7 PASSED.

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-channel-runtime/
git commit -m "feat(channel-runtime): add ChannelStore protocol + MemoryChannelStore"
```

---

### Task 1.5: `SqliteChannelStore`

**Files:**
- Modify: `packages/python/vystak-channel-runtime/src/vystak_channel_runtime/store.py`
- Modify: `packages/python/vystak-channel-runtime/tests/test_store.py`

- [ ] **Step 1: Add the failing test**

Append to `packages/python/vystak-channel-runtime/tests/test_store.py`:

```python
from pathlib import Path

from vystak_channel_runtime.store import SqliteChannelStore


@pytest.fixture
def sqlite_store(tmp_path: Path):
    return SqliteChannelStore(str(tmp_path / "channel.db"))


@pytest.mark.asyncio
async def test_sqlite_store_implements_protocol(sqlite_store):
    assert isinstance(sqlite_store, ChannelStore)


@pytest.mark.asyncio
async def test_sqlite_thread_binding_round_trip(sqlite_store):
    assert await sqlite_store.get_thread_binding("slack", "T1", "C:1") is None
    await sqlite_store.set_thread_binding("slack", "T1", "C:1", "hero")
    assert await sqlite_store.get_thread_binding("slack", "T1", "C:1") == "hero"
    await sqlite_store.close()


@pytest.mark.asyncio
async def test_sqlite_route_pref_round_trip(sqlite_store):
    await sqlite_store.set_route_pref("slack", "T1", "hero")
    assert await sqlite_store.get_route_pref("slack", "T1") == "hero"
    await sqlite_store.delete_route_pref("slack", "T1")
    assert await sqlite_store.get_route_pref("slack", "T1") is None
    await sqlite_store.close()


@pytest.mark.asyncio
async def test_sqlite_persists_across_instances(tmp_path):
    path = str(tmp_path / "channel.db")
    s1 = SqliteChannelStore(path)
    await s1.set_thread_binding("slack", "T1", "C:1", "hero")
    await s1.close()
    s2 = SqliteChannelStore(path)
    assert await s2.get_thread_binding("slack", "T1", "C:1") == "hero"
    await s2.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/python/vystak-channel-runtime/tests/test_store.py -v -k sqlite`
Expected: ImportError on `SqliteChannelStore`.

- [ ] **Step 3: Implement `SqliteChannelStore`**

Append to `packages/python/vystak-channel-runtime/src/vystak_channel_runtime/store.py`:

```python
import aiosqlite

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS thread_bindings (
    channel_type TEXT NOT NULL,
    scope_id     TEXT NOT NULL,
    thread_id    TEXT NOT NULL,
    agent_name   TEXT NOT NULL,
    user_id      TEXT,
    created_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (channel_type, scope_id, thread_id)
);

CREATE TABLE IF NOT EXISTS route_prefs (
    channel_type TEXT NOT NULL,
    scope_id     TEXT NOT NULL,
    agent_name   TEXT NOT NULL,
    created_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (channel_type, scope_id)
);

CREATE INDEX IF NOT EXISTS idx_thread_bindings_scope
    ON thread_bindings (channel_type, scope_id);
"""


class SqliteChannelStore:
    """ChannelStore backed by aiosqlite (single-file SQLite)."""

    def __init__(self, path: str) -> None:
        self._path = path
        self._lock = None  # type: ignore[assignment]

    async def _ensure(self) -> aiosqlite.Connection:
        # Lazy connection; aiosqlite is per-connection threadsafe.
        conn = await aiosqlite.connect(self._path)
        for stmt in _SCHEMA_SQL.split(";"):
            stmt = stmt.strip()
            if stmt:
                await conn.execute(stmt)
        await conn.commit()
        return conn

    async def get_thread_binding(
        self, channel_type: str, scope_id: str, thread_id: str
    ) -> str | None:
        conn = await self._ensure()
        try:
            cur = await conn.execute(
                "SELECT agent_name FROM thread_bindings "
                "WHERE channel_type=? AND scope_id=? AND thread_id=?",
                (channel_type, scope_id, thread_id),
            )
            row = await cur.fetchone()
            return row[0] if row else None
        finally:
            await conn.close()

    async def set_thread_binding(
        self,
        channel_type: str,
        scope_id: str,
        thread_id: str,
        agent_name: str,
        user_id: str | None = None,
    ) -> None:
        conn = await self._ensure()
        try:
            await conn.execute(
                """
                INSERT INTO thread_bindings
                    (channel_type, scope_id, thread_id, agent_name, user_id)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(channel_type, scope_id, thread_id) DO UPDATE SET
                    agent_name=excluded.agent_name,
                    user_id=excluded.user_id,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (channel_type, scope_id, thread_id, agent_name, user_id),
            )
            await conn.commit()
        finally:
            await conn.close()

    async def delete_thread_binding(
        self, channel_type: str, scope_id: str, thread_id: str
    ) -> None:
        conn = await self._ensure()
        try:
            await conn.execute(
                "DELETE FROM thread_bindings "
                "WHERE channel_type=? AND scope_id=? AND thread_id=?",
                (channel_type, scope_id, thread_id),
            )
            await conn.commit()
        finally:
            await conn.close()

    async def get_route_pref(
        self, channel_type: str, scope_id: str
    ) -> str | None:
        conn = await self._ensure()
        try:
            cur = await conn.execute(
                "SELECT agent_name FROM route_prefs "
                "WHERE channel_type=? AND scope_id=?",
                (channel_type, scope_id),
            )
            row = await cur.fetchone()
            return row[0] if row else None
        finally:
            await conn.close()

    async def set_route_pref(
        self, channel_type: str, scope_id: str, agent_name: str
    ) -> None:
        conn = await self._ensure()
        try:
            await conn.execute(
                """
                INSERT INTO route_prefs (channel_type, scope_id, agent_name)
                VALUES (?, ?, ?)
                ON CONFLICT(channel_type, scope_id) DO UPDATE SET
                    agent_name=excluded.agent_name,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (channel_type, scope_id, agent_name),
            )
            await conn.commit()
        finally:
            await conn.close()

    async def delete_route_pref(
        self, channel_type: str, scope_id: str
    ) -> None:
        conn = await self._ensure()
        try:
            await conn.execute(
                "DELETE FROM route_prefs WHERE channel_type=? AND scope_id=?",
                (channel_type, scope_id),
            )
            await conn.commit()
        finally:
            await conn.close()

    async def list_thread_bindings(
        self, channel_type: str, scope_id: str | None = None
    ) -> list[ThreadBinding]:
        conn = await self._ensure()
        try:
            if scope_id is None:
                cur = await conn.execute(
                    "SELECT channel_type, scope_id, thread_id, agent_name, user_id, "
                    "created_at, updated_at FROM thread_bindings WHERE channel_type=?",
                    (channel_type,),
                )
            else:
                cur = await conn.execute(
                    "SELECT channel_type, scope_id, thread_id, agent_name, user_id, "
                    "created_at, updated_at FROM thread_bindings "
                    "WHERE channel_type=? AND scope_id=?",
                    (channel_type, scope_id),
                )
            rows = await cur.fetchall()
            return [
                ThreadBinding(
                    channel_type=r[0],
                    scope_id=r[1],
                    thread_id=r[2],
                    agent_name=r[3],
                    user_id=r[4],
                )
                for r in rows
            ]
        finally:
            await conn.close()

    async def close(self) -> None:
        # No persistent connection to close.
        pass
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest packages/python/vystak-channel-runtime/tests/test_store.py -v -k sqlite`
Expected: 4 PASSED.

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-channel-runtime/
git commit -m "feat(channel-runtime): add SqliteChannelStore"
```

---

### Task 1.6: `PostgresChannelStore`

**Files:**
- Modify: `packages/python/vystak-channel-runtime/src/vystak_channel_runtime/store.py`
- Modify: `packages/python/vystak-channel-runtime/tests/test_store.py`

- [ ] **Step 1: Add the failing test (docker-marked, requires real Postgres)**

Append to `packages/python/vystak-channel-runtime/tests/test_store.py`:

```python
from vystak_channel_runtime.store import PostgresChannelStore


@pytest.mark.docker
@pytest.mark.asyncio
async def test_postgres_store_round_trip(postgres_dsn):
    s = PostgresChannelStore(postgres_dsn)
    await s.set_thread_binding("slack", "T1", "C:1", "hero")
    assert await s.get_thread_binding("slack", "T1", "C:1") == "hero"
    await s.delete_thread_binding("slack", "T1", "C:1")
    assert await s.get_thread_binding("slack", "T1", "C:1") is None
    await s.close()


@pytest.mark.docker
@pytest.mark.asyncio
async def test_postgres_route_pref(postgres_dsn):
    s = PostgresChannelStore(postgres_dsn)
    await s.set_route_pref("slack", "T1", "hero")
    assert await s.get_route_pref("slack", "T1") == "hero"
    await s.delete_route_pref("slack", "T1")
    await s.close()
```

Append to `packages/python/vystak-channel-runtime/tests/conftest.py`:

```python
import os


@pytest.fixture
def postgres_dsn():
    """Postgres DSN for docker-marked tests.

    Docker test job sets POSTGRES_DSN; tests skip if absent.
    """
    dsn = os.environ.get("POSTGRES_DSN")
    if not dsn:
        pytest.skip("POSTGRES_DSN not set")
    return dsn
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/python/vystak-channel-runtime/tests/test_store.py -v -k postgres -m docker`
Expected: ImportError on `PostgresChannelStore` (or skipped if no DSN).

- [ ] **Step 3: Implement `PostgresChannelStore`**

Append to `packages/python/vystak-channel-runtime/src/vystak_channel_runtime/store.py`:

```python
import asyncpg

_PG_SCHEMA_SQL = [
    """
    CREATE TABLE IF NOT EXISTS thread_bindings (
        channel_type TEXT NOT NULL,
        scope_id     TEXT NOT NULL,
        thread_id    TEXT NOT NULL,
        agent_name   TEXT NOT NULL,
        user_id      TEXT,
        created_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (channel_type, scope_id, thread_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS route_prefs (
        channel_type TEXT NOT NULL,
        scope_id     TEXT NOT NULL,
        agent_name   TEXT NOT NULL,
        created_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (channel_type, scope_id)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_thread_bindings_scope
        ON thread_bindings (channel_type, scope_id)
    """,
]


class PostgresChannelStore:
    """ChannelStore backed by asyncpg."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._pool: asyncpg.Pool | None = None

    async def _ensure(self) -> asyncpg.Pool:
        if self._pool is None:
            self._pool = await asyncpg.create_pool(self._dsn, min_size=1, max_size=4)
            async with self._pool.acquire() as conn:
                for stmt in _PG_SCHEMA_SQL:
                    await conn.execute(stmt)
        return self._pool

    async def get_thread_binding(
        self, channel_type: str, scope_id: str, thread_id: str
    ) -> str | None:
        pool = await self._ensure()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT agent_name FROM thread_bindings "
                "WHERE channel_type=$1 AND scope_id=$2 AND thread_id=$3",
                channel_type, scope_id, thread_id,
            )
            return row["agent_name"] if row else None

    async def set_thread_binding(
        self,
        channel_type: str,
        scope_id: str,
        thread_id: str,
        agent_name: str,
        user_id: str | None = None,
    ) -> None:
        pool = await self._ensure()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO thread_bindings
                    (channel_type, scope_id, thread_id, agent_name, user_id)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (channel_type, scope_id, thread_id) DO UPDATE SET
                    agent_name=EXCLUDED.agent_name,
                    user_id=EXCLUDED.user_id,
                    updated_at=CURRENT_TIMESTAMP
                """,
                channel_type, scope_id, thread_id, agent_name, user_id,
            )

    async def delete_thread_binding(
        self, channel_type: str, scope_id: str, thread_id: str
    ) -> None:
        pool = await self._ensure()
        async with pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM thread_bindings "
                "WHERE channel_type=$1 AND scope_id=$2 AND thread_id=$3",
                channel_type, scope_id, thread_id,
            )

    async def get_route_pref(
        self, channel_type: str, scope_id: str
    ) -> str | None:
        pool = await self._ensure()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT agent_name FROM route_prefs "
                "WHERE channel_type=$1 AND scope_id=$2",
                channel_type, scope_id,
            )
            return row["agent_name"] if row else None

    async def set_route_pref(
        self, channel_type: str, scope_id: str, agent_name: str
    ) -> None:
        pool = await self._ensure()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO route_prefs (channel_type, scope_id, agent_name)
                VALUES ($1, $2, $3)
                ON CONFLICT (channel_type, scope_id) DO UPDATE SET
                    agent_name=EXCLUDED.agent_name,
                    updated_at=CURRENT_TIMESTAMP
                """,
                channel_type, scope_id, agent_name,
            )

    async def delete_route_pref(
        self, channel_type: str, scope_id: str
    ) -> None:
        pool = await self._ensure()
        async with pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM route_prefs WHERE channel_type=$1 AND scope_id=$2",
                channel_type, scope_id,
            )

    async def list_thread_bindings(
        self, channel_type: str, scope_id: str | None = None
    ) -> list[ThreadBinding]:
        pool = await self._ensure()
        async with pool.acquire() as conn:
            if scope_id is None:
                rows = await conn.fetch(
                    "SELECT channel_type, scope_id, thread_id, agent_name, user_id, "
                    "created_at, updated_at FROM thread_bindings "
                    "WHERE channel_type=$1",
                    channel_type,
                )
            else:
                rows = await conn.fetch(
                    "SELECT channel_type, scope_id, thread_id, agent_name, user_id, "
                    "created_at, updated_at FROM thread_bindings "
                    "WHERE channel_type=$1 AND scope_id=$2",
                    channel_type, scope_id,
                )
            return [
                ThreadBinding(
                    channel_type=r["channel_type"],
                    scope_id=r["scope_id"],
                    thread_id=r["thread_id"],
                    agent_name=r["agent_name"],
                    user_id=r["user_id"],
                    created_at=r["created_at"],
                    updated_at=r["updated_at"],
                )
                for r in rows
            ]

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None
```

- [ ] **Step 4: Run docker-marked test (locally with a Postgres container)**

```bash
docker run -d --name plan-pg-test -p 55432:5432 -e POSTGRES_PASSWORD=t -e POSTGRES_DB=t postgres:16
export POSTGRES_DSN=postgresql://postgres:t@localhost:55432/t
sleep 2
uv run pytest packages/python/vystak-channel-runtime/tests/test_store.py -v -k postgres -m docker
docker rm -f plan-pg-test
unset POSTGRES_DSN
```

Expected: 2 PASSED.

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-channel-runtime/
git commit -m "feat(channel-runtime): add PostgresChannelStore"
```

---

### Task 1.7: `make_channel_store` factory

**Files:**
- Modify: `packages/python/vystak-channel-runtime/src/vystak_channel_runtime/store.py`
- Modify: `packages/python/vystak-channel-runtime/tests/test_store.py`

- [ ] **Step 1: Add the failing test**

Append to `tests/test_store.py`:

```python
from vystak_channel_runtime.store import make_channel_store


def test_make_channel_store_none_returns_memory():
    s = make_channel_store(None)
    assert isinstance(s, MemoryChannelStore)


def test_make_channel_store_sqlite(tmp_path):
    cfg = {"type": "sqlite", "path": str(tmp_path / "x.db")}
    s = make_channel_store(cfg)
    assert isinstance(s, SqliteChannelStore)


def test_make_channel_store_postgres():
    cfg = {"type": "postgres", "dsn": "postgresql://u:p@h/db"}
    s = make_channel_store(cfg)
    assert isinstance(s, PostgresChannelStore)


def test_make_channel_store_unknown_raises():
    with pytest.raises(ValueError):
        make_channel_store({"type": "redis"})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/python/vystak-channel-runtime/tests/test_store.py -v -k make_channel_store`
Expected: ImportError.

- [ ] **Step 3: Implement the factory**

Append to `store.py`:

```python
def make_channel_store(state_config: dict | None) -> ChannelStore:
    """Build a ChannelStore from a Service-shaped config dict.

    Accepts None (-> MemoryChannelStore) or one of:
      {"type": "sqlite",   "path": "/path/to.db"}
      {"type": "postgres", "dsn":  "postgresql://..."}
      {"type": "memory"}
    """
    if state_config is None:
        return MemoryChannelStore()
    kind = state_config.get("type")
    if kind in (None, "memory"):
        return MemoryChannelStore()
    if kind == "sqlite":
        return SqliteChannelStore(state_config["path"])
    if kind == "postgres":
        return PostgresChannelStore(state_config["dsn"])
    raise ValueError(f"unknown channel store type: {kind!r}")
```

Re-export in `__init__.py`:

```python
from vystak_channel_runtime.store import (
    ChannelStore,
    MemoryChannelStore,
    PostgresChannelStore,
    SqliteChannelStore,
    make_channel_store,
)
```

Append to `__all__`: `"ChannelStore", "MemoryChannelStore", "PostgresChannelStore", "SqliteChannelStore", "make_channel_store"`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest packages/python/vystak-channel-runtime/tests/test_store.py -v -k make_channel_store`
Expected: 4 PASSED.

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-channel-runtime/
git commit -m "feat(channel-runtime): add make_channel_store factory"
```

---

### Task 1.8: `ChannelRuntime` ABC — lifecycle + `authorize`

**Files:**
- Create: `packages/python/vystak-channel-runtime/src/vystak_channel_runtime/runtime.py`
- Create: `packages/python/vystak-channel-runtime/tests/test_runtime.py`

- [ ] **Step 1: Write the failing test**

Create `packages/python/vystak-channel-runtime/tests/test_runtime.py`:

```python
"""Tests for ChannelRuntime base class."""

import pytest
from vystak.schema.common import ChannelType
from vystak_channel_runtime.runtime import ChannelRuntime
from vystak_channel_runtime.store import MemoryChannelStore
from vystak_channel_runtime.types import (
    AgentReply,
    InboundEvent,
    SkipEvent,
)


class TrivialRuntime(ChannelRuntime):
    """Minimal ChannelRuntime subclass for unit tests."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.posted: list[tuple[InboundEvent, str, AgentReply]] = []

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    def parse_event(self, raw):
        if raw.get("skip"):
            raise SkipEvent("skip")
        return InboundEvent(
            channel_type=ChannelType.SLACK,
            scope_id=raw["scope_id"],
            thread_id=raw.get("thread_id"),
            user_id=raw["user_id"],
            text=raw["text"],
            is_dm=raw.get("is_dm", False),
            mentions_bot=raw.get("mentions_bot", True),
            metadata={},
            raw=raw,
        )

    async def post_reply(self, event, route, reply):
        self.posted.append((event, route, reply))


def _config(**overrides):
    base = {
        "channel_type": "slack",
        "agent_protocol": "a2a-turn",
        "agents": ["hero"],
        "default_agent": "hero",
        "group_policy": "open",
        "dm_policy": "open",
        "allow_from": [],
        "allow_bots": False,
        "channel_overrides": {},
    }
    base.update(overrides)
    return base


def _routes():
    return {"hero": {"canonical": "hero.agents.default", "address": "http://hero:8000"}}


@pytest.mark.asyncio
async def test_authorize_blocks_bots_when_allow_bots_false():
    rt = TrivialRuntime(
        config=_config(allow_bots=False),
        routes=_routes(),
        store=MemoryChannelStore(),
    )
    ev = InboundEvent(
        channel_type=ChannelType.SLACK, scope_id="T1", thread_id=None,
        user_id="U_BOT", text="hi", is_dm=False, mentions_bot=True,
        metadata={"is_bot": True},
    )
    assert await rt.authorize(ev) is False


@pytest.mark.asyncio
async def test_authorize_allows_when_allow_bots_true():
    rt = TrivialRuntime(
        config=_config(allow_bots=True),
        routes=_routes(),
        store=MemoryChannelStore(),
    )
    ev = InboundEvent(
        channel_type=ChannelType.SLACK, scope_id="T1", thread_id=None,
        user_id="U_BOT", text="hi", is_dm=False, mentions_bot=True,
        metadata={"is_bot": True},
    )
    assert await rt.authorize(ev) is True


@pytest.mark.asyncio
async def test_authorize_dm_disabled():
    rt = TrivialRuntime(
        config=_config(dm_policy="disabled"),
        routes=_routes(),
        store=MemoryChannelStore(),
    )
    ev = InboundEvent(
        channel_type=ChannelType.SLACK, scope_id="T1", thread_id=None,
        user_id="U", text="hi", is_dm=True, mentions_bot=False,
    )
    assert await rt.authorize(ev) is False


@pytest.mark.asyncio
async def test_authorize_allowlist_blocks_unknown_user():
    rt = TrivialRuntime(
        config=_config(group_policy="allowlist", allow_from=["U_OK"]),
        routes=_routes(),
        store=MemoryChannelStore(),
    )
    ev = InboundEvent(
        channel_type=ChannelType.SLACK, scope_id="T1", thread_id=None,
        user_id="U_NOPE", text="hi", is_dm=False, mentions_bot=True,
    )
    assert await rt.authorize(ev) is False


@pytest.mark.asyncio
async def test_authorize_allowlist_admits_known_user():
    rt = TrivialRuntime(
        config=_config(group_policy="allowlist", allow_from=["U_OK"]),
        routes=_routes(),
        store=MemoryChannelStore(),
    )
    ev = InboundEvent(
        channel_type=ChannelType.SLACK, scope_id="T1", thread_id=None,
        user_id="U_OK", text="hi", is_dm=False, mentions_bot=True,
    )
    assert await rt.authorize(ev) is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/python/vystak-channel-runtime/tests/test_runtime.py -v`
Expected: ImportError on `vystak_channel_runtime.runtime`.

- [ ] **Step 3: Implement `runtime.py` (skeleton + authorize)**

Create `packages/python/vystak-channel-runtime/src/vystak_channel_runtime/runtime.py`:

```python
"""ChannelRuntime — template-method base for all channel containers."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

from vystak_channel_runtime.agent_client import (
    A2AAgentClient,
    AgentClient,
)
from vystak_channel_runtime.store import ChannelStore
from vystak_channel_runtime.types import (
    AgentCallError,
    AgentReply,
    InboundEvent,
    Message,
    SkipEvent,
)

logger = logging.getLogger("vystak.channel.runtime")


class ChannelRuntime(ABC):
    """Template-method base — owns the message lifecycle.

    Subclasses implement: start, stop, parse_event, post_reply.
    Subclasses may override: fetch_history, before_call, after_reply,
    on_no_route, on_agent_error.
    """

    def __init__(
        self,
        config: dict,
        routes: dict,
        store: ChannelStore,
        agent_client: AgentClient | None = None,
    ) -> None:
        self.config = config
        self.routes = routes
        self.store = store
        self.channel_type: str = config.get("channel_type", "")
        self.agent_protocol: str = config.get("agent_protocol", "a2a-turn")
        self._agent_client = agent_client or self._default_agent_client()

    def _default_agent_client(self) -> AgentClient:
        if self.agent_protocol in ("a2a-turn", "a2a-stream"):
            return A2AAgentClient()
        if self.agent_protocol == "media-bridge":
            raise NotImplementedError("media-bridge requires a custom AgentClient")
        raise ValueError(f"unknown agent_protocol: {self.agent_protocol}")

    # --- Lifecycle (subclass implements) ----------------------------------

    @abstractmethod
    async def start(self) -> None: ...

    @abstractmethod
    async def stop(self) -> None: ...

    # --- Pipeline hooks (subclass implements) -----------------------------

    @abstractmethod
    def parse_event(self, raw_event: Any) -> InboundEvent: ...

    @abstractmethod
    async def post_reply(
        self, event: InboundEvent, route: str, reply: AgentReply
    ) -> None: ...

    # --- Pipeline hooks (subclass may override; defaults below) -----------

    async def fetch_history(self, event: InboundEvent) -> list[Message]:
        return []

    async def before_call(self, event: InboundEvent, route: str) -> None:
        return None

    async def after_reply(
        self, event: InboundEvent, route: str, reply: AgentReply
    ) -> None:
        if event.thread_id is not None:
            await self.store.set_thread_binding(
                self.channel_type,
                event.scope_id,
                event.thread_id,
                route,
                user_id=event.user_id,
            )

    async def on_no_route(self, event: InboundEvent) -> None:
        logger.info(
            "no route for event scope=%s thread=%s user=%s",
            event.scope_id, event.thread_id, event.user_id,
        )

    async def on_agent_error(
        self, event: InboundEvent, route: str, exc: AgentCallError
    ) -> None:
        logger.exception(
            "agent call failed for route=%s scope=%s: %s",
            route, event.scope_id, exc,
        )

    # --- Authorize (base owns) --------------------------------------------

    async def authorize(self, event: InboundEvent) -> bool:
        is_bot = bool(event.metadata.get("is_bot"))
        if is_bot and not self.config.get("allow_bots", False):
            return False
        policy = (
            self.config.get("dm_policy")
            if event.is_dm
            else self.config.get("group_policy")
        )
        if policy == "disabled":
            return False
        if policy == "allowlist":
            allow_from = self.config.get("allow_from", [])
            if event.user_id not in allow_from:
                return False
        return True
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest packages/python/vystak-channel-runtime/tests/test_runtime.py -v`
Expected: 5 PASSED.

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-channel-runtime/
git commit -m "feat(channel-runtime): add ChannelRuntime ABC with authorize hook"
```

---

### Task 1.9: `ChannelRuntime.resolve_route`

**Files:**
- Modify: `packages/python/vystak-channel-runtime/src/vystak_channel_runtime/runtime.py`
- Modify: `packages/python/vystak-channel-runtime/tests/test_runtime.py`

- [ ] **Step 1: Add the failing test**

Append to `tests/test_runtime.py`:

```python
@pytest.mark.asyncio
async def test_resolve_route_uses_channel_override():
    rt = TrivialRuntime(
        config=_config(channel_overrides={"C1": {"agent": "villain"}}),
        routes=_routes(),
        store=MemoryChannelStore(),
    )
    ev = InboundEvent(
        channel_type=ChannelType.SLACK, scope_id="C1", thread_id=None,
        user_id="U", text="hi", is_dm=False, mentions_bot=True,
    )
    assert await rt.resolve_route(ev) == "villain"


@pytest.mark.asyncio
async def test_resolve_route_uses_thread_binding_when_no_override():
    store = MemoryChannelStore()
    await store.set_thread_binding("slack", "C1", "T:1.0", "villain")
    rt = TrivialRuntime(
        config=_config(),
        routes=_routes(),
        store=store,
    )
    ev = InboundEvent(
        channel_type=ChannelType.SLACK, scope_id="C1", thread_id="T:1.0",
        user_id="U", text="hi", is_dm=False, mentions_bot=True,
    )
    assert await rt.resolve_route(ev) == "villain"


@pytest.mark.asyncio
async def test_resolve_route_uses_route_pref_for_dm():
    store = MemoryChannelStore()
    await store.set_route_pref("slack", "U", "villain")
    rt = TrivialRuntime(
        config=_config(),
        routes=_routes(),
        store=store,
    )
    ev = InboundEvent(
        channel_type=ChannelType.SLACK, scope_id="U", thread_id=None,
        user_id="U", text="hi", is_dm=True, mentions_bot=False,
    )
    assert await rt.resolve_route(ev) == "villain"


@pytest.mark.asyncio
async def test_resolve_route_falls_back_to_default_agent():
    rt = TrivialRuntime(
        config=_config(default_agent="hero"),
        routes=_routes(),
        store=MemoryChannelStore(),
    )
    ev = InboundEvent(
        channel_type=ChannelType.SLACK, scope_id="C1", thread_id=None,
        user_id="U", text="hi", is_dm=False, mentions_bot=True,
    )
    assert await rt.resolve_route(ev) == "hero"


@pytest.mark.asyncio
async def test_resolve_route_returns_none_when_no_default():
    rt = TrivialRuntime(
        config=_config(default_agent=None),
        routes=_routes(),
        store=MemoryChannelStore(),
    )
    ev = InboundEvent(
        channel_type=ChannelType.SLACK, scope_id="C1", thread_id=None,
        user_id="U", text="hi", is_dm=False, mentions_bot=True,
    )
    assert await rt.resolve_route(ev) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/python/vystak-channel-runtime/tests/test_runtime.py -v -k resolve_route`
Expected: AttributeError on `resolve_route`.

- [ ] **Step 3: Add `resolve_route` to `runtime.py`**

Append to `runtime.py` (inside the `ChannelRuntime` class, alongside `authorize`):

```python
    async def resolve_route(self, event: InboundEvent) -> str | None:
        """Order: channel_overrides -> thread_binding -> route_pref (DM) -> default_agent."""
        ov = self.config.get("channel_overrides", {}).get(event.scope_id)
        if ov is not None and isinstance(ov, dict) and ov.get("agent"):
            return ov["agent"]

        if event.thread_id is not None:
            bound = await self.store.get_thread_binding(
                self.channel_type, event.scope_id, event.thread_id,
            )
            if bound:
                return bound

        if event.is_dm:
            pref = await self.store.get_route_pref(
                self.channel_type, event.scope_id,
            )
            if pref:
                return pref

        return self.config.get("default_agent")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest packages/python/vystak-channel-runtime/tests/test_runtime.py -v -k resolve_route`
Expected: 5 PASSED.

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-channel-runtime/
git commit -m "feat(channel-runtime): add resolve_route (overrides → bindings → prefs → default)"
```

---

### Task 1.10: `ChannelRuntime.call_agent` + `handle_event` pipeline

**Files:**
- Modify: `packages/python/vystak-channel-runtime/src/vystak_channel_runtime/runtime.py`
- Modify: `packages/python/vystak-channel-runtime/tests/test_runtime.py`

- [ ] **Step 1: Add the failing test**

Append to `tests/test_runtime.py`:

```python
class FakeAgentClient:
    def __init__(self):
        self.calls = []

    async def send_turn(self, agent_url, text, thread_id, history=None, metadata=None):
        self.calls.append({"url": agent_url, "text": text, "thread_id": thread_id})
        return AgentReply(text=f"reply to: {text}")

    async def stream_turn(self, *args, **kwargs):
        raise NotImplementedError


@pytest.mark.asyncio
async def test_handle_event_full_pipeline_happy_path():
    fc = FakeAgentClient()
    store = MemoryChannelStore()
    rt = TrivialRuntime(
        config=_config(),
        routes=_routes(),
        store=store,
        agent_client=fc,
    )
    await rt.handle_event({"scope_id": "C1", "thread_id": "T:1", "user_id": "U", "text": "hi"})
    assert len(rt.posted) == 1
    ev, route, reply = rt.posted[0]
    assert route == "hero"
    assert reply.text == "reply to: hi"
    assert fc.calls[0]["url"] == "http://hero:8000"
    # thread binding persisted in after_reply
    assert await store.get_thread_binding("slack", "C1", "T:1") == "hero"


@pytest.mark.asyncio
async def test_handle_event_skips_when_parse_event_raises_skip():
    rt = TrivialRuntime(
        config=_config(),
        routes=_routes(),
        store=MemoryChannelStore(),
        agent_client=FakeAgentClient(),
    )
    await rt.handle_event({"skip": True})
    assert rt.posted == []


@pytest.mark.asyncio
async def test_handle_event_drops_when_authorize_false():
    rt = TrivialRuntime(
        config=_config(group_policy="disabled"),
        routes=_routes(),
        store=MemoryChannelStore(),
        agent_client=FakeAgentClient(),
    )
    await rt.handle_event({"scope_id": "C1", "user_id": "U", "text": "hi"})
    assert rt.posted == []


@pytest.mark.asyncio
async def test_handle_event_no_route_calls_on_no_route():
    fc = FakeAgentClient()

    class NoRouteRuntime(TrivialRuntime):
        def __init__(self, **kw):
            super().__init__(**kw)
            self.no_route_count = 0

        async def on_no_route(self, event):
            self.no_route_count += 1

    rt = NoRouteRuntime(
        config=_config(default_agent=None),
        routes=_routes(),
        store=MemoryChannelStore(),
        agent_client=fc,
    )
    await rt.handle_event({"scope_id": "C1", "user_id": "U", "text": "hi"})
    assert rt.no_route_count == 1
    assert rt.posted == []


@pytest.mark.asyncio
async def test_handle_event_agent_error_routes_to_handler():
    class FailingClient:
        async def send_turn(self, *a, **kw):
            raise AgentCallError("boom")
        async def stream_turn(self, *a, **kw):
            raise NotImplementedError

    class CapturingRuntime(TrivialRuntime):
        def __init__(self, **kw):
            super().__init__(**kw)
            self.errors = []

        async def on_agent_error(self, event, route, exc):
            self.errors.append((route, str(exc)))

    rt = CapturingRuntime(
        config=_config(),
        routes=_routes(),
        store=MemoryChannelStore(),
        agent_client=FailingClient(),
    )
    await rt.handle_event({"scope_id": "C1", "user_id": "U", "text": "hi"})
    assert rt.errors == [("hero", "boom")]
    assert rt.posted == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/python/vystak-channel-runtime/tests/test_runtime.py -v -k handle_event`
Expected: AttributeError on `handle_event` / `call_agent`.

- [ ] **Step 3: Add `call_agent` + `handle_event` to `runtime.py`**

Append to the `ChannelRuntime` class:

```python
    async def call_agent(
        self,
        event: InboundEvent,
        route: str,
        history: list[Message],
    ) -> AgentReply:
        route_entry = self.routes.get(route)
        if route_entry is None:
            raise AgentCallError(f"unknown route: {route}")
        agent_url = (
            route_entry.get("address") if isinstance(route_entry, dict) else route_entry
        )
        if not agent_url:
            raise AgentCallError(f"route {route} has no address")
        return await self._agent_client.send_turn(
            agent_url,
            text=event.text,
            thread_id=event.thread_id or event.scope_id,
            history=history,
            metadata=event.metadata,
        )

    async def handle_event(self, raw_event: Any) -> None:
        try:
            event = self.parse_event(raw_event)
        except SkipEvent:
            return
        if not await self.authorize(event):
            return
        route = await self.resolve_route(event)
        if route is None:
            await self.on_no_route(event)
            return
        history = await self.fetch_history(event)
        await self.before_call(event, route)
        try:
            reply = await self.call_agent(event, route, history)
        except AgentCallError as exc:
            await self.on_agent_error(event, route, exc)
            return
        await self.post_reply(event, route, reply)
        await self.after_reply(event, route, reply)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest packages/python/vystak-channel-runtime/tests/test_runtime.py -v`
Expected: all tests PASSED (~15 tests by now).

- [ ] **Step 5: Re-export `ChannelRuntime`**

Edit `__init__.py`:

```python
from vystak_channel_runtime.runtime import ChannelRuntime
```

Add `"ChannelRuntime"` to `__all__`.

- [ ] **Step 6: Commit**

```bash
git add packages/python/vystak-channel-runtime/
git commit -m "feat(channel-runtime): add call_agent + handle_event template-method pipeline"
```

---

### Task 1.11: `launch()` helper

**Files:**
- Create: `packages/python/vystak-channel-runtime/src/vystak_channel_runtime/launcher.py`
- Create: `packages/python/vystak-channel-runtime/tests/test_launcher.py`

- [ ] **Step 1: Write the failing test**

Create `packages/python/vystak-channel-runtime/tests/test_launcher.py`:

```python
"""Tests for vystak_channel_runtime.launcher."""

import pytest
from vystak.schema.common import ChannelType
from vystak_channel_runtime.launcher import build_runtime
from vystak_channel_runtime.runtime import ChannelRuntime
from vystak_channel_runtime.store import MemoryChannelStore, SqliteChannelStore
from vystak_channel_runtime.types import AgentReply, InboundEvent


class _Trivial(ChannelRuntime):
    async def start(self): pass
    async def stop(self): pass
    def parse_event(self, raw): return InboundEvent(
        channel_type=ChannelType.SLACK, scope_id="x", thread_id=None,
        user_id="U", text="hi", is_dm=False, mentions_bot=True,
    )
    async def post_reply(self, e, r, reply): pass


def test_build_runtime_with_no_state_returns_memory_store():
    rt = build_runtime(_Trivial, config={"channel_type": "slack"}, routes={})
    assert isinstance(rt, _Trivial)
    assert isinstance(rt.store, MemoryChannelStore)


def test_build_runtime_with_sqlite_state(tmp_path):
    cfg = {
        "channel_type": "slack",
        "state": {"type": "sqlite", "path": str(tmp_path / "x.db")},
    }
    rt = build_runtime(_Trivial, config=cfg, routes={})
    assert isinstance(rt.store, SqliteChannelStore)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/python/vystak-channel-runtime/tests/test_launcher.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement `launcher.py`**

Create `packages/python/vystak-channel-runtime/src/vystak_channel_runtime/launcher.py`:

```python
"""Launcher helpers for channel containers' __main__.py entrypoints."""

from __future__ import annotations

import asyncio
import logging
import os
import signal

from vystak_channel_runtime.runtime import ChannelRuntime
from vystak_channel_runtime.store import make_channel_store


def build_runtime(
    runtime_cls: type[ChannelRuntime],
    config: dict,
    routes: dict,
) -> ChannelRuntime:
    """Construct a ChannelRuntime from configs (no I/O loop)."""
    store = make_channel_store(config.get("state"))
    return runtime_cls(config=config, routes=routes, store=store)


def launch(
    runtime_cls: type[ChannelRuntime],
    config: dict,
    routes: dict,
) -> None:
    """Build the runtime and run its event loop until SIGTERM/SIGINT."""
    logging.basicConfig(
        level=os.environ.get("VYSTAK_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    rt = build_runtime(runtime_cls, config=config, routes=routes)
    asyncio.run(_run(rt))


async def _run(rt: ChannelRuntime) -> None:
    stop_event = asyncio.Event()

    def _stop(*_):
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _stop)
        except NotImplementedError:
            # Windows / non-main-thread fallback.
            pass

    starter = asyncio.create_task(rt.start())
    waiter = asyncio.create_task(stop_event.wait())
    done, pending = await asyncio.wait(
        {starter, waiter}, return_when=asyncio.FIRST_COMPLETED,
    )
    for t in pending:
        t.cancel()
    await rt.stop()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest packages/python/vystak-channel-runtime/tests/test_launcher.py -v`
Expected: 2 PASSED.

- [ ] **Step 5: Re-export**

Edit `__init__.py`:

```python
from vystak_channel_runtime.launcher import build_runtime, launch
```

Add `"build_runtime", "launch"` to `__all__`.

- [ ] **Step 6: Commit**

```bash
git add packages/python/vystak-channel-runtime/
git commit -m "feat(channel-runtime): add launch() + build_runtime helpers"
```

---

### Task 1.12: `/test/event` synthetic-dispatch endpoint

**Files:**
- Create: `packages/python/vystak-channel-runtime/src/vystak_channel_runtime/test_endpoint.py`
- Create: `packages/python/vystak-channel-runtime/tests/test_test_endpoint.py`

- [ ] **Step 1: Write the failing test**

Create `packages/python/vystak-channel-runtime/tests/test_test_endpoint.py`:

```python
"""Tests for the /test/event synthetic dispatch endpoint."""

import pytest
from fastapi.testclient import TestClient
from vystak.schema.common import ChannelType
from vystak_channel_runtime.runtime import ChannelRuntime
from vystak_channel_runtime.store import MemoryChannelStore
from vystak_channel_runtime.test_endpoint import build_test_app
from vystak_channel_runtime.types import InboundEvent, AgentReply


class CapturingRuntime(ChannelRuntime):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.handled = []

    async def start(self): pass
    async def stop(self): pass

    def parse_event(self, raw):
        return InboundEvent(**raw)

    async def post_reply(self, e, r, reply):
        self.handled.append((e.scope_id, r, reply.text))


def test_test_endpoint_dispatches(monkeypatch):
    rt = CapturingRuntime(
        config={
            "channel_type": "slack",
            "agent_protocol": "a2a-turn",
            "default_agent": "hero",
            "group_policy": "open",
            "dm_policy": "open",
        },
        routes={"hero": {"address": "http://hero:8000"}},
        store=MemoryChannelStore(),
    )

    class _FakeAgent:
        async def send_turn(self, *a, **kw):
            return AgentReply(text="ok")
        async def stream_turn(self, *a, **kw):
            raise NotImplementedError

    rt._agent_client = _FakeAgent()
    app = build_test_app(rt)
    client = TestClient(app)
    resp = client.post(
        "/test/event",
        json={
            "channel_type": ChannelType.SLACK.value,
            "scope_id": "C1",
            "thread_id": None,
            "user_id": "U",
            "text": "hi",
            "is_dm": False,
            "mentions_bot": True,
            "metadata": {},
        },
    )
    assert resp.status_code == 200
    assert rt.handled == [("C1", "hero", "ok")]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/python/vystak-channel-runtime/tests/test_test_endpoint.py -v`
Expected: ImportError on `vystak_channel_runtime.test_endpoint`.

- [ ] **Step 3: Add `fastapi` to runtime deps**

Edit `packages/python/vystak-channel-runtime/pyproject.toml` and append to `dependencies`:

```toml
    "fastapi>=0.110",
```

Run `uv sync`.

- [ ] **Step 4: Implement `test_endpoint.py`**

Create `packages/python/vystak-channel-runtime/src/vystak_channel_runtime/test_endpoint.py`:

```python
"""Synthetic event dispatch endpoint — gated by VYSTAK_TEST_EVENTS env var."""

from __future__ import annotations

import os

from fastapi import FastAPI

from vystak_channel_runtime.runtime import ChannelRuntime
from vystak_channel_runtime.types import InboundEvent


def is_test_endpoint_enabled() -> bool:
    return os.environ.get("VYSTAK_TEST_EVENTS") == "1"


def build_test_app(runtime: ChannelRuntime) -> FastAPI:
    """Build a small FastAPI app exposing /test/event for synthetic dispatch."""
    app = FastAPI(title="vystak-channel-runtime test endpoint")

    @app.post("/test/event")
    async def post_event(event: InboundEvent) -> dict:
        await runtime.handle_event(event.model_dump())
        return {"status": "dispatched"}

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    return app
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest packages/python/vystak-channel-runtime/tests/test_test_endpoint.py -v`
Expected: 1 PASSED.

- [ ] **Step 6: Re-export**

Edit `__init__.py`:

```python
from vystak_channel_runtime.test_endpoint import build_test_app, is_test_endpoint_enabled
```

Add `"build_test_app", "is_test_endpoint_enabled"` to `__all__`.

- [ ] **Step 7: Commit**

```bash
git add packages/python/vystak-channel-runtime/
git commit -m "feat(channel-runtime): add /test/event synthetic dispatch endpoint (gated)"
```

---

### Task 1.13: Phase 1 wrap — full-suite runtime test

**Files:**
- Test: existing test files

- [ ] **Step 1: Run the full runtime lib test suite**

```bash
uv run pytest packages/python/vystak-channel-runtime/ -v
```

Expected: all tests PASS (excluding `-m docker` ones unless Postgres is up).

- [ ] **Step 2: Lint + format**

```bash
uv run ruff check packages/python/vystak-channel-runtime/
uv run ruff format packages/python/vystak-channel-runtime/
```

Expected: clean.

- [ ] **Step 3: Smoke import everything from `__init__`**

```bash
uv run python -c "from vystak_channel_runtime import (
    AgentCallError, AgentChunk, AgentClient, AgentReply, A2AAgentClient,
    ChannelRuntime, ChannelStore, InboundEvent, Message, MemoryChannelStore,
    PostgresChannelStore, SqliteChannelStore, ThreadBinding, SkipEvent,
    build_runtime, launch, build_test_app, is_test_endpoint_enabled,
    make_channel_store,
); print('all imports ok')"
```

Expected: prints `all imports ok`.

- [ ] **Step 4: Commit (only if anything changed; otherwise skip)**

```bash
git status
# If nothing to commit, skip.
git add -p packages/python/vystak-channel-runtime/
git commit -m "test(channel-runtime): phase 1 wrap — verify imports and lint clean"
```

---

## Phase 2: Slack retrofit (behavior-preserving)

> **Gate for entire phase:** the existing Slack test suite (`uv run pytest packages/python/vystak-channel-slack -v`) stays green. Existing Slack `tests/release/` cells stay green when run with credentials.

### Task 2.1: Add `vystak-channel-runtime` dep to Slack package

**Files:**
- Modify: `packages/python/vystak-channel-slack/pyproject.toml`

- [ ] **Step 1: Add the dependency**

Edit `packages/python/vystak-channel-slack/pyproject.toml`. Inside `[project] dependencies`, append:

```toml
    "vystak-channel-runtime>=0.1.0",
```

And inside `[tool.uv.sources]` add:

```toml
vystak-channel-runtime = { workspace = true }
```

- [ ] **Step 2: Resync workspace**

```bash
uv sync
```

Expected: success.

- [ ] **Step 3: Smoke import inside Slack package context**

```bash
uv run python -c "import vystak_channel_slack; from vystak_channel_runtime import ChannelRuntime; print('ok')"
```

Expected: prints `ok`.

- [ ] **Step 4: Commit**

```bash
git add packages/python/vystak-channel-slack/pyproject.toml uv.lock
git commit -m "chore(channel-slack): depend on vystak-channel-runtime"
```

---

### Task 2.2: Create `SlackChannelRuntime` skeleton (start/stop only)

**Files:**
- Create: `packages/python/vystak-channel-slack/src/vystak_channel_slack/runtime.py`
- Create: `packages/python/vystak-channel-slack/tests/test_runtime.py`

> **Note:** Slack's existing `server_template.py` builds a `slack_bolt.async_app.AsyncApp` and registers `app.event("message")` / `app.event("app_mention")` / `app.command("/vystak")` handlers, then runs `AsyncSocketModeHandler(app, app_token).start_async()`. The new `SlackChannelRuntime.start()` does the same construction but dispatches into `handle_event()` instead of running ad-hoc routing code in the event handler bodies.

- [ ] **Step 1: Write the failing test**

Create `packages/python/vystak-channel-slack/tests/test_runtime.py`:

```python
"""Tests for SlackChannelRuntime."""

import pytest
from vystak_channel_runtime.store import MemoryChannelStore
from vystak_channel_slack.runtime import SlackChannelRuntime


def _config():
    return {
        "channel_type": "slack",
        "agent_protocol": "a2a-turn",
        "agents": ["hero"],
        "default_agent": "hero",
        "group_policy": "open",
        "dm_policy": "open",
        "allow_from": [],
        "allow_bots": False,
        "channel_overrides": {},
    }


def test_runtime_constructable():
    rt = SlackChannelRuntime(
        config=_config(),
        routes={"hero": {"address": "http://hero:8000"}},
        store=MemoryChannelStore(),
    )
    assert rt.channel_type == "slack"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest packages/python/vystak-channel-slack/tests/test_runtime.py -v
```

Expected: ImportError on `vystak_channel_slack.runtime`.

- [ ] **Step 3: Implement `runtime.py` skeleton**

Create `packages/python/vystak-channel-slack/src/vystak_channel_slack/runtime.py`:

```python
"""SlackChannelRuntime — runs a slack-bolt Socket Mode handler dispatching to ChannelRuntime."""

from __future__ import annotations

import logging
import os
from typing import Any

from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from slack_bolt.async_app import AsyncApp

from vystak_channel_runtime.runtime import ChannelRuntime
from vystak_channel_runtime.types import (
    AgentReply,
    InboundEvent,
    SkipEvent,
)

logger = logging.getLogger("vystak.channel.slack")


class SlackChannelRuntime(ChannelRuntime):
    """Slack Socket Mode runtime."""

    def __init__(self, **kw: Any) -> None:
        super().__init__(**kw)
        self._bot_token: str | None = None
        self._app_token: str | None = None
        self._app: AsyncApp | None = None
        self._handler: AsyncSocketModeHandler | None = None

    async def start(self) -> None:
        self._bot_token = os.environ["SLACK_BOT_TOKEN"]
        self._app_token = os.environ["SLACK_APP_TOKEN"]
        self._app = AsyncApp(token=self._bot_token)

        @self._app.event("message")
        async def _on_message(event, say):  # noqa: ARG001
            await self.handle_event({"type": "message", "event": event, "say": say})

        @self._app.event("app_mention")
        async def _on_mention(event, say):  # noqa: ARG001
            await self.handle_event({"type": "app_mention", "event": event, "say": say})

        self._handler = AsyncSocketModeHandler(self._app, self._app_token)
        await self._handler.start_async()

    async def stop(self) -> None:
        if self._handler is not None:
            await self._handler.close_async()

    def parse_event(self, raw_event: Any) -> InboundEvent:
        # Real implementation in Task 2.3
        raise SkipEvent("not implemented yet")

    async def post_reply(
        self, event: InboundEvent, route: str, reply: AgentReply
    ) -> None:
        # Real implementation in Task 2.4
        raise NotImplementedError
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest packages/python/vystak-channel-slack/tests/test_runtime.py::test_runtime_constructable -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-channel-slack/src/vystak_channel_slack/runtime.py packages/python/vystak-channel-slack/tests/test_runtime.py
git commit -m "feat(channel-slack): scaffold SlackChannelRuntime (lifecycle only)"
```

---

### Task 2.3: Implement `SlackChannelRuntime.parse_event`

**Files:**
- Modify: `packages/python/vystak-channel-slack/src/vystak_channel_slack/runtime.py`
- Modify: `packages/python/vystak-channel-slack/tests/test_runtime.py`

> **Note:** existing Slack `server_template.py` builds an `Event` dataclass with `team`, `channel`, `user`, `text`, `is_dm`, `is_bot`, `channel_name`. This task transforms a Slack Bolt event payload into the runtime's `InboundEvent`. Slack's `scope_id` is `team_id` (per spec); `thread_id` is the existing `f"{channel_id}:{thread_ts}"` format Slack already uses.

- [ ] **Step 1: Add the failing test**

Append to `packages/python/vystak-channel-slack/tests/test_runtime.py`:

```python
from vystak.schema.common import ChannelType


def _bolt_event(text="hi <@U_BOT>", channel_type="channel", thread_ts=None, bot_id=None):
    return {
        "type": "message",
        "channel": "C1",
        "user": "U_USER",
        "text": text,
        "ts": "1.0",
        "team": "T1",
        "channel_type": channel_type,
        **({"thread_ts": thread_ts} if thread_ts else {}),
        **({"bot_id": bot_id} if bot_id else {}),
    }


def test_parse_event_app_mention():
    rt = SlackChannelRuntime(
        config=_config(),
        routes={"hero": {"address": "http://hero:8000"}},
        store=MemoryChannelStore(),
    )
    rt._bot_user_id = "U_BOT"
    raw = {"type": "app_mention", "event": _bolt_event(), "say": None}
    ev = rt.parse_event(raw)
    assert ev.channel_type == ChannelType.SLACK
    assert ev.scope_id == "T1"
    assert ev.thread_id == "C1:1.0"
    assert ev.user_id == "U_USER"
    assert ev.is_dm is False
    assert ev.mentions_bot is True


def test_parse_event_dm():
    rt = SlackChannelRuntime(
        config=_config(),
        routes={"hero": {"address": "http://hero:8000"}},
        store=MemoryChannelStore(),
    )
    rt._bot_user_id = "U_BOT"
    raw = {"type": "message", "event": _bolt_event(text="hello", channel_type="im"), "say": None}
    ev = rt.parse_event(raw)
    assert ev.is_dm is True
    assert ev.mentions_bot is False


def test_parse_event_thread_reply_keeps_root_thread_id():
    rt = SlackChannelRuntime(
        config=_config(),
        routes={"hero": {"address": "http://hero:8000"}},
        store=MemoryChannelStore(),
    )
    rt._bot_user_id = "U_BOT"
    raw = {"type": "message", "event": _bolt_event(thread_ts="1.0"), "say": None}
    ev = rt.parse_event(raw)
    assert ev.thread_id == "C1:1.0"


def test_parse_event_bot_marked_in_metadata():
    rt = SlackChannelRuntime(
        config=_config(),
        routes={"hero": {"address": "http://hero:8000"}},
        store=MemoryChannelStore(),
    )
    rt._bot_user_id = "U_BOT"
    raw = {"type": "message", "event": _bolt_event(bot_id="B1"), "say": None}
    ev = rt.parse_event(raw)
    assert ev.metadata.get("is_bot") is True


def test_parse_event_skips_own_message():
    rt = SlackChannelRuntime(
        config=_config(),
        routes={"hero": {"address": "http://hero:8000"}},
        store=MemoryChannelStore(),
    )
    rt._bot_user_id = "U_BOT"
    raw = {"type": "message", "event": {**_bolt_event(), "user": "U_BOT"}, "say": None}
    from vystak_channel_runtime.types import SkipEvent
    with pytest.raises(SkipEvent):
        rt.parse_event(raw)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest packages/python/vystak-channel-slack/tests/test_runtime.py -v -k parse_event
```

Expected: failures (parse_event still raises SkipEvent unconditionally).

- [ ] **Step 3: Implement `parse_event` (replace placeholder in `runtime.py`)**

Replace the `parse_event` method body in `runtime.py`:

```python
    def parse_event(self, raw_event: Any) -> InboundEvent:
        kind = raw_event.get("type")
        ev = raw_event["event"]
        say = raw_event.get("say")

        # Skip our own messages and subtype-noisy events.
        if ev.get("user") == getattr(self, "_bot_user_id", None):
            raise SkipEvent("own message")
        subtype = ev.get("subtype")
        if subtype in {"message_changed", "message_deleted", "channel_join"}:
            raise SkipEvent(f"subtype {subtype}")

        team_id = ev.get("team") or ""
        channel_id = ev.get("channel", "")
        thread_ts = ev.get("thread_ts") or ev.get("ts") or ""
        is_dm = ev.get("channel_type") == "im"
        mentions_bot = (
            kind == "app_mention"
            or f"<@{getattr(self, '_bot_user_id', '')}>" in (ev.get("text") or "")
        )
        is_bot = bool(ev.get("bot_id"))

        metadata = {
            "channel_id": channel_id,
            "channel_name": ev.get("channel_name"),
            "ts": ev.get("ts"),
            "thread_ts": ev.get("thread_ts"),
            "is_bot": is_bot,
            "say": say,
            "kind": kind,
        }

        return InboundEvent(
            channel_type=__import__(
                "vystak.schema.common", fromlist=["ChannelType"]
            ).ChannelType.SLACK,
            scope_id=team_id,
            thread_id=f"{channel_id}:{thread_ts}",
            user_id=ev.get("user", ""),
            text=ev.get("text", ""),
            is_dm=is_dm,
            mentions_bot=mentions_bot,
            metadata=metadata,
            raw=raw_event,
        )
```

(Tidy import: at the top of `runtime.py`, replace the `__import__` shim by adding `from vystak.schema.common import ChannelType` and changing `__import__(...).ChannelType.SLACK` to `ChannelType.SLACK`.)

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest packages/python/vystak-channel-slack/tests/test_runtime.py -v -k parse_event
```

Expected: 5 PASSED.

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-channel-slack/
git commit -m "feat(channel-slack): implement SlackChannelRuntime.parse_event"
```

---

### Task 2.4: Implement `SlackChannelRuntime.post_reply` and `fetch_history`

**Files:**
- Modify: `packages/python/vystak-channel-slack/src/vystak_channel_slack/runtime.py`
- Modify: `packages/python/vystak-channel-slack/tests/test_runtime.py`

- [ ] **Step 1: Add the failing test**

Append to `tests/test_runtime.py`:

```python
class _FakeSay:
    def __init__(self):
        self.calls = []

    async def __call__(self, **kwargs):
        self.calls.append(kwargs)


@pytest.mark.asyncio
async def test_post_reply_uses_say_with_thread_ts():
    say = _FakeSay()
    rt = SlackChannelRuntime(
        config=_config(),
        routes={"hero": {"address": "http://hero:8000"}},
        store=MemoryChannelStore(),
    )
    rt._bot_user_id = "U_BOT"
    raw = {"type": "app_mention", "event": _bolt_event(thread_ts="1.0"), "say": say}
    ev = rt.parse_event(raw)
    await rt.post_reply(ev, "hero", AgentReply(text="hello back"))
    assert len(say.calls) == 1
    assert say.calls[0]["text"] == "hello back"
    assert say.calls[0]["thread_ts"] == "1.0"


@pytest.mark.asyncio
async def test_fetch_history_returns_empty_when_no_thread_ts(monkeypatch):
    rt = SlackChannelRuntime(
        config=_config(),
        routes={"hero": {"address": "http://hero:8000"}},
        store=MemoryChannelStore(),
    )
    rt._bot_user_id = "U_BOT"
    raw = {"type": "message", "event": _bolt_event(channel_type="im"), "say": None}
    ev = rt.parse_event(raw)
    history = await rt.fetch_history(ev)
    assert history == []
```

(Add at the top: `from vystak_channel_runtime.types import AgentReply`.)

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest packages/python/vystak-channel-slack/tests/test_runtime.py -v -k "post_reply or fetch_history"
```

Expected: failure (`post_reply` still NotImplementedError).

- [ ] **Step 3: Implement `post_reply` and `fetch_history`**

In `runtime.py`, replace `post_reply` and add `fetch_history`:

```python
    async def post_reply(
        self, event: InboundEvent, route: str, reply: AgentReply
    ) -> None:
        say = event.metadata.get("say")
        if say is None:
            logger.warning("no `say` callable in event metadata; cannot post reply")
            return
        thread_ts = event.metadata.get("thread_ts") or event.metadata.get("ts")
        kwargs: dict[str, Any] = {"text": reply.text}
        if thread_ts:
            kwargs["thread_ts"] = thread_ts
        await say(**kwargs)

    async def fetch_history(self, event: InboundEvent) -> list[Message]:
        from vystak_channel_runtime.types import Message
        thread_ts = event.metadata.get("thread_ts")
        channel_id = event.metadata.get("channel_id")
        if not thread_ts or not channel_id or self._app is None:
            return []
        try:
            client = self._app.client
            limit = (
                self.config.get("thread", {}).get("initial_history_limit", 20)
            )
            resp = await client.conversations_replies(
                channel=channel_id, ts=thread_ts, limit=limit,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("conversations.replies failed: %s", exc)
            return []
        out: list[Message] = []
        bot_user_id = getattr(self, "_bot_user_id", None)
        for msg in resp.get("messages", [])[:-1]:  # exclude the trigger msg itself
            role = "assistant" if msg.get("user") == bot_user_id else "user"
            out.append(Message(role=role, content=msg.get("text", "")))
        return out
```

(Add `from vystak_channel_runtime.types import Message` to module imports, dropping the inline import.)

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest packages/python/vystak-channel-slack/tests/test_runtime.py -v -k "post_reply or fetch_history"
```

Expected: 2 PASSED.

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-channel-slack/
git commit -m "feat(channel-slack): implement post_reply + fetch_history hooks"
```

---

### Task 2.5: Migrate Slack-specific store helpers (`inviters.py`)

**Files:**
- Create: `packages/python/vystak-channel-slack/src/vystak_channel_slack/inviters.py`
- Create: `packages/python/vystak-channel-slack/tests/test_inviters.py`

> **Note:** existing Slack `store.py` includes `record_inviter()` and `inviter()` methods that don't fit the generic `ChannelStore` shape. They get a thin Slack-only helper backed by a small Slack-only SQLite/Postgres table, layered on top of the same connection or DSN.

- [ ] **Step 1: Write the failing test**

Create `packages/python/vystak-channel-slack/tests/test_inviters.py`:

```python
"""Tests for the Slack-only inviter helper."""

import pytest

from vystak_channel_slack.inviters import InviterStore


@pytest.mark.asyncio
async def test_inviter_round_trip(tmp_path):
    s = InviterStore(str(tmp_path / "inv.db"))
    assert await s.get_inviter("T1", "C1") is None
    await s.record_inviter("T1", "C1", "U_INVITER")
    assert await s.get_inviter("T1", "C1") == "U_INVITER"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest packages/python/vystak-channel-slack/tests/test_inviters.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement `inviters.py`**

Create `packages/python/vystak-channel-slack/src/vystak_channel_slack/inviters.py`:

```python
"""Slack-only inviter tracking — one row per (team, channel)."""

from __future__ import annotations

import aiosqlite

_DDL = """
CREATE TABLE IF NOT EXISTS slack_inviters (
    team_id    TEXT NOT NULL,
    channel_id TEXT NOT NULL,
    user_id    TEXT NOT NULL,
    PRIMARY KEY (team_id, channel_id)
);
"""


class InviterStore:
    """Stores who first invited the bot into a channel."""

    def __init__(self, path: str) -> None:
        self._path = path

    async def _ensure(self) -> aiosqlite.Connection:
        conn = await aiosqlite.connect(self._path)
        await conn.execute(_DDL)
        await conn.commit()
        return conn

    async def get_inviter(self, team_id: str, channel_id: str) -> str | None:
        conn = await self._ensure()
        try:
            cur = await conn.execute(
                "SELECT user_id FROM slack_inviters WHERE team_id=? AND channel_id=?",
                (team_id, channel_id),
            )
            row = await cur.fetchone()
            return row[0] if row else None
        finally:
            await conn.close()

    async def record_inviter(self, team_id: str, channel_id: str, user_id: str) -> None:
        conn = await self._ensure()
        try:
            await conn.execute(
                """
                INSERT INTO slack_inviters (team_id, channel_id, user_id)
                VALUES (?, ?, ?)
                ON CONFLICT(team_id, channel_id) DO UPDATE SET user_id=excluded.user_id
                """,
                (team_id, channel_id, user_id),
            )
            await conn.commit()
        finally:
            await conn.close()
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest packages/python/vystak-channel-slack/tests/test_inviters.py -v
```

Expected: 1 PASSED.

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-channel-slack/src/vystak_channel_slack/inviters.py packages/python/vystak-channel-slack/tests/test_inviters.py
git commit -m "feat(channel-slack): split Slack-only inviter tracking into inviters.py"
```

---

### Task 2.6: Wire welcome / commands / threads through `SlackChannelRuntime` hooks

**Files:**
- Modify: `packages/python/vystak-channel-slack/src/vystak_channel_slack/runtime.py`
- Modify: `packages/python/vystak-channel-slack/src/vystak_channel_slack/welcome.py`
- Modify: `packages/python/vystak-channel-slack/src/vystak_channel_slack/commands.py`
- Modify: `packages/python/vystak-channel-slack/src/vystak_channel_slack/threads.py`

> **Note:** existing `welcome.py`/`commands.py`/`threads.py` modules currently import `RoutesStore` from the deleted `store.py`. They need to be updated to take a `ChannelStore` instance instead. Each existing test for these modules should keep passing after the swap.

- [ ] **Step 1: Read existing usages of `RoutesStore` in welcome/commands/threads**

```bash
grep -n "RoutesStore\|from vystak_channel_slack.store" packages/python/vystak-channel-slack/src/vystak_channel_slack/welcome.py packages/python/vystak-channel-slack/src/vystak_channel_slack/commands.py packages/python/vystak-channel-slack/src/vystak_channel_slack/threads.py
```

Note every call site that touches `channel_binding`/`set_channel_binding`/`thread_binding`/etc.

- [ ] **Step 2: Mechanically rename store calls to the ChannelStore API**

The existing-store API → new-store API mapping:

| Old (`RoutesStore`)                                | New (`ChannelStore`)                                                                |
|----------------------------------------------------|-------------------------------------------------------------------------------------|
| `store.channel_binding(team, channel)`             | `await store.get_thread_binding("slack", team, f"{channel}:")` *(see note)*         |
| `store.set_channel_binding(team, channel, agent, inviter)` | `await store.set_thread_binding("slack", team, f"{channel}:", agent)`             |
| `store.unbind_channel(team, channel)`              | `await store.delete_thread_binding("slack", team, f"{channel}:")`                   |
| `store.thread_binding(team, channel, ts)`          | `await store.get_thread_binding("slack", team, f"{channel}:{ts}")`                  |
| `store.set_thread_binding(team, channel, ts, agent)` | `await store.set_thread_binding("slack", team, f"{channel}:{ts}", agent)`          |
| `store.unbind_thread(team, channel, ts)`           | `await store.delete_thread_binding("slack", team, f"{channel}:{ts}")`               |
| `store.user_pref(team, user)`                      | `await store.get_route_pref("slack", f"{team}:{user}")`                             |
| `store.set_user_pref(team, user, agent)`           | `await store.set_route_pref("slack", f"{team}:{user}", agent)`                      |
| `store.unset_user_pref(team, user)`                | `await store.delete_route_pref("slack", f"{team}:{user}")`                          |
| `store.record_inviter(team, channel, user)`        | `await inviters.record_inviter(team, channel, user)`                                |
| `store.inviter(team, channel)`                     | `await inviters.get_inviter(team, channel)`                                         |

**Channel-binding convention:** Slack's "bind THIS CHANNEL to agent X" lives at the same `thread_bindings` table with `thread_id = f"{channel_id}:"` (trailing colon, no thread_ts). This is a deliberate convention so that thread-binding lookups for messages in a thread fall back to channel binding when the per-thread row is absent.

- [ ] **Step 3: Update `welcome.py` signatures**

For every function in `welcome.py` that takes `store: RoutesStore`, change the type annotation to `store: ChannelStore` and add `inviters: InviterStore | None = None` where the function calls `record_inviter`/`inviter`. Update internal call sites per the table above.

- [ ] **Step 4: Update `commands.py` signatures**

Same exercise for `commands.py`. The `/vystak route|prefer|status|unroute|unprefer` handlers all take a `store` argument; swap to `ChannelStore` API.

- [ ] **Step 5: Update `threads.py` signatures**

Same for `threads.py`. The `route_thread_message` policy function takes `store`; swap.

- [ ] **Step 6: Wire welcome/commands/threads into `SlackChannelRuntime.start`**

Inside `SlackChannelRuntime.start()`, after creating `self._app`, register the existing event handlers and slash command using the new module signatures:

```python
        from vystak_channel_slack import commands, threads, welcome
        from vystak_channel_slack.inviters import InviterStore

        # Persist the inviter store separately for Slack-only inviter tracking.
        inviter_path = self.config.get("state", {}).get("path", "/data/channel.db")
        self._inviters = InviterStore(inviter_path)

        welcome.register(self._app, self.config, self.store, self._inviters)
        commands.register(self._app, self.config, self.store)
        threads.register(self._app, self.config, self.store)
```

(Each module's `register(app, config, store, ...)` function wires the bolt event/command handlers and shares the `ChannelStore` instance with the runtime. Test that registration is idempotent if called more than once during dev reloads.)

- [ ] **Step 7: Run the full Slack test suite**

```bash
uv run pytest packages/python/vystak-channel-slack/ -v
```

Expected: all PASS. Failures here mean the rename broke a test — fix in place, do not change behavior.

- [ ] **Step 8: Commit**

```bash
git add packages/python/vystak-channel-slack/
git commit -m "refactor(channel-slack): wire welcome/commands/threads through ChannelStore"
```

---

### Task 2.7: Delete `resolver.py` + `store.py`; re-point existing tests

**Files:**
- Delete: `packages/python/vystak-channel-slack/src/vystak_channel_slack/resolver.py`
- Delete: `packages/python/vystak-channel-slack/src/vystak_channel_slack/store.py`
- Modify: `packages/python/vystak-channel-slack/tests/test_resolver.py`
- Modify: `packages/python/vystak-channel-slack/tests/test_store.py`

- [ ] **Step 1: Confirm `resolver.py`'s only callers are deleted/migrated**

```bash
grep -rn "from vystak_channel_slack.resolver\|from vystak_channel_slack import resolver\|resolver.resolve" packages/python/vystak-channel-slack/
```

Any remaining production imports must already be the dispatch into `ChannelRuntime.resolve_route` from Task 1.9. Test imports should be re-pointed in step 3.

- [ ] **Step 2: Confirm `store.py`'s only callers are migrated**

```bash
grep -rn "from vystak_channel_slack.store\|from vystak_channel_slack import store\|RoutesStore\|SqliteStore\|PostgresStore" packages/python/vystak-channel-slack/
```

Should be empty in `src/` (all callers swapped to `ChannelStore` in Task 2.6). Test references handled in step 3.

- [ ] **Step 3: Re-point `tests/test_resolver.py`**

Open `tests/test_resolver.py`. The existing tests build a `ResolverConfig` dataclass and call `resolve(event, cfg, store)`. Replace with tests that exercise the same logic via `ChannelRuntime.resolve_route`. Concretely:

Replace the entire file with:

```python
"""Slack routing tests — now exercised via ChannelRuntime.resolve_route()."""

import pytest
from vystak.schema.common import ChannelType
from vystak_channel_runtime.runtime import ChannelRuntime
from vystak_channel_runtime.store import MemoryChannelStore
from vystak_channel_runtime.types import (
    AgentReply,
    InboundEvent,
)


class _TrivSlack(ChannelRuntime):
    async def start(self): pass
    async def stop(self): pass
    def parse_event(self, raw): raise NotImplementedError
    async def post_reply(self, e, r, reply): pass


def _ev(scope_id="T1", thread_id=None, user_id="U", is_dm=False):
    return InboundEvent(
        channel_type=ChannelType.SLACK, scope_id=scope_id, thread_id=thread_id,
        user_id=user_id, text="hi", is_dm=is_dm, mentions_bot=True,
    )


def _cfg(**overrides):
    base = {
        "channel_type": "slack",
        "agent_protocol": "a2a-turn",
        "agents": ["hero"],
        "default_agent": "hero",
        "group_policy": "open",
        "dm_policy": "open",
        "allow_from": [],
        "allow_bots": False,
        "channel_overrides": {},
    }
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_resolve_uses_channel_override():
    rt = _TrivSlack(
        config=_cfg(channel_overrides={"T1": {"agent": "villain"}}),
        routes={}, store=MemoryChannelStore(),
    )
    assert await rt.resolve_route(_ev()) == "villain"


@pytest.mark.asyncio
async def test_resolve_falls_back_to_default():
    rt = _TrivSlack(
        config=_cfg(),
        routes={}, store=MemoryChannelStore(),
    )
    assert await rt.resolve_route(_ev()) == "hero"
```

- [ ] **Step 4: Re-point `tests/test_store.py`**

Replace the content of `tests/test_store.py` with delegation to runtime store + Slack-specific inviter tests:

```python
"""Slack store tests — generic ChannelStore tests live in vystak-channel-runtime;
this file only covers Slack-specific inviter tracking."""

import pytest

from vystak_channel_slack.inviters import InviterStore


@pytest.mark.asyncio
async def test_inviter_record_then_retrieve(tmp_path):
    s = InviterStore(str(tmp_path / "inv.db"))
    await s.record_inviter("T1", "C1", "U_INV")
    assert await s.get_inviter("T1", "C1") == "U_INV"


@pytest.mark.asyncio
async def test_inviter_returns_none_when_absent(tmp_path):
    s = InviterStore(str(tmp_path / "inv.db"))
    assert await s.get_inviter("T1", "C1") is None
```

- [ ] **Step 5: Delete `resolver.py` and `store.py`**

```bash
git rm packages/python/vystak-channel-slack/src/vystak_channel_slack/resolver.py
git rm packages/python/vystak-channel-slack/src/vystak_channel_slack/store.py
```

- [ ] **Step 6: Run the full Slack test suite**

```bash
uv run pytest packages/python/vystak-channel-slack/ -v
```

Expected: all tests pass. If a previously-passing test now fails, treat as a retrofit bug.

- [ ] **Step 7: Lint**

```bash
uv run ruff check packages/python/vystak-channel-slack/
```

Expected: clean.

- [ ] **Step 8: Commit**

```bash
git add packages/python/vystak-channel-slack/
git commit -m "refactor(channel-slack): delete resolver.py + store.py (logic moved to channel-runtime)"
```

---

### Task 2.8: Slack `__main__.py` + plugin emits configs+Dockerfile only

**Files:**
- Create: `packages/python/vystak-channel-slack/src/vystak_channel_slack/__main__.py`
- Modify: `packages/python/vystak-channel-slack/src/vystak_channel_slack/server_template.py`
- Modify: `packages/python/vystak-channel-slack/src/vystak_channel_slack/plugin.py`
- Modify: `packages/python/vystak-channel-slack/tests/test_plugin.py`

- [ ] **Step 1: Add the failing plugin test**

Append to (or create) `tests/test_plugin.py`:

```python
"""Tests for the Slack channel plugin's no-codegen output shape."""

from vystak.schema.channel import Channel
from vystak.schema.common import ChannelType
from vystak.schema.platform import Platform

from vystak_channel_slack.plugin import SlackChannelPlugin


def _channel():
    return Channel(
        name="slack-prod",
        type=ChannelType.SLACK,
        agents=[],
        default_agent=None,
        group_policy="open",
        dm_policy="open",
        allow_from=[],
        allow_bots=False,
        channel_overrides={},
    )


def test_plugin_emits_no_python_source():
    plugin = SlackChannelPlugin()
    out = plugin.generate_code(_channel(), resolved_routes={})
    for path in out.files:
        assert not path.endswith(".py"), f"unexpected python source emitted: {path}"
    assert "Dockerfile" in out.files
    assert "channel_config.json" in out.files
    assert "routes.json" in out.files
    assert "requirements.txt" in out.files


def test_plugin_entrypoint_is_module_form():
    plugin = SlackChannelPlugin()
    out = plugin.generate_code(_channel(), resolved_routes={})
    assert out.entrypoint == "python -m vystak_channel_slack"


def test_dockerfile_pins_package_version():
    plugin = SlackChannelPlugin()
    out = plugin.generate_code(_channel(), resolved_routes={})
    df = out.files["Dockerfile"]
    assert "vystak-channel-slack==" in df
    assert "ENTRYPOINT" in df


def test_channel_config_includes_channel_type_and_protocol():
    import json
    plugin = SlackChannelPlugin()
    out = plugin.generate_code(_channel(), resolved_routes={})
    cfg = json.loads(out.files["channel_config.json"])
    assert cfg["channel_type"] == "slack"
    assert cfg["agent_protocol"] == "a2a-turn"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest packages/python/vystak-channel-slack/tests/test_plugin.py -v
```

Expected: failures (current plugin emits `server.py` and uses old shape).

- [ ] **Step 3: Replace `server_template.py`**

Replace the entire contents of `packages/python/vystak-channel-slack/src/vystak_channel_slack/server_template.py` with:

```python
"""Build-time artifacts for the Slack channel container.

We no longer emit a SERVER_PY string. The container is built from the
installed `vystak-channel-slack` package; its __main__ entrypoint reads
config files mounted into /etc/vystak/.
"""

from __future__ import annotations

from importlib.metadata import version


def package_version() -> str:
    try:
        return version("vystak-channel-slack")
    except Exception:
        return "0.1.0"


REQUIREMENTS = f"vystak-channel-slack=={package_version()}\n"

DOCKERFILE = f"""\
FROM python:3.11-slim
RUN pip install --no-cache-dir vystak-channel-slack=={package_version()}
COPY channel_config.json routes.json /etc/vystak/
ENV VYSTAK_CONFIG_DIR=/etc/vystak
ENTRYPOINT ["python", "-m", "vystak_channel_slack"]
"""
```

- [ ] **Step 4: Create `__main__.py`**

Create `packages/python/vystak-channel-slack/src/vystak_channel_slack/__main__.py`:

```python
"""Slack channel container entrypoint."""

from __future__ import annotations

import json
import os
from pathlib import Path

from vystak_channel_runtime import launch
from vystak_channel_slack.runtime import SlackChannelRuntime


def main() -> None:
    cfg_dir = Path(os.environ.get("VYSTAK_CONFIG_DIR", "/etc/vystak"))
    config = json.loads((cfg_dir / "channel_config.json").read_text())
    routes = json.loads((cfg_dir / "routes.json").read_text())
    launch(SlackChannelRuntime, config=config, routes=routes)


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Update `plugin.py.generate_code` to emit configs + Dockerfile only**

Replace the body of `SlackChannelPlugin.generate_code` in `plugin.py` so it returns:

```python
        channel_config = self._build_channel_config(channel)
        from vystak_channel_slack.server_template import DOCKERFILE, REQUIREMENTS

        return GeneratedCode(
            files={
                "Dockerfile": DOCKERFILE,
                "requirements.txt": REQUIREMENTS,
                "channel_config.json": json.dumps(channel_config, indent=2),
                "routes.json": json.dumps(resolved_routes, indent=2),
            },
            entrypoint="python -m vystak_channel_slack",
        )
```

Extract the existing channel_config dict-build into a `_build_channel_config(channel)` helper method on the plugin class that returns the same dict shape that `plugin.py` already produces, plus two new keys at the top:

```python
        channel_config = {
            "channel_type": "slack",
            "agent_protocol": "a2a-turn",
            # ...existing keys: agents, group_policy, dm_policy, allow_from, allow_bots,
            # channel_overrides, default_agent, route_authority, welcome_on_invite,
            # welcome_message, reply_to_mode, reply_to_mode_by_chat_type, thread,
            # stream_tool_calls, state...
        }
```

- [ ] **Step 6: Run the plugin tests**

```bash
uv run pytest packages/python/vystak-channel-slack/tests/test_plugin.py -v
```

Expected: 4 PASSED.

- [ ] **Step 7: Run the full Slack test suite**

```bash
uv run pytest packages/python/vystak-channel-slack/ -v
```

Expected: all PASS. Slack release cells (gated on tokens) auto-skip locally.

- [ ] **Step 8: Smoke `python -m vystak_channel_slack --help` (if --help wired) or import**

```bash
uv run python -c "from vystak_channel_slack.__main__ import main; print('main importable')"
```

Expected: prints `main importable`.

- [ ] **Step 9: Commit**

```bash
git add packages/python/vystak-channel-slack/
git commit -m "feat(channel-slack): pivot off codegen — __main__.py + slim Dockerfile"
```

---

## Phase 3: Chat retrofit

### Task 3.1: Add runtime dep + create `ChatChannelRuntime`

**Files:**
- Modify: `packages/python/vystak-channel-chat/pyproject.toml`
- Create: `packages/python/vystak-channel-chat/src/vystak_channel_chat/runtime.py`
- Create: `packages/python/vystak-channel-chat/tests/test_runtime.py`

- [ ] **Step 1: Add the dep (mirrors Task 2.1)**

In `pyproject.toml`, append `"vystak-channel-runtime>=0.1.0",` to `dependencies` and add `vystak-channel-runtime = { workspace = true }` under `[tool.uv.sources]`. Run `uv sync`.

- [ ] **Step 2: Write the failing test**

Create `tests/test_runtime.py`:

```python
"""Tests for ChatChannelRuntime."""

import pytest
from fastapi.testclient import TestClient
from vystak_channel_chat.runtime import ChatChannelRuntime, build_app
from vystak_channel_runtime.store import MemoryChannelStore
from vystak_channel_runtime.types import AgentReply


def _config():
    return {
        "channel_type": "chat",
        "agent_protocol": "a2a-turn",
        "agents": ["hero"],
        "default_agent": "hero",
        "group_policy": "open",
        "dm_policy": "open",
        "allow_from": [],
        "allow_bots": False,
        "channel_overrides": {},
    }


class _FakeAgent:
    async def send_turn(self, *a, **kw):
        return AgentReply(text="pong")
    async def stream_turn(self, *a, **kw):
        raise NotImplementedError


def test_chat_completions_returns_assistant_text():
    rt = ChatChannelRuntime(
        config=_config(),
        routes={"hero": {"address": "http://hero:8000"}},
        store=MemoryChannelStore(),
        agent_client=_FakeAgent(),
    )
    app = build_app(rt)
    client = TestClient(app)
    resp = client.post(
        "/v1/chat/completions",
        json={
            "model": "vystak/hero",
            "messages": [{"role": "user", "content": "ping"}],
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["choices"][0]["message"]["content"] == "pong"
```

- [ ] **Step 3: Run test to verify it fails**

```bash
uv run pytest packages/python/vystak-channel-chat/tests/test_runtime.py -v
```

Expected: ImportError.

- [ ] **Step 4: Implement `runtime.py`**

Create `packages/python/vystak-channel-chat/src/vystak_channel_chat/runtime.py`:

```python
"""ChatChannelRuntime — OpenAI-compatible synchronous routing into ChannelRuntime."""

from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from vystak.schema.common import ChannelType

from vystak_channel_runtime.runtime import ChannelRuntime
from vystak_channel_runtime.types import (
    AgentReply,
    InboundEvent,
    SkipEvent,
)

logger = logging.getLogger("vystak.channel.chat")


class _ChatMessage(BaseModel):
    role: str
    content: str


class _ChatRequest(BaseModel):
    model: str
    messages: list[_ChatMessage]
    user: str | None = None


class ChatChannelRuntime(ChannelRuntime):
    """OpenAI-compatible chat endpoint backed by ChannelRuntime."""

    def __init__(self, **kw: Any) -> None:
        super().__init__(**kw)
        self._app: FastAPI | None = None
        self._server: uvicorn.Server | None = None
        # Held by post_reply to bridge the sync HTTP response.
        self._pending_reply: dict[str, AgentReply] = {}

    def parse_event(self, raw_event: Any) -> InboundEvent:
        req: _ChatRequest = raw_event["request"]
        request_id = raw_event["request_id"]
        if not req.messages:
            raise SkipEvent("empty messages")
        last = req.messages[-1]
        agent = req.model.removeprefix("vystak/") or self.config.get("default_agent") or ""
        return InboundEvent(
            channel_type=ChannelType.CHAT,
            scope_id=req.user or "anon",
            thread_id=request_id,
            user_id=req.user or "anon",
            text=last.content,
            is_dm=True,
            mentions_bot=True,
            metadata={"requested_agent": agent, "request_id": request_id},
            raw=req,
        )

    async def resolve_route(self, event: InboundEvent) -> str | None:
        explicit = event.metadata.get("requested_agent")
        if explicit:
            return explicit
        return await super().resolve_route(event)

    async def post_reply(
        self, event: InboundEvent, route: str, reply: AgentReply
    ) -> None:
        rid = event.metadata["request_id"]
        self._pending_reply[rid] = reply

    async def start(self) -> None:
        self._app = build_app(self)
        port = int(self.config.get("port", 8080))
        cfg = uvicorn.Config(self._app, host="0.0.0.0", port=port, log_level="info")
        self._server = uvicorn.Server(cfg)
        await self._server.serve()

    async def stop(self) -> None:
        if self._server is not None:
            self._server.should_exit = True


def build_app(rt: ChatChannelRuntime) -> FastAPI:
    app = FastAPI(title="vystak-channel-chat")

    @app.post("/v1/chat/completions")
    async def completions(req: _ChatRequest) -> dict:
        rid = str(uuid.uuid4())
        await rt.handle_event({"request": req, "request_id": rid})
        reply = rt._pending_reply.pop(rid, None)
        if reply is None:
            raise HTTPException(status_code=502, detail="no reply (route missing or agent error)")
        return {
            "id": rid,
            "object": "chat.completion",
            "created": int(time.time()),
            "model": req.model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": reply.text},
                    "finish_reason": reply.finish_reason or "stop",
                }
            ],
        }

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    return app
```

- [ ] **Step 5: Run test to verify it passes**

```bash
uv run pytest packages/python/vystak-channel-chat/tests/test_runtime.py -v
```

Expected: 1 PASSED.

- [ ] **Step 6: Commit**

```bash
git add packages/python/vystak-channel-chat/
git commit -m "feat(channel-chat): add ChatChannelRuntime built on vystak-channel-runtime"
```

---

### Task 3.2: Chat `__main__.py` + plugin emits configs+Dockerfile only

**Files:**
- Create: `packages/python/vystak-channel-chat/src/vystak_channel_chat/__main__.py`
- Modify: `packages/python/vystak-channel-chat/src/vystak_channel_chat/server_template.py`
- Modify: `packages/python/vystak-channel-chat/src/vystak_channel_chat/plugin.py`
- Modify: `packages/python/vystak-channel-chat/tests/test_plugin.py` (or create)

- [ ] **Step 1: Add the failing plugin test (mirrors Task 2.8)**

Create or edit `tests/test_plugin.py`:

```python
"""Tests for the chat channel plugin's no-codegen output shape."""

import json

from vystak.schema.channel import Channel
from vystak.schema.common import ChannelType
from vystak_channel_chat.plugin import ChatChannelPlugin


def _channel():
    return Channel(name="chat", type=ChannelType.CHAT, agents=[])


def test_plugin_emits_no_python_source():
    out = ChatChannelPlugin().generate_code(_channel(), resolved_routes={})
    for path in out.files:
        assert not path.endswith(".py"), f"unexpected python source: {path}"
    assert "Dockerfile" in out.files
    assert "channel_config.json" in out.files


def test_entrypoint_is_module_form():
    out = ChatChannelPlugin().generate_code(_channel(), resolved_routes={})
    assert out.entrypoint == "python -m vystak_channel_chat"


def test_channel_config_includes_channel_type_and_protocol():
    out = ChatChannelPlugin().generate_code(_channel(), resolved_routes={})
    cfg = json.loads(out.files["channel_config.json"])
    assert cfg["channel_type"] == "chat"
    assert cfg["agent_protocol"] == "a2a-turn"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest packages/python/vystak-channel-chat/tests/test_plugin.py -v
```

Expected: failures.

- [ ] **Step 3: Replace `server_template.py`**

Replace contents:

```python
"""Build-time artifacts for the chat channel container."""

from __future__ import annotations

from importlib.metadata import version


def package_version() -> str:
    try:
        return version("vystak-channel-chat")
    except Exception:
        return "0.1.0"


REQUIREMENTS = f"vystak-channel-chat=={package_version()}\n"

DOCKERFILE = f"""\
FROM python:3.11-slim
RUN pip install --no-cache-dir vystak-channel-chat=={package_version()}
COPY channel_config.json routes.json /etc/vystak/
ENV VYSTAK_CONFIG_DIR=/etc/vystak
ENTRYPOINT ["python", "-m", "vystak_channel_chat"]
"""
```

- [ ] **Step 4: Create `__main__.py`**

Create `packages/python/vystak-channel-chat/src/vystak_channel_chat/__main__.py`:

```python
"""Chat channel container entrypoint."""

from __future__ import annotations

import json
import os
from pathlib import Path

from vystak_channel_runtime import launch
from vystak_channel_chat.runtime import ChatChannelRuntime


def main() -> None:
    cfg_dir = Path(os.environ.get("VYSTAK_CONFIG_DIR", "/etc/vystak"))
    config = json.loads((cfg_dir / "channel_config.json").read_text())
    routes_path = cfg_dir / "routes.json"
    routes = json.loads(routes_path.read_text()) if routes_path.exists() else {}
    launch(ChatChannelRuntime, config=config, routes=routes)


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Update `plugin.py.generate_code`**

Replace the `generate_code` body in `plugin.py`:

```python
        from vystak_channel_chat.server_template import DOCKERFILE, REQUIREMENTS

        channel_config = {
            "channel_type": "chat",
            "agent_protocol": "a2a-turn",
            "agents": [a.name for a in channel.agents],
            "default_agent": channel.default_agent.name if channel.default_agent else None,
            "port": 8080,
            "state": (
                channel.state.model_dump(exclude_none=True)
                if channel.state is not None else None
            ),
        }
        return GeneratedCode(
            files={
                "Dockerfile": DOCKERFILE,
                "requirements.txt": REQUIREMENTS,
                "channel_config.json": json.dumps(channel_config, indent=2),
                "routes.json": json.dumps(resolved_routes, indent=2),
            },
            entrypoint="python -m vystak_channel_chat",
        )
```

- [ ] **Step 6: Run all chat tests**

```bash
uv run pytest packages/python/vystak-channel-chat/ -v
```

Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add packages/python/vystak-channel-chat/
git commit -m "feat(channel-chat): pivot off codegen — __main__.py + slim Dockerfile"
```

---

## Phase 4: `vystak-channel-discord` package

### Task 4.1: Create Discord package skeleton + plugin

**Files:**
- Create: `packages/python/vystak-channel-discord/pyproject.toml`
- Create: `packages/python/vystak-channel-discord/README.md`
- Create: `packages/python/vystak-channel-discord/src/vystak_channel_discord/__init__.py`
- Create: `packages/python/vystak-channel-discord/src/vystak_channel_discord/plugin.py`
- Create: `packages/python/vystak-channel-discord/src/vystak_channel_discord/server_template.py`
- Create: `packages/python/vystak-channel-discord/tests/__init__.py`
- Create: `packages/python/vystak-channel-discord/tests/test_plugin.py`

- [ ] **Step 1: Create directory structure**

```bash
mkdir -p packages/python/vystak-channel-discord/src/vystak_channel_discord
mkdir -p packages/python/vystak-channel-discord/tests
```

- [ ] **Step 2: Write `pyproject.toml`**

```toml
[project]
name = "vystak-channel-discord"
dynamic = ["version"]
description = "Vystak Discord channel — Gateway WebSocket runner"
readme = "README.md"
requires-python = ">=3.11"
license = "Apache-2.0"
authors = [
    { name = "Anatoliy Kolodkin", email = "11351966+akolodkin@users.noreply.github.com" },
]
keywords = ["vystak", "channel", "discord", "agent"]
classifiers = [
    "Development Status :: 3 - Alpha",
    "Intended Audience :: Developers",
    "License :: OSI Approved :: Apache Software License",
    "Operating System :: OS Independent",
    "Programming Language :: Python :: 3",
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
    "Programming Language :: Python :: 3.13",
    "Topic :: Software Development :: Libraries :: Python Modules",
]
dependencies = [
    "vystak>=0.1.0",
    "vystak-channel-runtime>=0.1.0",
    "discord.py>=2.4",
]

[project.urls]
Homepage = "https://vystak.dev"
Repository = "https://github.com/vystak/vystak"

[build-system]
requires = ["hatchling", "hatch-vcs"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/vystak_channel_discord"]

[tool.hatch.version]
source = "vcs"

[tool.uv.sources]
vystak = { workspace = true }
vystak-channel-runtime = { workspace = true }

[tool.pytest.ini_options]
asyncio_mode = "auto"
```

- [ ] **Step 3: Write minimal `README.md`**

```markdown
# vystak-channel-discord

Vystak Discord channel — gateway-mode bot dispatching events into the
shared `vystak-channel-runtime` pipeline.

Setup: see `website/docs/channels/discord.md`.
```

- [ ] **Step 4: Write the failing plugin test**

Create `tests/test_plugin.py`:

```python
"""Tests for the Discord channel plugin."""

import json

from vystak.schema.channel import Channel
from vystak.schema.common import ChannelType
from vystak_channel_discord.plugin import DiscordChannelPlugin


def _channel():
    return Channel(name="discord-prod", type=ChannelType.DISCORD, agents=[])


def test_plugin_emits_no_python_source():
    out = DiscordChannelPlugin().generate_code(_channel(), resolved_routes={})
    for path in out.files:
        assert not path.endswith(".py"), f"unexpected python source: {path}"
    assert "Dockerfile" in out.files
    assert "channel_config.json" in out.files
    assert "routes.json" in out.files


def test_entrypoint_is_module_form():
    out = DiscordChannelPlugin().generate_code(_channel(), resolved_routes={})
    assert out.entrypoint == "python -m vystak_channel_discord"


def test_channel_config_includes_channel_type_and_protocol():
    out = DiscordChannelPlugin().generate_code(_channel(), resolved_routes={})
    cfg = json.loads(out.files["channel_config.json"])
    assert cfg["channel_type"] == "discord"
    assert cfg["agent_protocol"] == "a2a-turn"
```

- [ ] **Step 5: Sync workspace + run test**

```bash
uv sync
uv run pytest packages/python/vystak-channel-discord/tests/test_plugin.py -v
```

Expected: ImportError on `vystak_channel_discord.plugin`.

- [ ] **Step 6: Implement `server_template.py`**

```python
"""Build-time artifacts for the Discord channel container."""

from __future__ import annotations

from importlib.metadata import version


def package_version() -> str:
    try:
        return version("vystak-channel-discord")
    except Exception:
        return "0.1.0"


REQUIREMENTS = f"vystak-channel-discord=={package_version()}\n"

DOCKERFILE = f"""\
FROM python:3.11-slim
RUN pip install --no-cache-dir vystak-channel-discord=={package_version()}
COPY channel_config.json routes.json /etc/vystak/
ENV VYSTAK_CONFIG_DIR=/etc/vystak
ENTRYPOINT ["python", "-m", "vystak_channel_discord"]
"""
```

- [ ] **Step 7: Implement `plugin.py`**

Create `packages/python/vystak-channel-discord/src/vystak_channel_discord/plugin.py`:

```python
"""DiscordChannelPlugin — build-time codegen (configs + Dockerfile only)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from pydantic import BaseModel
from vystak.providers.base import ChannelPlugin, GeneratedCode
from vystak.schema.channel import Channel
from vystak.schema.common import AgentProtocol, ChannelType, RuntimeMode
from vystak.schema.platform import Platform

from vystak_channel_discord.server_template import DOCKERFILE, REQUIREMENTS

if TYPE_CHECKING:
    from vystak.provisioning import Provisionable


class DiscordChannelConfig(BaseModel):
    """Optional config for a Discord channel."""

    port: int = 8080
    application_id: str | None = None
    register_slash_commands: bool = True


class DiscordChannelPlugin(ChannelPlugin):
    """Discord channel — gateway runner, one container per declaration."""

    type = ChannelType.DISCORD
    default_runtime_mode = RuntimeMode.SHARED
    agent_protocol = AgentProtocol.A2A_TURN
    config_schema = DiscordChannelConfig

    def generate_code(
        self, channel: Channel, resolved_routes: dict[str, dict[str, str]]
    ) -> GeneratedCode:
        agent_names = [a.name for a in channel.agents]
        default_agent_name = (
            channel.default_agent.name if channel.default_agent else None
        )
        channel_overrides: dict[str, dict] = {}
        for ch_id, ov in channel.channel_overrides.items():
            channel_overrides[ch_id] = {
                "agent": ov.agent.name if ov.agent else None,
                "system_prompt": ov.system_prompt,
                "tools": ov.tools,
                "skills": ov.skills,
                "users": ov.users,
                "require_mention": ov.require_mention,
            }

        state_cfg: dict | None = None
        if channel.state is not None:
            state_cfg = channel.state.model_dump(exclude_none=True)

        channel_config: dict = {
            "channel_type": "discord",
            "agent_protocol": "a2a-turn",
            "agents": agent_names,
            "default_agent": default_agent_name,
            "group_policy": (
                channel.group_policy.value
                if hasattr(channel.group_policy, "value") else channel.group_policy
            ),
            "dm_policy": (
                channel.dm_policy.value
                if hasattr(channel.dm_policy, "value") else channel.dm_policy
            ),
            "allow_from": list(channel.allow_from),
            "allow_bots": channel.allow_bots,
            "channel_overrides": channel_overrides,
            "route_authority": channel.route_authority,
            "welcome_on_invite": channel.welcome_on_invite,
            "welcome_message": channel.welcome_message,
            "thread": {
                "history_scope": channel.thread.history_scope,
                "initial_history_limit": channel.thread.initial_history_limit,
                "inherit_parent": channel.thread.inherit_parent,
                "require_explicit_mention": channel.thread.require_explicit_mention,
            },
            "register_slash_commands": bool(
                channel.config.get("register_slash_commands", True)
            ),
            "port": int(channel.config.get("port", 8080)),
            "application_id": channel.config.get("application_id"),
            "state": state_cfg,
        }

        return GeneratedCode(
            files={
                "Dockerfile": DOCKERFILE,
                "requirements.txt": REQUIREMENTS,
                "channel_config.json": json.dumps(channel_config, indent=2),
                "routes.json": json.dumps(resolved_routes, indent=2),
            },
            entrypoint="python -m vystak_channel_discord",
        )

    def provision_nodes(
        self, channel: Channel, platform: Platform
    ) -> "list[Provisionable]":
        return []

    def thread_name(self, event: dict) -> str:
        guild = event.get("guild_id") or "dm"
        channel_id = event.get("channel_id") or "0"
        thread = event.get("thread_id") or event.get("message_id") or "root"
        return f"thread:discord:{guild}:{channel_id}:{thread}"

    def health_check(self, deployment: dict) -> str:
        return "ok" if deployment.get("running") else "down"
```

- [ ] **Step 8: Empty `__init__.py`**

Create `src/vystak_channel_discord/__init__.py`:

```python
"""Vystak Discord channel."""

from vystak_channel_discord.plugin import DiscordChannelConfig, DiscordChannelPlugin

__all__ = ["DiscordChannelConfig", "DiscordChannelPlugin"]
```

- [ ] **Step 9: Empty `tests/__init__.py`**

Create empty file.

- [ ] **Step 10: Run tests**

```bash
uv sync
uv run pytest packages/python/vystak-channel-discord/tests/test_plugin.py -v
```

Expected: 3 PASSED.

- [ ] **Step 11: Commit**

```bash
git add packages/python/vystak-channel-discord pyproject.toml uv.lock
git commit -m "feat(channel-discord): scaffold package + DiscordChannelPlugin"
```

---

### Task 4.2: `DiscordChannelRuntime` skeleton (lifecycle)

**Files:**
- Create: `packages/python/vystak-channel-discord/src/vystak_channel_discord/runtime.py`
- Create: `packages/python/vystak-channel-discord/tests/test_runtime.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_runtime.py`:

```python
"""Tests for DiscordChannelRuntime."""

import pytest
from vystak_channel_discord.runtime import DiscordChannelRuntime
from vystak_channel_runtime.store import MemoryChannelStore


def _config():
    return {
        "channel_type": "discord",
        "agent_protocol": "a2a-turn",
        "agents": ["hero"],
        "default_agent": "hero",
        "group_policy": "open",
        "dm_policy": "open",
        "allow_from": [],
        "allow_bots": False,
        "channel_overrides": {},
        "register_slash_commands": False,
    }


def test_runtime_constructable():
    rt = DiscordChannelRuntime(
        config=_config(),
        routes={"hero": {"address": "http://hero:8000"}},
        store=MemoryChannelStore(),
    )
    assert rt.channel_type == "discord"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest packages/python/vystak-channel-discord/tests/test_runtime.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement `runtime.py` (skeleton)**

Create `packages/python/vystak-channel-discord/src/vystak_channel_discord/runtime.py`:

```python
"""DiscordChannelRuntime — gateway-mode bot dispatching into ChannelRuntime."""

from __future__ import annotations

import logging
import os
from typing import Any

import discord

from vystak_channel_runtime.runtime import ChannelRuntime
from vystak_channel_runtime.types import (
    AgentReply,
    InboundEvent,
    SkipEvent,
)

logger = logging.getLogger("vystak.channel.discord")

MAX_DISCORD_MESSAGE_CHARS = 2000


class DiscordChannelRuntime(ChannelRuntime):
    """Discord gateway runtime."""

    def __init__(self, **kw: Any) -> None:
        super().__init__(**kw)
        self._client: discord.Client | None = None
        self._token: str | None = None

    async def start(self) -> None:
        self._token = os.environ["DISCORD_BOT_TOKEN"]
        intents = discord.Intents.none()
        intents.guilds = True
        intents.guild_messages = True
        intents.dm_messages = True
        intents.message_content = True
        self._client = discord.Client(intents=intents)

        @self._client.event
        async def on_ready():  # noqa: ARG001
            logger.info("discord client connected as %s", self._client.user)

        @self._client.event
        async def on_message(message: discord.Message):
            await self.handle_event({"kind": "message", "message": message})

        @self._client.event
        async def on_interaction(interaction: discord.Interaction):
            await self.handle_event({"kind": "interaction", "interaction": interaction})

        await self._client.start(self._token)

    async def stop(self) -> None:
        if self._client is not None:
            await self._client.close()

    def parse_event(self, raw_event: Any) -> InboundEvent:
        # Real impl in Task 4.3
        raise SkipEvent("not implemented yet")

    async def post_reply(
        self, event: InboundEvent, route: str, reply: AgentReply
    ) -> None:
        # Real impl in Task 4.4
        raise NotImplementedError
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest packages/python/vystak-channel-discord/tests/test_runtime.py::test_runtime_constructable -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-channel-discord/
git commit -m "feat(channel-discord): scaffold DiscordChannelRuntime (lifecycle only)"
```

---

### Task 4.3: `parse_event` for Discord messages

**Files:**
- Modify: `packages/python/vystak-channel-discord/src/vystak_channel_discord/runtime.py`
- Modify: `packages/python/vystak-channel-discord/tests/test_runtime.py`

> **Note:** discord.py message events come as `discord.Message` objects. Tests use lightweight stand-ins (Pydantic-y dataclasses) instead of real discord.py objects so we don't need a real gateway connection.

- [ ] **Step 1: Add the failing test**

Append to `tests/test_runtime.py`:

```python
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class _FakeUser:
    id: int
    bot: bool = False


@dataclass
class _FakeChannel:
    id: int
    type_str: str = "text"  # "text" | "dm" | "thread" | "forum"

    @property
    def type(self):
        # Mimic discord.ChannelType enum lookup we use in parse_event.
        return self.type_str


@dataclass
class _FakeGuild:
    id: int


@dataclass
class _FakeThread:
    id: int


@dataclass
class _FakeMessage:
    id: int
    author: _FakeUser
    channel: _FakeChannel
    guild: Optional[_FakeGuild]
    content: str
    mentions: list[_FakeUser] = field(default_factory=list)
    thread: Optional[_FakeThread] = None
    reference: Optional[object] = None


def _bot_user():
    return _FakeUser(id=999, bot=True)


def _make_runtime():
    rt = DiscordChannelRuntime(
        config=_config(),
        routes={"hero": {"address": "http://hero:8000"}},
        store=MemoryChannelStore(),
    )
    bot = _bot_user()
    rt._bot_user = bot  # type: ignore[attr-defined]
    return rt


def test_parse_event_guild_message_with_mention():
    rt = _make_runtime()
    msg = _FakeMessage(
        id=10,
        author=_FakeUser(id=1),
        channel=_FakeChannel(id=200, type_str="text"),
        guild=_FakeGuild(id=100),
        content=f"hi <@{rt._bot_user.id}>",
        mentions=[rt._bot_user],
    )
    ev = rt.parse_event({"kind": "message", "message": msg})
    assert ev.scope_id == "100/200"
    assert ev.thread_id == "10"
    assert ev.user_id == "1"
    assert ev.is_dm is False
    assert ev.mentions_bot is True


def test_parse_event_dm_uses_dm_scope():
    rt = _make_runtime()
    msg = _FakeMessage(
        id=11,
        author=_FakeUser(id=2),
        channel=_FakeChannel(id=300, type_str="dm"),
        guild=None,
        content="hello",
    )
    ev = rt.parse_event({"kind": "message", "message": msg})
    assert ev.scope_id == "dm/2"
    assert ev.is_dm is True
    assert ev.mentions_bot is False


def test_parse_event_in_thread_uses_thread_id():
    rt = _make_runtime()
    msg = _FakeMessage(
        id=12,
        author=_FakeUser(id=3),
        channel=_FakeChannel(id=400, type_str="thread"),
        guild=_FakeGuild(id=100),
        content="hi",
        thread=_FakeThread(id=999),
    )
    ev = rt.parse_event({"kind": "message", "message": msg})
    assert ev.thread_id == "999"


def test_parse_event_skips_own_messages():
    rt = _make_runtime()
    msg = _FakeMessage(
        id=13,
        author=_FakeUser(id=rt._bot_user.id),
        channel=_FakeChannel(id=500, type_str="text"),
        guild=_FakeGuild(id=100),
        content="self",
    )
    with pytest.raises(SkipEvent):
        rt.parse_event({"kind": "message", "message": msg})


def test_parse_event_skips_other_bots_when_disallowed():
    rt = _make_runtime()
    msg = _FakeMessage(
        id=14,
        author=_FakeUser(id=42, bot=True),
        channel=_FakeChannel(id=600, type_str="text"),
        guild=_FakeGuild(id=100),
        content="hi",
    )
    ev = rt.parse_event({"kind": "message", "message": msg})
    assert ev.metadata["is_bot"] is True
```

(Add at the top: `from vystak_channel_runtime.types import SkipEvent`.)

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest packages/python/vystak-channel-discord/tests/test_runtime.py -v -k parse_event
```

Expected: failures (placeholder still raises SkipEvent unconditionally).

- [ ] **Step 3: Implement `parse_event`**

Replace the body of `parse_event` in `runtime.py`:

```python
    def parse_event(self, raw_event: Any) -> InboundEvent:
        from vystak.schema.common import ChannelType

        if raw_event.get("kind") != "message":
            raise SkipEvent("not a message")
        msg = raw_event["message"]

        bot_user = getattr(self, "_bot_user", None) or (
            self._client.user if self._client is not None else None
        )
        if bot_user is not None and msg.author.id == bot_user.id:
            raise SkipEvent("own message")

        is_dm = getattr(msg.channel, "type", None) in {"dm", "private", discord.ChannelType.private}
        if is_dm:
            scope_id = f"dm/{msg.author.id}"
        else:
            guild_id = getattr(getattr(msg, "guild", None), "id", "?")
            scope_id = f"{guild_id}/{msg.channel.id}"

        if getattr(msg, "thread", None) is not None:
            thread_id = str(msg.thread.id)
        elif getattr(msg.channel, "type", None) in {"thread", "forum"}:
            thread_id = str(msg.channel.id)
        else:
            thread_id = str(msg.id)

        mentions_bot = False
        if bot_user is not None:
            mentions_bot = any(m.id == bot_user.id for m in (msg.mentions or []))

        is_bot = bool(getattr(msg.author, "bot", False))

        metadata = {
            "channel_id": str(msg.channel.id),
            "guild_id": str(getattr(getattr(msg, "guild", None), "id", "")),
            "message_id": str(msg.id),
            "channel_type": getattr(msg.channel, "type", None),
            "is_bot": is_bot,
            "raw_message": msg,
        }

        return InboundEvent(
            channel_type=ChannelType.DISCORD,
            scope_id=scope_id,
            thread_id=thread_id,
            user_id=str(msg.author.id),
            text=msg.content or "",
            is_dm=is_dm,
            mentions_bot=mentions_bot,
            metadata=metadata,
            raw=raw_event,
        )
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest packages/python/vystak-channel-discord/tests/test_runtime.py -v -k parse_event
```

Expected: 5 PASSED.

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-channel-discord/
git commit -m "feat(channel-discord): implement parse_event for messages, DMs, threads"
```

---

### Task 4.4: `post_reply` with 2000-char split

**Files:**
- Modify: `packages/python/vystak-channel-discord/src/vystak_channel_discord/runtime.py`
- Modify: `packages/python/vystak-channel-discord/tests/test_runtime.py`

- [ ] **Step 1: Add the failing test**

Append to `tests/test_runtime.py`:

```python
@dataclass
class _FakeChannelWithSend(_FakeChannel):
    sent: list = field(default_factory=list)

    async def send(self, content: str):
        self.sent.append(content)


@pytest.mark.asyncio
async def test_post_reply_sends_to_channel():
    rt = _make_runtime()
    chan = _FakeChannelWithSend(id=200, type_str="text")
    msg = _FakeMessage(
        id=10,
        author=_FakeUser(id=1),
        channel=chan,
        guild=_FakeGuild(id=100),
        content="hi",
        mentions=[rt._bot_user],
    )
    ev = rt.parse_event({"kind": "message", "message": msg})
    await rt.post_reply(ev, "hero", AgentReply(text="hello back"))
    assert chan.sent == ["hello back"]


@pytest.mark.asyncio
async def test_post_reply_splits_long_messages():
    rt = _make_runtime()
    chan = _FakeChannelWithSend(id=200, type_str="text")
    msg = _FakeMessage(
        id=10,
        author=_FakeUser(id=1),
        channel=chan,
        guild=_FakeGuild(id=100),
        content="hi",
        mentions=[rt._bot_user],
    )
    ev = rt.parse_event({"kind": "message", "message": msg})
    long = "x" * 4500
    await rt.post_reply(ev, "hero", AgentReply(text=long))
    assert len(chan.sent) == 3
    assert all(len(s) <= 2000 for s in chan.sent)
    assert "".join(chan.sent) == long
```

(Add `from vystak_channel_runtime.types import AgentReply` at the top if not already present.)

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest packages/python/vystak-channel-discord/tests/test_runtime.py -v -k post_reply
```

Expected: failure (NotImplementedError).

- [ ] **Step 3: Implement `post_reply`**

Replace `post_reply` body in `runtime.py`:

```python
    async def post_reply(
        self, event: InboundEvent, route: str, reply: AgentReply
    ) -> None:
        msg = event.metadata.get("raw_message")
        if msg is None:
            logger.warning("no raw_message; cannot post reply")
            return
        text = reply.text or ""
        for chunk in _chunk(text, MAX_DISCORD_MESSAGE_CHARS):
            await msg.channel.send(chunk)


def _chunk(text: str, size: int) -> list[str]:
    if not text:
        return [""]
    return [text[i : i + size] for i in range(0, len(text), size)]
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest packages/python/vystak-channel-discord/tests/test_runtime.py -v -k post_reply
```

Expected: 2 PASSED.

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-channel-discord/
git commit -m "feat(channel-discord): implement post_reply with 2000-char chunking"
```

---

### Task 4.5: `fetch_history`, `before_call`, `after_reply`, `on_no_route`, `on_agent_error`

**Files:**
- Modify: `packages/python/vystak-channel-discord/src/vystak_channel_discord/runtime.py`
- Modify: `packages/python/vystak-channel-discord/tests/test_runtime.py`

- [ ] **Step 1: Add the failing tests**

Append to `tests/test_runtime.py`:

```python
@dataclass
class _FakeHistMsg:
    author: _FakeUser
    content: str


@dataclass
class _FakeChannelWithHistory(_FakeChannelWithSend):
    history_msgs: list = field(default_factory=list)

    def history(self, limit: int):
        msgs = self.history_msgs[:limit]

        async def _aiter():
            for m in msgs:
                yield m

        return _aiter()


@pytest.mark.asyncio
async def test_fetch_history_returns_messages_for_thread():
    rt = _make_runtime()
    chan = _FakeChannelWithHistory(id=400, type_str="thread")
    chan.history_msgs = [
        _FakeHistMsg(author=_FakeUser(id=1), content="user-msg"),
        _FakeHistMsg(author=rt._bot_user, content="bot-msg"),
    ]
    msg = _FakeMessage(
        id=12,
        author=_FakeUser(id=3),
        channel=chan,
        guild=_FakeGuild(id=100),
        content="hi",
        thread=_FakeThread(id=999),
    )
    ev = rt.parse_event({"kind": "message", "message": msg})
    history = await rt.fetch_history(ev)
    assert len(history) == 2
    assert history[0].role == "user"
    assert history[1].role == "assistant"


@pytest.mark.asyncio
async def test_fetch_history_empty_for_top_level_message():
    rt = _make_runtime()
    chan = _FakeChannelWithHistory(id=200, type_str="text")
    msg = _FakeMessage(
        id=10,
        author=_FakeUser(id=1),
        channel=chan,
        guild=_FakeGuild(id=100),
        content="hi",
    )
    ev = rt.parse_event({"kind": "message", "message": msg})
    history = await rt.fetch_history(ev)
    assert history == []


@pytest.mark.asyncio
async def test_after_reply_persists_thread_binding():
    rt = _make_runtime()
    chan = _FakeChannelWithSend(id=200, type_str="thread")
    msg = _FakeMessage(
        id=12,
        author=_FakeUser(id=3),
        channel=chan,
        guild=_FakeGuild(id=100),
        content="hi",
        thread=_FakeThread(id=999),
    )
    ev = rt.parse_event({"kind": "message", "message": msg})
    await rt.after_reply(ev, "hero", AgentReply(text="ok"))
    bound = await rt.store.get_thread_binding("discord", ev.scope_id, ev.thread_id)
    assert bound == "hero"


@pytest.mark.asyncio
async def test_on_no_route_posts_message_when_configured():
    rt = DiscordChannelRuntime(
        config={**_config(), "no_route_message": "no agent here"},
        routes={"hero": {"address": "http://hero:8000"}},
        store=MemoryChannelStore(),
    )
    rt._bot_user = _bot_user()
    chan = _FakeChannelWithSend(id=200, type_str="text")
    msg = _FakeMessage(
        id=10,
        author=_FakeUser(id=1),
        channel=chan,
        guild=_FakeGuild(id=100),
        content="hi",
        mentions=[rt._bot_user],
    )
    ev = rt.parse_event({"kind": "message", "message": msg})
    await rt.on_no_route(ev)
    assert chan.sent == ["no agent here"]
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest packages/python/vystak-channel-discord/tests/test_runtime.py -v -k "fetch_history or after_reply or on_no_route"
```

Expected: failures.

- [ ] **Step 3: Add the hooks**

Append to the `DiscordChannelRuntime` class in `runtime.py`:

```python
    async def fetch_history(self, event: InboundEvent) -> "list[Message]":
        from vystak_channel_runtime.types import Message
        msg = event.metadata.get("raw_message")
        if msg is None:
            return []
        if getattr(msg.channel, "type", None) not in {"thread", "forum"} and getattr(msg, "thread", None) is None:
            return []
        limit = self.config.get("thread", {}).get("initial_history_limit", 20)
        out: list[Message] = []
        bot_id = getattr(getattr(self, "_bot_user", None), "id", None)
        async for hist in msg.channel.history(limit=limit):
            role = "assistant" if getattr(hist.author, "id", None) == bot_id else "user"
            out.append(Message(role=role, content=hist.content or ""))
        return out

    async def before_call(self, event: InboundEvent, route: str) -> None:
        if not self.config.get("post_placeholder", False):
            return
        msg = event.metadata.get("raw_message")
        if msg is None:
            return
        try:
            placeholder = await msg.channel.send("Responding…")
        except Exception:  # noqa: BLE001
            return
        event.metadata["placeholder_message"] = placeholder

    async def on_no_route(self, event: InboundEvent) -> None:
        text = self.config.get("no_route_message")
        if not text:
            return
        msg = event.metadata.get("raw_message")
        if msg is None:
            return
        try:
            await msg.channel.send(text)
        except Exception:  # noqa: BLE001
            logger.warning("on_no_route send failed", exc_info=True)

    async def on_agent_error(
        self, event: InboundEvent, route: str, exc: "AgentCallError"
    ) -> None:
        msg = event.metadata.get("raw_message")
        if msg is None:
            return
        try:
            await msg.channel.send(f"Agent error ({route}): {str(exc)[:300]}")
        except Exception:  # noqa: BLE001
            logger.warning("on_agent_error send failed", exc_info=True)
```

(Add `from vystak_channel_runtime.types import AgentCallError` to imports.)

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest packages/python/vystak-channel-discord/tests/test_runtime.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-channel-discord/
git commit -m "feat(channel-discord): add fetch_history + UX hooks"
```

---

### Task 4.6: Discord slash commands (`commands.py`)

**Files:**
- Create: `packages/python/vystak-channel-discord/src/vystak_channel_discord/commands.py`
- Create: `packages/python/vystak-channel-discord/tests/test_commands.py`

> **Note:** This task implements pure store-mutation handlers. The actual `discord.app_commands` registration is wired into `runtime.start()` in Task 4.9 (alongside welcome). This split lets us unit-test the handlers without instantiating `discord.Client`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_commands.py`:

```python
"""Tests for /vystak slash command handlers."""

import pytest

from vystak_channel_discord.commands import (
    handle_prefer,
    handle_route,
    handle_status,
    handle_unprefer,
    handle_unroute,
)
from vystak_channel_runtime.store import MemoryChannelStore


@pytest.mark.asyncio
async def test_handle_route_sets_thread_binding():
    store = MemoryChannelStore()
    msg = await handle_route(store, scope_id="100/200", thread_id="100/200:", agent="hero")
    assert "hero" in msg
    assert await store.get_thread_binding("discord", "100/200", "100/200:") == "hero"


@pytest.mark.asyncio
async def test_handle_unroute_removes_binding():
    store = MemoryChannelStore()
    await store.set_thread_binding("discord", "100/200", "100/200:", "hero")
    msg = await handle_unroute(store, scope_id="100/200", thread_id="100/200:")
    assert "removed" in msg.lower() or "unrouted" in msg.lower()
    assert await store.get_thread_binding("discord", "100/200", "100/200:") is None


@pytest.mark.asyncio
async def test_handle_prefer_sets_route_pref():
    store = MemoryChannelStore()
    msg = await handle_prefer(store, scope_id="dm/42", agent="villain")
    assert "villain" in msg
    assert await store.get_route_pref("discord", "dm/42") == "villain"


@pytest.mark.asyncio
async def test_handle_unprefer_removes_route_pref():
    store = MemoryChannelStore()
    await store.set_route_pref("discord", "dm/42", "villain")
    msg = await handle_unprefer(store, scope_id="dm/42")
    assert await store.get_route_pref("discord", "dm/42") is None


@pytest.mark.asyncio
async def test_handle_status_lists_bindings():
    store = MemoryChannelStore()
    await store.set_thread_binding("discord", "100/200", "T:1", "hero")
    msg = await handle_status(store, scope_id="100/200")
    assert "hero" in msg
    assert "T:1" in msg
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest packages/python/vystak-channel-discord/tests/test_commands.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement `commands.py`**

Create `packages/python/vystak-channel-discord/src/vystak_channel_discord/commands.py`:

```python
"""/vystak slash-command handlers — pure store mutations, easy to unit-test."""

from __future__ import annotations

from vystak_channel_runtime.store import ChannelStore


async def handle_route(
    store: ChannelStore, scope_id: str, thread_id: str, agent: str
) -> str:
    await store.set_thread_binding("discord", scope_id, thread_id, agent)
    return f"Routed thread to agent **{agent}**."


async def handle_unroute(
    store: ChannelStore, scope_id: str, thread_id: str
) -> str:
    await store.delete_thread_binding("discord", scope_id, thread_id)
    return "Thread routing removed."


async def handle_prefer(
    store: ChannelStore, scope_id: str, agent: str
) -> str:
    await store.set_route_pref("discord", scope_id, agent)
    return f"Preference set: agent **{agent}**."


async def handle_unprefer(
    store: ChannelStore, scope_id: str
) -> str:
    await store.delete_route_pref("discord", scope_id)
    return "Preference removed."


async def handle_status(
    store: ChannelStore, scope_id: str
) -> str:
    bindings = await store.list_thread_bindings("discord", scope_id)
    pref = await store.get_route_pref("discord", scope_id)
    parts = []
    if pref:
        parts.append(f"Default agent: **{pref}**")
    if bindings:
        lines = "\n".join(f"- `{b.thread_id}` → **{b.agent_name}**" for b in bindings)
        parts.append(f"Thread bindings:\n{lines}")
    return "\n\n".join(parts) or "No bindings configured for this scope."
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest packages/python/vystak-channel-discord/tests/test_commands.py -v
```

Expected: 5 PASSED.

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-channel-discord/
git commit -m "feat(channel-discord): add /vystak slash command handlers (route/prefer/status/...)"
```

---

### Task 4.7: Discord welcome / auto-bind (`welcome.py`)

**Files:**
- Create: `packages/python/vystak-channel-discord/src/vystak_channel_discord/welcome.py`
- Create: `packages/python/vystak-channel-discord/tests/test_welcome.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_welcome.py`:

```python
"""Tests for Discord welcome / auto-bind."""

import pytest

from vystak_channel_discord.welcome import auto_bind_single_agent
from vystak_channel_runtime.store import MemoryChannelStore


@pytest.mark.asyncio
async def test_auto_bind_does_nothing_when_multiple_agents():
    store = MemoryChannelStore()
    await auto_bind_single_agent(store, scope_id="100/200", agents=["hero", "villain"])
    assert await store.get_route_pref("discord", "100/200") is None


@pytest.mark.asyncio
async def test_auto_bind_sets_pref_when_single_agent():
    store = MemoryChannelStore()
    await auto_bind_single_agent(store, scope_id="100/200", agents=["hero"])
    assert await store.get_route_pref("discord", "100/200") == "hero"


@pytest.mark.asyncio
async def test_auto_bind_does_nothing_when_already_bound():
    store = MemoryChannelStore()
    await store.set_route_pref("discord", "100/200", "villain")
    await auto_bind_single_agent(store, scope_id="100/200", agents=["hero"])
    assert await store.get_route_pref("discord", "100/200") == "villain"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest packages/python/vystak-channel-discord/tests/test_welcome.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement `welcome.py`**

Create `packages/python/vystak-channel-discord/src/vystak_channel_discord/welcome.py`:

```python
"""Discord welcome + single-agent auto-bind on join."""

from __future__ import annotations

from vystak_channel_runtime.store import ChannelStore


async def auto_bind_single_agent(
    store: ChannelStore, scope_id: str, agents: list[str]
) -> None:
    """If exactly one agent is declared, set it as the route pref for the scope.

    Idempotent: if a route pref already exists, do nothing.
    """
    if len(agents) != 1:
        return
    existing = await store.get_route_pref("discord", scope_id)
    if existing is not None:
        return
    await store.set_route_pref("discord", scope_id, agents[0])


def render_welcome(message: str | None, agents: list[str]) -> str:
    """Build the welcome string posted when bot joins a guild/channel."""
    if message:
        return message
    if len(agents) == 1:
        return (
            f"Hi! I'm here with agent **{agents[0]}**. "
            "Mention me to start a conversation."
        )
    if not agents:
        return (
            "Hi! No agents are configured for this Vystak deployment yet. "
            "Use `/vystak route` to bind one."
        )
    listed = ", ".join(f"`{a}`" for a in agents)
    return (
        f"Hi! I have multiple agents available: {listed}. "
        "Use `/vystak route <agent>` to bind one to this channel."
    )
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest packages/python/vystak-channel-discord/tests/test_welcome.py -v
```

Expected: 3 PASSED.

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-channel-discord/
git commit -m "feat(channel-discord): add welcome message + single-agent auto-bind"
```

---

### Task 4.8: Discord threads helper (`threads.py`)

**Files:**
- Create: `packages/python/vystak-channel-discord/src/vystak_channel_discord/threads.py`
- Create: `packages/python/vystak-channel-discord/tests/test_threads.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_threads.py`:

```python
"""Tests for Discord thread + forum detection."""

from vystak_channel_discord.threads import (
    is_forum_channel,
    is_thread_channel,
    should_respond_in_thread,
)


def test_is_thread_channel():
    assert is_thread_channel("thread") is True
    assert is_thread_channel("forum") is False
    assert is_thread_channel("text") is False


def test_is_forum_channel():
    assert is_forum_channel("forum") is True
    assert is_forum_channel("thread") is False


def test_should_respond_in_thread_when_no_explicit_required():
    assert should_respond_in_thread(
        require_explicit_mention=False, mentions_bot=False, is_in_thread=True
    ) is True


def test_should_not_respond_in_thread_when_explicit_required_and_no_mention():
    assert should_respond_in_thread(
        require_explicit_mention=True, mentions_bot=False, is_in_thread=True
    ) is False


def test_should_respond_in_thread_when_explicit_required_with_mention():
    assert should_respond_in_thread(
        require_explicit_mention=True, mentions_bot=True, is_in_thread=True
    ) is True


def test_top_level_message_always_routes_through_authorize_pipeline():
    # When NOT in a thread, this helper returns True; the runtime's
    # `mentions_bot`/policy checks govern whether to actually respond.
    assert should_respond_in_thread(
        require_explicit_mention=True, mentions_bot=False, is_in_thread=False
    ) is True
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest packages/python/vystak-channel-discord/tests/test_threads.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement `threads.py`**

Create `packages/python/vystak-channel-discord/src/vystak_channel_discord/threads.py`:

```python
"""Discord native-thread + forum-channel helpers."""

from __future__ import annotations


def is_thread_channel(channel_type: str | None) -> bool:
    return channel_type == "thread"


def is_forum_channel(channel_type: str | None) -> bool:
    return channel_type == "forum"


def should_respond_in_thread(
    *,
    require_explicit_mention: bool,
    mentions_bot: bool,
    is_in_thread: bool,
) -> bool:
    """Apply the thread.require_explicit_mention policy.

    If the message is not in a thread, this helper returns True; the runtime's
    main authorize pipeline still applies. Inside a thread:
      * require_explicit_mention=False -> always True (follow the thread)
      * require_explicit_mention=True  -> only when the bot is mentioned
    """
    if not is_in_thread:
        return True
    if not require_explicit_mention:
        return True
    return mentions_bot
```

- [ ] **Step 4: Wire `should_respond_in_thread` into the runtime**

In `runtime.py`, override `authorize` to consult the helper for in-thread messages:

```python
    async def authorize(self, event: InboundEvent) -> bool:
        from vystak_channel_discord.threads import (
            is_forum_channel,
            is_thread_channel,
            should_respond_in_thread,
        )
        if not await super().authorize(event):
            return False
        chan_type = event.metadata.get("channel_type")
        is_in_thread = is_thread_channel(chan_type) or is_forum_channel(chan_type) or (
            event.metadata.get("raw_message") is not None
            and getattr(event.metadata["raw_message"], "thread", None) is not None
        )
        require_mention = (
            self.config.get("thread", {}).get("require_explicit_mention", False)
        )
        return should_respond_in_thread(
            require_explicit_mention=require_mention,
            mentions_bot=event.mentions_bot,
            is_in_thread=is_in_thread,
        )
```

- [ ] **Step 5: Run test to verify it passes**

```bash
uv run pytest packages/python/vystak-channel-discord/tests/test_threads.py -v
uv run pytest packages/python/vystak-channel-discord/tests/test_runtime.py -v
```

Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add packages/python/vystak-channel-discord/
git commit -m "feat(channel-discord): add thread + forum helpers and wire require_explicit_mention"
```

---

### Task 4.9: Wire commands + welcome into `start()` and create `__main__.py`

**Files:**
- Modify: `packages/python/vystak-channel-discord/src/vystak_channel_discord/runtime.py`
- Create: `packages/python/vystak-channel-discord/src/vystak_channel_discord/__main__.py`

- [ ] **Step 1: Wire slash commands and welcome into `start()`**

In `runtime.py`, extend the `start()` body. Add after the `on_message`/`on_interaction` handler registrations:

```python
        from discord import app_commands
        from vystak_channel_discord import commands as cmd
        from vystak_channel_discord.welcome import auto_bind_single_agent, render_welcome

        if self.config.get("register_slash_commands", True):
            tree = app_commands.CommandTree(self._client)

            @tree.command(name="vystak-route", description="Bind this channel to an agent")
            async def _route(interaction, agent: str):  # noqa: ANN001
                scope_id = self._scope_id_from_interaction(interaction)
                thread_id = f"{scope_id}:"
                msg = await cmd.handle_route(self.store, scope_id, thread_id, agent)
                await interaction.response.send_message(msg, ephemeral=True)

            @tree.command(name="vystak-unroute", description="Remove channel routing")
            async def _unroute(interaction):  # noqa: ANN001
                scope_id = self._scope_id_from_interaction(interaction)
                thread_id = f"{scope_id}:"
                msg = await cmd.handle_unroute(self.store, scope_id, thread_id)
                await interaction.response.send_message(msg, ephemeral=True)

            @tree.command(name="vystak-prefer", description="Set DM/per-scope preference")
            async def _prefer(interaction, agent: str):  # noqa: ANN001
                scope_id = self._scope_id_from_interaction(interaction)
                msg = await cmd.handle_prefer(self.store, scope_id, agent)
                await interaction.response.send_message(msg, ephemeral=True)

            @tree.command(name="vystak-unprefer", description="Remove preference")
            async def _unprefer(interaction):  # noqa: ANN001
                scope_id = self._scope_id_from_interaction(interaction)
                msg = await cmd.handle_unprefer(self.store, scope_id)
                await interaction.response.send_message(msg, ephemeral=True)

            @tree.command(name="vystak-status", description="Show current routing")
            async def _status(interaction):  # noqa: ANN001
                scope_id = self._scope_id_from_interaction(interaction)
                msg = await cmd.handle_status(self.store, scope_id)
                await interaction.response.send_message(msg, ephemeral=True)

            await tree.sync()

        @self._client.event
        async def on_guild_join(guild):  # noqa: ANN001
            scope_id = f"{guild.id}/{getattr(getattr(guild, 'system_channel', None), 'id', '0')}"
            await auto_bind_single_agent(
                self.store, scope_id, self.config.get("agents", [])
            )
            text = render_welcome(self.config.get("welcome_message"), self.config.get("agents", []))
            sys_chan = getattr(guild, "system_channel", None)
            if sys_chan is not None:
                try:
                    await sys_chan.send(text)
                except Exception:  # noqa: BLE001
                    logger.warning("welcome send failed", exc_info=True)
```

Add the helper at the bottom of the class:

```python
    @staticmethod
    def _scope_id_from_interaction(interaction) -> str:
        guild_id = getattr(interaction, "guild_id", None)
        channel_id = getattr(interaction, "channel_id", None)
        if guild_id is None:
            user_id = getattr(getattr(interaction, "user", None), "id", "?")
            return f"dm/{user_id}"
        return f"{guild_id}/{channel_id}"
```

- [ ] **Step 2: Create `__main__.py`**

```python
"""Discord channel container entrypoint."""

from __future__ import annotations

import json
import os
from pathlib import Path

from vystak_channel_runtime import launch
from vystak_channel_discord.runtime import DiscordChannelRuntime


def main() -> None:
    cfg_dir = Path(os.environ.get("VYSTAK_CONFIG_DIR", "/etc/vystak"))
    config = json.loads((cfg_dir / "channel_config.json").read_text())
    routes_path = cfg_dir / "routes.json"
    routes = json.loads(routes_path.read_text()) if routes_path.exists() else {}
    launch(DiscordChannelRuntime, config=config, routes=routes)


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Smoke importability**

```bash
uv run python -c "from vystak_channel_discord.__main__ import main; print('ok')"
```

Expected: prints `ok`.

- [ ] **Step 4: Re-run all Discord tests**

```bash
uv run pytest packages/python/vystak-channel-discord/ -v
```

Expected: all PASS.

- [ ] **Step 5: Lint**

```bash
uv run ruff check packages/python/vystak-channel-discord/
```

Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add packages/python/vystak-channel-discord/
git commit -m "feat(channel-discord): wire slash commands + on_guild_join + __main__ entrypoint"
```

---

### Task 4.10: Discord `/test/event` integration smoke test

**Files:**
- Create: `packages/python/vystak-channel-discord/tests/test_test_endpoint.py`

- [ ] **Step 1: Write the test**

Create `tests/test_test_endpoint.py`:

```python
"""Synthetic /test/event smoke for DiscordChannelRuntime."""

import pytest
from fastapi.testclient import TestClient
from vystak.schema.common import ChannelType
from vystak_channel_discord.runtime import DiscordChannelRuntime
from vystak_channel_runtime.store import MemoryChannelStore
from vystak_channel_runtime.test_endpoint import build_test_app
from vystak_channel_runtime.types import AgentReply


class _FakeAgent:
    async def send_turn(self, *a, **kw):
        return AgentReply(text="sync ack")
    async def stream_turn(self, *a, **kw):
        raise NotImplementedError


def test_test_endpoint_dispatches_into_discord_runtime():
    rt = DiscordChannelRuntime(
        config={
            "channel_type": "discord",
            "agent_protocol": "a2a-turn",
            "default_agent": "hero",
            "group_policy": "open",
            "dm_policy": "open",
            "agents": ["hero"],
            "register_slash_commands": False,
        },
        routes={"hero": {"address": "http://hero:8000"}},
        store=MemoryChannelStore(),
        agent_client=_FakeAgent(),
    )
    posted = []
    async def fake_post_reply(event, route, reply):
        posted.append((event.scope_id, route, reply.text))
    rt.post_reply = fake_post_reply  # type: ignore[assignment]

    # parse_event() expects metadata['raw_message']; bypass by overriding for the test.
    def fake_parse(raw):
        from vystak_channel_runtime.types import InboundEvent
        return InboundEvent(**raw)
    rt.parse_event = fake_parse  # type: ignore[assignment]

    app = build_test_app(rt)
    client = TestClient(app)
    resp = client.post(
        "/test/event",
        json={
            "channel_type": ChannelType.DISCORD.value,
            "scope_id": "100/200",
            "thread_id": "T:1",
            "user_id": "U1",
            "text": "hi",
            "is_dm": False,
            "mentions_bot": True,
            "metadata": {},
        },
    )
    assert resp.status_code == 200
    assert posted == [("100/200", "hero", "sync ack")]
```

- [ ] **Step 2: Run the test**

```bash
uv run pytest packages/python/vystak-channel-discord/tests/test_test_endpoint.py -v
```

Expected: 1 PASSED.

- [ ] **Step 3: Commit**

```bash
git add packages/python/vystak-channel-discord/tests/test_test_endpoint.py
git commit -m "test(channel-discord): synthetic /test/event end-to-end smoke"
```

---

## Phase 5: Release tests + docs + CHANGELOG

### Task 5.1: Add `release_discord` pytest marker

**Files:**
- Modify: `pyproject.toml` (root) — register the marker.
- Create: `packages/python/vystak-channel-discord/tests/release/__init__.py`
- Create: `packages/python/vystak-channel-discord/tests/release/conftest.py`

- [ ] **Step 1: Register the marker**

In root `pyproject.toml`, locate the `[tool.pytest.ini_options]` section's `markers = [...]` list and append:

```toml
    "release_discord: Discord release-cell tests gated on DISCORD_BOT_TOKEN",
```

- [ ] **Step 2: Create the release test conftest**

```bash
mkdir -p packages/python/vystak-channel-discord/tests/release
```

Create `packages/python/vystak-channel-discord/tests/release/__init__.py` (empty).

Create `packages/python/vystak-channel-discord/tests/release/conftest.py`:

```python
"""Release-cell fixtures for vystak-channel-discord."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def discord_token():
    tok = os.environ.get("DISCORD_BOT_TOKEN")
    if not tok:
        pytest.skip("DISCORD_BOT_TOKEN not set")
    return tok


@pytest.fixture
def project(tmp_path: Path):
    """A tmp project dir with a sentinel .env and guaranteed teardown."""
    proj = tmp_path / "discord-cell"
    proj.mkdir()
    (proj / ".env").write_text(
        "ANTHROPIC_API_KEY=test-key\nANTHROPIC_API_URL=https://invalid.local\n"
    )
    yield proj
    if shutil.which("vystak"):
        subprocess.run(["vystak", "destroy", "-y"], cwd=proj, check=False)
```

- [ ] **Step 3: Verify the marker is recognised**

```bash
uv run pytest --markers | grep release_discord
```

Expected: shows `release_discord: Discord release-cell tests gated on DISCORD_BOT_TOKEN`.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml packages/python/vystak-channel-discord/tests/release/
git commit -m "test(channel-discord): register release_discord marker + release conftest"
```

---

### Task 5.2: Release cell D9 — default chat-over-HTTP

**Files:**
- Create: `packages/python/vystak-channel-discord/tests/release/test_D9_discord_default_chat_http.py`

- [ ] **Step 1: Write the cell**

Create the file:

```python
"""D9: Discord default chat over HTTP — V1 plan, V2 apply, V4 health, V9 destroy."""

import json
import subprocess

import pytest


@pytest.mark.release_smoke
@pytest.mark.docker
def test_D9_discord_default_chat_http(project, discord_token):
    """Deploy a single-agent Discord channel; verify health, then destroy."""
    (project / "agent.yaml").write_text(
        """\
name: hero
model: anthropic/claude-haiku-4-5-20251001
adapter: langchain
provider: docker
channels:
  - name: discord-prod
    type: discord
    agents: [hero]
    default_agent: hero
"""
    )

    plan = subprocess.run(
        ["vystak", "plan"], cwd=project, capture_output=True, text=True, timeout=60,
    )
    assert plan.returncode == 0, plan.stderr

    apply = subprocess.run(
        ["vystak", "apply", "-y"],
        cwd=project,
        capture_output=True, text=True, timeout=300,
        env={
            **__import__("os").environ,
            "DISCORD_BOT_TOKEN": discord_token,
        },
    )
    assert apply.returncode == 0, apply.stderr

    status = subprocess.run(
        ["vystak", "status", "--json"],
        cwd=project, capture_output=True, text=True, timeout=30,
    )
    parsed = json.loads(status.stdout)
    discord_entries = [e for e in parsed.get("channels", []) if e.get("type") == "discord"]
    assert discord_entries, "no discord channel reported in status"
    assert all(e.get("health") == "ok" for e in discord_entries)

    destroy = subprocess.run(
        ["vystak", "destroy", "-y"],
        cwd=project, capture_output=True, text=True, timeout=120,
    )
    assert destroy.returncode == 0, destroy.stderr
```

- [ ] **Step 2: Verify it auto-skips without token**

```bash
uv run pytest packages/python/vystak-channel-discord/tests/release/test_D9_discord_default_chat_http.py -v -m release_smoke
```

Expected: SKIPPED (no DISCORD_BOT_TOKEN).

- [ ] **Step 3: Commit**

```bash
git add packages/python/vystak-channel-discord/tests/release/test_D9_discord_default_chat_http.py
git commit -m "test(channel-discord): add D9 release cell — default chat-over-HTTP"
```

---

### Task 5.3: Release cells D10 (DM), D11 (threads), D12 (Postgres)

**Files:**
- Create: `packages/python/vystak-channel-discord/tests/release/test_D10_discord_dm_chat_http.py`
- Create: `packages/python/vystak-channel-discord/tests/release/test_D11_discord_threads.py`
- Create: `packages/python/vystak-channel-discord/tests/release/test_D12_discord_postgres.py`

- [ ] **Step 1: Write D10**

Create `tests/release/test_D10_discord_dm_chat_http.py`:

```python
"""D10: Discord DM-only flow — V1 plan, V2 apply, V4 health, V9 destroy."""

import json
import subprocess

import pytest


@pytest.mark.release_integration
@pytest.mark.docker
def test_D10_discord_dm_chat_http(project, discord_token):
    (project / "agent.yaml").write_text(
        """\
name: hero
model: anthropic/claude-haiku-4-5-20251001
adapter: langchain
provider: docker
channels:
  - name: discord-prod
    type: discord
    agents: [hero]
    default_agent: hero
    group_policy: disabled
    dm_policy: open
"""
    )
    apply = subprocess.run(
        ["vystak", "apply", "-y"],
        cwd=project, capture_output=True, text=True, timeout=300,
        env={**__import__("os").environ, "DISCORD_BOT_TOKEN": discord_token},
    )
    assert apply.returncode == 0, apply.stderr
    status = subprocess.run(
        ["vystak", "status", "--json"], cwd=project,
        capture_output=True, text=True, timeout=30,
    )
    parsed = json.loads(status.stdout)
    assert any(c.get("type") == "discord" for c in parsed.get("channels", []))
    subprocess.run(["vystak", "destroy", "-y"], cwd=project, check=True, timeout=120)
```

- [ ] **Step 2: Write D11**

Create `tests/release/test_D11_discord_threads.py`:

```python
"""D11: Discord threaded reply — exercises fetch_history + after_reply binding."""

import json
import subprocess

import pytest


@pytest.mark.release_integration
@pytest.mark.docker
def test_D11_discord_threads(project, discord_token):
    (project / "agent.yaml").write_text(
        """\
name: hero
model: anthropic/claude-haiku-4-5-20251001
adapter: langchain
provider: docker
channels:
  - name: discord-prod
    type: discord
    agents: [hero]
    default_agent: hero
    thread:
      initial_history_limit: 10
      require_explicit_mention: false
"""
    )
    apply = subprocess.run(
        ["vystak", "apply", "-y"],
        cwd=project, capture_output=True, text=True, timeout=300,
        env={**__import__("os").environ, "DISCORD_BOT_TOKEN": discord_token},
    )
    assert apply.returncode == 0, apply.stderr
    status = subprocess.run(
        ["vystak", "status", "--json"], cwd=project,
        capture_output=True, text=True, timeout=30,
    )
    parsed = json.loads(status.stdout)
    assert any(c.get("type") == "discord" for c in parsed.get("channels", []))
    subprocess.run(["vystak", "destroy", "-y"], cwd=project, check=True, timeout=120)
```

- [ ] **Step 3: Write D12**

Create `tests/release/test_D12_discord_postgres.py`:

```python
"""D12: Discord with Postgres ChannelStore — exercises new shared schema."""

import json
import subprocess

import pytest


@pytest.mark.release_integration
@pytest.mark.docker
def test_D12_discord_postgres(project, discord_token):
    (project / "agent.yaml").write_text(
        """\
name: hero
model: anthropic/claude-haiku-4-5-20251001
adapter: langchain
provider: docker
channels:
  - name: discord-prod
    type: discord
    agents: [hero]
    default_agent: hero
    state:
      type: postgres
      dsn_secret: pg_dsn
secrets:
  - name: pg_dsn
    value: postgresql://postgres:vystakpw@vystak-data:5432/postgres
"""
    )
    apply = subprocess.run(
        ["vystak", "apply", "-y"],
        cwd=project, capture_output=True, text=True, timeout=300,
        env={**__import__("os").environ, "DISCORD_BOT_TOKEN": discord_token},
    )
    assert apply.returncode == 0, apply.stderr
    status = subprocess.run(
        ["vystak", "status", "--json"], cwd=project,
        capture_output=True, text=True, timeout=30,
    )
    parsed = json.loads(status.stdout)
    assert any(c.get("type") == "discord" for c in parsed.get("channels", []))
    subprocess.run(["vystak", "destroy", "-y"], cwd=project, check=True, timeout=120)
```

- [ ] **Step 4: Verify auto-skip without token**

```bash
uv run pytest packages/python/vystak-channel-discord/tests/release/ -v
```

Expected: all SKIPPED (no DISCORD_BOT_TOKEN).

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-channel-discord/tests/release/
git commit -m "test(channel-discord): add D10/D11/D12 release cells (DM, threads, postgres)"
```

---

### Task 5.4: Discord docs page

**Files:**
- Create: `website/docs/channels/discord.md`

- [ ] **Step 1: Confirm docs site path**

```bash
ls website/docs/channels/ 2>&1 || ls website/docs/ 2>&1 | head -20
```

If `channels/` does not exist under `website/docs/`, create it.

- [ ] **Step 2: Write the docs page**

Create `website/docs/channels/discord.md`:

```markdown
---
title: Discord
sidebar_position: 3
---

# Discord channel

The Discord channel runs a Vystak bot connected to Discord's gateway over
WebSocket. Mention the bot in a guild text channel, DM it, or start a
thread — all messages route to your agents.

## Setup

1. Create a Discord application: <https://discord.com/developers/applications>.
2. Add a bot user to the application. Copy the bot token (you will use it as
   `DISCORD_BOT_TOKEN`).
3. Enable the **`MESSAGE CONTENT`** privileged intent in the bot settings.
   This is required to read message content (it is a one-checkbox setup;
   Discord verifies bots once they reach 100+ guilds).
4. Invite the bot to a server with at least the **`Send Messages`**, **`Read
   Message History`**, and **`Use Slash Commands`** permissions.

## Configuration

Add a Discord channel to your `agent.yaml`:

```yaml
name: hero
model: anthropic/claude-haiku-4-5-20251001
adapter: langchain
provider: docker
channels:
  - name: discord-prod
    type: discord
    agents: [hero]
    default_agent: hero
    # Optional:
    group_policy: open
    dm_policy: open
    thread:
      initial_history_limit: 20
      require_explicit_mention: false
    register_slash_commands: true
    welcome_message: "Hi! I'm Vystak. Mention me to start."
```

Pass the bot token via the host environment when running `vystak apply`:

```bash
export DISCORD_BOT_TOKEN=...
vystak apply
```

## Slash commands

Once the bot is in your server, the following slash commands are available
(they show up in Discord's UI as `/vystak-route`, `/vystak-status`, etc.):

| Command           | Purpose                              |
|-------------------|--------------------------------------|
| `/vystak-route`   | Bind this channel/thread to an agent |
| `/vystak-unroute` | Remove the binding                   |
| `/vystak-prefer`  | Set a default agent for this scope   |
| `/vystak-unprefer`| Remove the preference                |
| `/vystak-status`  | Show current routing                 |

## Threads + forum channels

Discord native threads and forum channels are treated the same way Slack
threads are: when a thread is bound (either explicitly with `/vystak-route`
or implicitly after the first reply), subsequent thread replies go to the
same agent. Set `thread.require_explicit_mention: true` to require an
@mention for follow-up replies.

## Limits

The Discord channel splits replies longer than 2000 characters into multiple
messages (Discord's per-message limit). Streaming and status reactions are
not yet supported.
```

- [ ] **Step 3: Commit**

```bash
git add website/docs/channels/discord.md
git commit -m "docs(channels): add Discord channel setup guide"
```

---

### Task 5.5: ChannelRuntime internals docs page

**Files:**
- Create: `website/docs/channels/internals.md`

- [ ] **Step 1: Write the docs page**

Create `website/docs/channels/internals.md`:

```markdown
---
title: Channel Runtime — Internals
sidebar_position: 99
---

# `vystak-channel-runtime`

`vystak-channel-runtime` is the shared library every channel container uses.
If you want to add a new channel (Telegram, Teams, Matrix, ...), this is
the surface to subclass.

## Architecture

Each channel container imports `vystak_channel_runtime` and runs a subclass
of `ChannelRuntime`. The base class owns the message lifecycle as a
template method:

```
parse_event → authorize → resolve_route → fetch_history
            → before_call → call_agent → post_reply → after_reply
```

`authorize`, `resolve_route`, and `call_agent` are implemented on the base.
`parse_event`, `post_reply`, `start`, and `stop` are abstract — subclasses
implement them. Optional hooks (`fetch_history`, `before_call`,
`after_reply`, `on_no_route`, `on_agent_error`) default to no-ops.

## Writing a new channel

1. Subclass `ChannelRuntime`. Implement `start`, `stop`, `parse_event`,
   `post_reply`. Override optional hooks as needed.
2. Build a `__main__.py` that reads `channel_config.json` and `routes.json`,
   then calls `vystak_channel_runtime.launch(MyRuntime, config, routes)`.
3. Build a `ChannelPlugin` subclass that emits `Dockerfile`,
   `requirements.txt`, `channel_config.json`, `routes.json`. Set
   `entrypoint = "python -m my_package"`.

See `vystak-channel-discord` for a complete example.

## Storage

`ChannelStore` defines a generic interface keyed by
`(channel_type, scope_id, thread_id)`. Default implementations:

- `MemoryChannelStore` — for tests / ephemeral deployments.
- `SqliteChannelStore` — single-file SQLite (`aiosqlite`).
- `PostgresChannelStore` — `asyncpg` pool.

Pick one via `channel_config.json`'s `state` key:

```json
{"state": {"type": "sqlite", "path": "/data/channel.db"}}
```

## Agent client

`AgentClient` is a Protocol. The default `A2AAgentClient` speaks A2A
JSON-RPC over HTTP. To integrate a different protocol (e.g. media bridge for
voice channels), subclass `AgentClient`, then inject it into your runtime
via the `agent_client=` constructor arg.

## Test fixtures

The `/test/event` synthetic-dispatch endpoint, gated by
`VYSTAK_TEST_EVENTS=1`, lets you POST a JSON-shaped `InboundEvent` directly
into your runtime without needing a live platform connection. Used by both
unit and release-cell tests.
```

- [ ] **Step 2: Commit**

```bash
git add website/docs/channels/internals.md
git commit -m "docs(channels): add channel-runtime internals guide for new-channel authors"
```

---

### Task 5.6: CHANGELOG entry

**Files:**
- Modify: `CHANGELOG.md` (create if absent)

- [ ] **Step 1: Confirm CHANGELOG location**

```bash
ls CHANGELOG.md CHANGES.md 2>&1
```

If neither exists, create `CHANGELOG.md` at the repo root.

- [ ] **Step 2: Add the entry**

Prepend (or insert under the `## Unreleased` section, creating it if absent) the following:

```markdown
## Unreleased

### Added

- New package `vystak-channel-runtime` — shared template-method runtime for
  all channel containers (`ChannelRuntime`, `AgentClient`, `ChannelStore`).
- New package `vystak-channel-discord` — Discord channel built on the
  shared runtime. Slack-parity routing, threads, slash commands, single-agent
  auto-bind; streaming and status reactions are deferred.

### Changed

- `vystak-channel-slack` and `vystak-channel-chat` retrofitted onto
  `vystak-channel-runtime`. User-visible behavior preserved.
- Channel containers no longer have generated `server.py` files. Each channel
  package is now a real importable library invoked as
  `python -m vystak_channel_<type>`. The plugin's `generate_code()` emits
  only `Dockerfile`, `requirements.txt`, `channel_config.json`, and
  `routes.json`.

### Breaking

- **Slack thread bindings + route prefs reset on upgrade.** The runtime store
  uses a new generic schema keyed by `(channel_type, scope_id, thread_id)`.
  Existing `routes.db` (SQLite) and `routes` table (Postgres) are ignored.
  Re-route via `/vystak route ...` after upgrade — auto-bind on mention
  repopulates organically.
- **Container entrypoint changed** from `python server.py` to
  `python -m vystak_channel_<type>`. `vystak apply` regenerates the
  Dockerfile so most users will not notice; downstream consumers with custom
  Dockerfiles will need to update.
```

- [ ] **Step 3: Commit**

```bash
git add CHANGELOG.md
git commit -m "docs(changelog): note channel runtime + Discord channel + breaking changes"
```

---

## Phase 6: Hash-tree contributions

### Task 6.1: Add `channel_package_version` + `channel_runtime_version` to hash tree

**Files:**
- Modify: `packages/python/vystak/src/vystak/hash/tree.py`
- Modify: `packages/python/vystak/tests/test_hash_tree.py` (or add)

- [ ] **Step 1: Locate the channel hash contribution site**

```bash
grep -n "channel\|Channel" packages/python/vystak/src/vystak/hash/tree.py | head -30
```

Find the function that hashes a `Channel` (likely a method like `_hash_channel` or inline in `AgentHashTree.build`).

- [ ] **Step 2: Write the failing test**

Add to (or create) `packages/python/vystak/tests/test_hash_tree.py`:

```python
"""Tests for AgentHashTree channel-version contributions."""

from vystak.hash.tree import AgentHashTree
from vystak.schema.agent import Agent
from vystak.schema.channel import Channel
from vystak.schema.common import ChannelType


def _agent(channel_pkg_version="0.1.0", runtime_version="0.1.0"):
    return Agent(
        name="hero",
        model="anthropic/claude-haiku-4-5-20251001",
        adapter="langchain",
        provider="docker",
        channels=[
            Channel(
                name="ch",
                type=ChannelType.SLACK,
                agents=[],
                channel_package_version=channel_pkg_version,
                channel_runtime_version=runtime_version,
            )
        ],
    )


def test_hash_changes_when_channel_package_version_changes():
    h1 = AgentHashTree.build(_agent(channel_pkg_version="0.1.0")).root
    h2 = AgentHashTree.build(_agent(channel_pkg_version="0.2.0")).root
    assert h1 != h2


def test_hash_changes_when_channel_runtime_version_changes():
    h1 = AgentHashTree.build(_agent(runtime_version="0.1.0")).root
    h2 = AgentHashTree.build(_agent(runtime_version="0.2.0")).root
    assert h1 != h2
```

- [ ] **Step 3: Run test to verify it fails**

```bash
uv run pytest packages/python/vystak/tests/test_hash_tree.py -v -k channel_package_version
```

Expected: AttributeError or hash equality failure (versions not contributed yet).

- [ ] **Step 4: Add fields to `Channel` schema**

Edit `packages/python/vystak/src/vystak/schema/channel.py` and add to `Channel`:

```python
    channel_package_version: str | None = None
    channel_runtime_version: str | None = None
```

- [ ] **Step 5: Contribute to the hash**

In `packages/python/vystak/src/vystak/hash/tree.py`, locate the channel-hash function and include `channel_package_version` and `channel_runtime_version` in the JSON-stable dict that goes into the digest. Example pattern (adapt to actual call site):

```python
def _hash_channel(ch: Channel) -> str:
    payload = {
        "type": ch.type,
        "name": ch.name,
        "agents": [a.name for a in ch.agents],
        "default_agent": ch.default_agent.name if ch.default_agent else None,
        "channel_package_version": ch.channel_package_version,
        "channel_runtime_version": ch.channel_runtime_version,
        # ...other existing fields...
    }
    return _digest(payload)
```

(The exact function name and shape will differ; the rule is: every existing channel field already in the hash payload, plus the two new ones.)

- [ ] **Step 6: Run test to verify it passes**

```bash
uv run pytest packages/python/vystak/tests/test_hash_tree.py -v -k channel_package_version
```

Expected: 2 PASSED.

- [ ] **Step 7: Commit**

```bash
git add packages/python/vystak/src/vystak/schema/channel.py packages/python/vystak/src/vystak/hash/tree.py packages/python/vystak/tests/test_hash_tree.py
git commit -m "feat(hash): include channel_package_version + channel_runtime_version in AgentHashTree"
```

---

### Task 6.2: Populate the new versions in each channel plugin's `generate_code`

**Files:**
- Modify: `packages/python/vystak-channel-slack/src/vystak_channel_slack/plugin.py`
- Modify: `packages/python/vystak-channel-chat/src/vystak_channel_chat/plugin.py`
- Modify: `packages/python/vystak-channel-discord/src/vystak_channel_discord/plugin.py`

> **Note:** the versions live on the `Channel` schema field but are populated by the plugin from `importlib.metadata.version()` so the user never sets them by hand. The provider/CLI captures them when building the deploy hash.

- [ ] **Step 1: Add a helper in `vystak-channel-runtime`**

Append to `packages/python/vystak-channel-runtime/src/vystak_channel_runtime/__init__.py`:

```python
from importlib.metadata import version as _pkg_version


def runtime_version() -> str:
    try:
        return _pkg_version("vystak-channel-runtime")
    except Exception:
        return "0.1.0"


def channel_package_version(name: str) -> str:
    try:
        return _pkg_version(name)
    except Exception:
        return "0.1.0"
```

Add `"runtime_version", "channel_package_version"` to `__all__`.

- [ ] **Step 2: Populate in Slack plugin**

In `vystak_channel_slack/plugin.py.generate_code`, after building `channel_config`, also stamp the channel's version fields onto the runtime view:

```python
        from vystak_channel_runtime import channel_package_version, runtime_version

        channel.channel_package_version = channel_package_version("vystak-channel-slack")
        channel.channel_runtime_version = runtime_version()
```

(If `Channel` is frozen / immutable, the plugin instead injects them into `channel_config["channel_package_version"]` and `channel_config["channel_runtime_version"]`, and the hash function reads them from `channel_config` rather than the schema field. Pick whichever the existing schema allows.)

- [ ] **Step 3: Same for Chat + Discord plugins**

Repeat for `vystak_channel_chat/plugin.py` (using package name `vystak-channel-chat`) and `vystak_channel_discord/plugin.py` (using package name `vystak-channel-discord`).

- [ ] **Step 4: Smoke test the plugin output captures versions**

Add a test to each plugin's `tests/test_plugin.py`:

```python
def test_plugin_writes_version_fields():
    out = SlackChannelPlugin().generate_code(_channel(), resolved_routes={})
    import json
    cfg = json.loads(out.files["channel_config.json"])
    assert "channel_package_version" in cfg
    assert "channel_runtime_version" in cfg
```

(Repeat for chat and discord plugin test files.)

- [ ] **Step 5: Run the plugin test suites**

```bash
uv run pytest packages/python/vystak-channel-slack/tests/test_plugin.py packages/python/vystak-channel-chat/tests/test_plugin.py packages/python/vystak-channel-discord/tests/test_plugin.py -v
```

Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add packages/python/vystak-channel-runtime/ packages/python/vystak-channel-slack/ packages/python/vystak-channel-chat/ packages/python/vystak-channel-discord/
git commit -m "feat(channels): stamp channel_package_version + channel_runtime_version into deploy hash"
```

---

## Phase 7: Final wrap

### Task 7.1: Run full CI parity

**Files:**
- (verification only, no edits)

- [ ] **Step 1: Run lint-python**

```bash
just lint-python
```

Expected: clean.

- [ ] **Step 2: Run test-python (excluding docker-marked)**

```bash
just test-python
```

Expected: all PASS.

- [ ] **Step 3: Run typecheck (informational — pre-existing failures in repo)**

```bash
just typecheck-python || true
```

Note: per CLAUDE.md, `typecheck-python` has known pre-existing failures unrelated to this work. Confirm none of the **new** errors are in any file changed by this plan.

- [ ] **Step 4: Run docker-marked Postgres tests against a real container**

```bash
docker run -d --name plan-pg-final -p 55433:5432 -e POSTGRES_PASSWORD=t -e POSTGRES_DB=t postgres:16
sleep 3
export POSTGRES_DSN=postgresql://postgres:t@localhost:55433/t
uv run pytest packages/python/vystak-channel-runtime/tests/ -v -m docker
docker rm -f plan-pg-final
unset POSTGRES_DSN
```

Expected: PASSED.

- [ ] **Step 5: If any step fails, branch back to the relevant task; otherwise commit a wrap message**

```bash
git status
# If anything was tweaked during verification, commit it. Otherwise skip.
```

---

### Task 7.2: Smoke-deploy Discord against a real bot (manual)

**Files:**
- (manual verification — no edits)

> **Note:** this final step requires a real Discord bot token and a Discord server you control. Skip the corresponding sub-steps if you do not have access.

- [ ] **Step 1: Set the token**

```bash
export DISCORD_BOT_TOKEN=...
```

- [ ] **Step 2: Run D9 against the real bot**

```bash
uv run pytest packages/python/vystak-channel-discord/tests/release/test_D9_discord_default_chat_http.py -v -m release_smoke
```

Expected: PASSED. The deploy creates a real container; the bot connects to your Discord server.

- [ ] **Step 3: Manual smoke**

In Discord:
1. Mention the bot in a guild text channel. Confirm it replies.
2. DM the bot. Confirm it replies.
3. Reply in a thread to the bot's first response. Confirm it replies again with thread context.
4. Run `/vystak-status`. Confirm it shows the auto-bound agent.
5. Run `/vystak-route hero` then `/vystak-status`. Confirm the binding.

- [ ] **Step 4: Tear down**

```bash
uv run pytest packages/python/vystak-channel-discord/tests/release/test_D9_discord_default_chat_http.py -v -m release_smoke
# (the cell's destroy fixture cleans up; rerun from scratch to verify idempotent destroy)
```

- [ ] **Step 5: If smoke succeeds, no further commits required**

---
