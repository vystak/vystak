# Panel NATS Transport + Resumable Streaming Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the control panel work on the NATS transport, with resumable streaming: agents publish turn events durably to JetStream; the panel persists and proxies them independently of any browser connection.

**Architecture:** A new `responses/createDetached` RPC makes the agent ack immediately and publish its OpenAI-Responses SSE events as `{seq, event}` messages to a per-turn JetStream subject. The panel spawns a process-owned persister consumer per turn plus per-connection SSE proxy consumers; browsers resume by replaying from seq 0 via a new GET endpoint wired to AI SDK v5's `resume: true`. HTTP transport keeps today's behavior untouched.

**Tech Stack:** Python 3.11 (FastAPI, nats-py ≥2.6, aiosqlite, pytest-asyncio), TypeScript (Next.js, `ai` v5, `@ai-sdk/react` v2).

**Spec:** `docs/superpowers/specs/2026-07-25-panel-nats-resumable-streaming-design.md` (read it first; the "Agent side" section was amended — the agent implementation extends `NatsHttpBridge`, it does NOT use `Transport.serve()`).

## Global Constraints

- Agent images pip-install `vystak` from PyPI and do **not** install `vystak-transport-nats`. Template code (`packages/python/vystak-template-langchain-python/_vystak/`) may only import `nats` (nats-py), stdlib, httpx, and already-released `vystak` core APIs. Never add a `vystak_transport_nats` import to template code.
- Channel images bundle local package source — panel code MAY import `vystak_transport_nats`.
- Naming convention (duplicated in template and `vystak_transport_nats.streams`, keep-in-sync comments both sides): tasks subject `{prefix}.{ns}.agents.{name}.tasks`; stream base = everything before `.agents.`; turn subject `{base}.streams.{conversation_id}.{turn_id}`; JetStream stream name = base with `.`→`-` + `-streams`.
- Stream message envelope: `{"seq": <0-based int>, "event": <OpenAI Responses SSE payload>}`. Terminal events: `event.type` ∈ {`response.completed`, `response.failed`}.
- Resume always replays from seq 0. No `Last-Event-ID`/offset support.
- HTTP transport behavior must not change. Every new panel behavior is gated on `channel_config.json`'s `transport_type == "nats"`.
- Verification gates per task: `just lint-python` and the named pytest commands. `just typecheck-python` is a known-red gate (370 pre-existing errors) — do not try to make it green, just don't add errors to files you touch.
- Run Python tests with `uv run pytest <path> -v` from the repo root.
- Commit after every task with the message given in the task.

---

### Task 1: `vystak-transport-nats` — stream naming + JetStream helpers

**Files:**
- Create: `packages/python/vystak-transport-nats/src/vystak_transport_nats/streams.py`
- Modify: `packages/python/vystak-transport-nats/src/vystak_transport_nats/__init__.py` (add exports)
- Test: `packages/python/vystak-transport-nats/tests/test_streams.py`

**Interfaces:**
- Produces (used by Tasks 7–8):
  - `stream_base(tasks_subject: str) -> str`
  - `stream_name_for_base(base: str) -> str`
  - `turn_subject(base: str, conversation_id: str, turn_id: str) -> str`
  - `is_terminal_event(payload: dict) -> bool`
  - `async ensure_stream(js, base: str, *, max_age_s: float = 3600.0) -> None`
  - `async read_turn_events(nc, subject: str, *, idle_timeout_s: float = 120.0) -> AsyncIterator[dict]` — yields `{"seq", "event"}` payload dicts, returns after a terminal event, raises `TurnStreamIdle` on idle timeout
  - `class TurnStreamIdle(TimeoutError)`

- [ ] **Step 1: Write the failing tests**

```python
# packages/python/vystak-transport-nats/tests/test_streams.py
"""Tests for JetStream turn-stream helpers."""

import asyncio
import json

import pytest
from vystak_transport_nats.streams import (
    TurnStreamIdle,
    ensure_stream,
    is_terminal_event,
    read_turn_events,
    stream_base,
    stream_name_for_base,
    turn_subject,
)


def test_stream_base_from_tasks_subject():
    assert stream_base("vystak.multi.agents.time-agent.tasks") == "vystak.multi"
    assert stream_base("vystak-nats.multi-nats.agents.a.tasks") == "vystak-nats.multi-nats"


def test_stream_base_rejects_non_tasks_subject():
    with pytest.raises(ValueError):
        stream_base("not-a-subject")


def test_stream_name_for_base():
    assert stream_name_for_base("vystak.multi") == "vystak-multi-streams"


def test_turn_subject():
    assert (
        turn_subject("vystak.multi", "conv1", "turnA")
        == "vystak.multi.streams.conv1.turnA"
    )


def test_is_terminal_event():
    assert is_terminal_event({"seq": 3, "event": {"type": "response.completed"}})
    assert is_terminal_event({"seq": 3, "event": {"type": "response.failed"}})
    assert not is_terminal_event({"seq": 0, "event": {"type": "response.created"}})
    assert not is_terminal_event({"seq": 0})


class FakeJS:
    def __init__(self, add_error: Exception | None = None):
        self.add_calls: list = []
        self.update_calls: list = []
        self._add_error = add_error

    async def add_stream(self, cfg):
        self.add_calls.append(cfg)
        if self._add_error:
            raise self._add_error

    async def update_stream(self, cfg):
        self.update_calls.append(cfg)


@pytest.mark.asyncio
async def test_ensure_stream_adds():
    js = FakeJS()
    await ensure_stream(js, "vystak.multi")
    assert len(js.add_calls) == 1
    cfg = js.add_calls[0]
    assert cfg.name == "vystak-multi-streams"
    assert cfg.subjects == ["vystak.multi.streams.>"]
    assert js.update_calls == []


@pytest.mark.asyncio
async def test_ensure_stream_falls_back_to_update_when_exists():
    js = FakeJS(add_error=RuntimeError("stream name already in use"))
    await ensure_stream(js, "vystak.multi")
    assert len(js.update_calls) == 1


class FakeMsg:
    def __init__(self, payload: dict):
        self.data = json.dumps(payload).encode()


class FakeSub:
    def __init__(self, payloads: list[dict], *, then_hang: bool = False):
        self._payloads = list(payloads)
        self._then_hang = then_hang
        self.unsubscribed = False

    async def next_msg(self, timeout: float):
        if self._payloads:
            return FakeMsg(self._payloads.pop(0))
        if self._then_hang:
            import nats.errors

            raise nats.errors.TimeoutError
        raise AssertionError("no more messages")

    async def unsubscribe(self):
        self.unsubscribed = True


class FakeNC:
    def __init__(self, sub: FakeSub):
        self._sub = sub
        self.subscribed_subject: str | None = None

    def jetstream(self):
        return self

    async def subscribe(self, subject, ordered_consumer=False):
        assert ordered_consumer is True
        self.subscribed_subject = subject
        return self._sub


@pytest.mark.asyncio
async def test_read_turn_events_stops_at_terminal():
    sub = FakeSub([
        {"seq": 0, "event": {"type": "response.created"}},
        {"seq": 1, "event": {"type": "response.output_text.delta", "delta": "hi"}},
        {"seq": 2, "event": {"type": "response.completed", "response": {"id": "r1"}}},
        {"seq": 99, "event": {"type": "should-not-be-read"}},
    ])
    nc = FakeNC(sub)
    got = [p async for p in read_turn_events(nc, "vystak.multi.streams.c.t")]
    assert [p["seq"] for p in got] == [0, 1, 2]
    assert nc.subscribed_subject == "vystak.multi.streams.c.t"
    assert sub.unsubscribed


@pytest.mark.asyncio
async def test_read_turn_events_idle_timeout():
    sub = FakeSub([{"seq": 0, "event": {"type": "response.created"}}], then_hang=True)
    nc = FakeNC(sub)
    gen = read_turn_events(nc, "s.streams.c.t", idle_timeout_s=0.01)
    assert (await gen.__anext__())["seq"] == 0
    with pytest.raises(TurnStreamIdle):
        await gen.__anext__()
    assert sub.unsubscribed
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/python/vystak-transport-nats/tests/test_streams.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'vystak_transport_nats.streams'`

- [ ] **Step 3: Write the implementation**

```python
# packages/python/vystak-transport-nats/src/vystak_transport_nats/streams.py
"""JetStream helpers for durable per-turn event streams.

Subject/naming convention — KEEP IN SYNC with the template runtime's copy in
vystak-template-langchain-python/_vystak/runtime/nats_bridge.py (the template
cannot import this package: agent images install vystak from PyPI only):

- tasks subject:  {prefix}.{ns}.agents.{name}.tasks
- stream base:    {prefix}.{ns}                  (everything before ".agents.")
- turn subject:   {base}.streams.{conversation_id}.{turn_id}
- stream name:    base with "." -> "-", plus "-streams"

Every message on a turn subject is ``{"seq": <int>, "event": <payload>}``
where ``event`` is one OpenAI Responses SSE payload. A turn is over when
``event.type`` is ``response.completed`` or ``response.failed``.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import nats.errors
from nats.js.api import RetentionPolicy, StorageType, StreamConfig

DEFAULT_MAX_AGE_S = 3600.0
TERMINAL_EVENT_TYPES = frozenset({"response.completed", "response.failed"})


class TurnStreamIdle(TimeoutError):
    """No event arrived on a turn subject within the idle timeout."""


def stream_base(tasks_subject: str) -> str:
    base, sep, _ = tasks_subject.partition(".agents.")
    if not sep:
        raise ValueError(f"not a tasks subject: {tasks_subject!r}")
    return base


def stream_name_for_base(base: str) -> str:
    return base.replace(".", "-") + "-streams"


def turn_subject(base: str, conversation_id: str, turn_id: str) -> str:
    return f"{base}.streams.{conversation_id}.{turn_id}"


def is_terminal_event(payload: dict[str, Any]) -> bool:
    return (payload.get("event") or {}).get("type") in TERMINAL_EVENT_TYPES


async def ensure_stream(
    js: Any, base: str, *, max_age_s: float = DEFAULT_MAX_AGE_S
) -> None:
    """Idempotently create (or converge) the turn-event stream for *base*."""
    cfg = StreamConfig(
        name=stream_name_for_base(base),
        subjects=[f"{base}.streams.>"],
        retention=RetentionPolicy.LIMITS,
        max_age=max_age_s,
        storage=StorageType.FILE,
    )
    try:
        await js.add_stream(cfg)
    except Exception:  # noqa: BLE001 — nats-py raises server-specific API errors
        # Stream already exists (possibly with an older subject list) —
        # converge via update instead.
        await js.update_stream(cfg)


async def read_turn_events(
    nc: Any, subject: str, *, idle_timeout_s: float = 120.0
) -> AsyncIterator[dict[str, Any]]:
    """Yield ``{"seq", "event"}`` payloads from seq 0 until a terminal event.

    Uses an ordered (ephemeral, deliver-all) JetStream consumer, so every
    caller independently replays the full turn. Raises :class:`TurnStreamIdle`
    when nothing arrives within *idle_timeout_s*.
    """
    js = nc.jetstream()
    sub = await js.subscribe(subject, ordered_consumer=True)
    try:
        while True:
            try:
                msg = await sub.next_msg(timeout=idle_timeout_s)
            except nats.errors.TimeoutError as e:
                raise TurnStreamIdle(subject) from e
            payload = json.loads(msg.data)
            yield payload
            if is_terminal_event(payload):
                return
    finally:
        await sub.unsubscribe()
```

Add to `packages/python/vystak-transport-nats/src/vystak_transport_nats/__init__.py` (match its existing export style):

```python
from vystak_transport_nats.streams import (
    TurnStreamIdle,
    ensure_stream,
    is_terminal_event,
    read_turn_events,
    stream_base,
    stream_name_for_base,
    turn_subject,
)
```
and extend `__all__` with those seven names.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/python/vystak-transport-nats/tests/ -v`
Expected: all PASS (new + pre-existing). If `pytest-asyncio` markers fail, check how `tests/test_nats_transport.py` marks async tests in this package and mirror it.

- [ ] **Step 5: Lint and commit**

```bash
just lint-python && just fmt-python
git add packages/python/vystak-transport-nats
git commit -m "feat(transport-nats): JetStream turn-stream helpers"
```

---

### Task 2: `NatsTransport.create_response_detached` + public connection accessor

**Files:**
- Modify: `packages/python/vystak-transport-nats/src/vystak_transport_nats/transport.py`
- Test: `packages/python/vystak-transport-nats/tests/test_nats_transport.py` (append)

**Interfaces:**
- Produces (used by Task 7):
  - `async NatsTransport.nats_connection() -> NATSClient` — public accessor for the lazily-connected client (needed for JetStream consume; today `_connect` is private)
  - `async NatsTransport.create_response_detached(agent: AgentRef, request: dict, metadata: dict, *, turn_id: str, stream_subject: str, timeout: float) -> dict` — sends `responses/createDetached`, returns the ack result; raises `TimeoutError` on NATS timeout, `RuntimeError` on a JSON-RPC error reply
- Wire format produced (consumed by Task 4's bridge): JSON-RPC envelope, `method="responses/createDetached"`, `params={"request": ..., "turn_id": ..., "stream_subject": ...}`, top-level `metadata`.

- [ ] **Step 1: Write the failing tests** (append to `test_nats_transport.py`; reuse its existing fake-NATS fixtures if present, otherwise this self-contained style):

```python
import json

import pytest
from vystak.transport import AgentRef
from vystak_transport_nats.transport import NatsTransport


class _FakeReply:
    def __init__(self, body: dict):
        self.data = json.dumps(body).encode()


class _FakeNC:
    def __init__(self, reply_body: dict):
        self._reply_body = reply_body
        self.requests: list[tuple[str, dict]] = []
        self.is_closed = False

    async def request(self, subject, payload, timeout):
        self.requests.append((subject, json.loads(payload)))
        return _FakeReply(self._reply_body)


@pytest.mark.asyncio
async def test_create_response_detached_sends_envelope_and_returns_ack():
    t = NatsTransport("nats://ignored:4222")
    fake = _FakeNC({"jsonrpc": "2.0", "id": "x", "result": {"turn_id": "t1", "stream_subject": "s"}})
    t._nc = fake  # bypass real connect
    result = await t.create_response_detached(
        AgentRef(canonical_name="time-agent.agents.multi"),
        {"input": "hi", "stream": True},
        {},
        turn_id="t1",
        stream_subject="vystak.multi.streams.c1.t1",
        timeout=5.0,
    )
    assert result == {"turn_id": "t1", "stream_subject": "s"}
    subject, envelope = fake.requests[0]
    assert subject == "vystak.multi.agents.time-agent.tasks"
    assert envelope["method"] == "responses/createDetached"
    assert envelope["params"]["turn_id"] == "t1"
    assert envelope["params"]["stream_subject"] == "vystak.multi.streams.c1.t1"
    assert envelope["params"]["request"]["input"] == "hi"


@pytest.mark.asyncio
async def test_create_response_detached_raises_on_jsonrpc_error():
    t = NatsTransport("nats://ignored:4222")
    t._nc = _FakeNC({"jsonrpc": "2.0", "id": "x", "error": {"code": -32602, "message": "bad params"}})
    with pytest.raises(RuntimeError, match="bad params"):
        await t.create_response_detached(
            AgentRef(canonical_name="time-agent.agents.multi"),
            {"input": "hi"},
            {},
            turn_id="t1",
            stream_subject="s",
            timeout=5.0,
        )


@pytest.mark.asyncio
async def test_nats_connection_returns_client():
    t = NatsTransport("nats://ignored:4222")
    fake = _FakeNC({})
    t._nc = fake
    assert await t.nats_connection() is fake
```

Note: `t._nc = fake` relies on `_connect()` short-circuiting when `self._nc` is set and not closed — `_FakeNC.is_closed = False` satisfies the check at `transport.py:46`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/python/vystak-transport-nats/tests/test_nats_transport.py -v -k detached`
Expected: FAIL with `AttributeError: 'NatsTransport' object has no attribute 'create_response_detached'`

- [ ] **Step 3: Implement** (append to `NatsTransport`, after `create_response_stream`):

```python
    async def nats_connection(self) -> NATSClient:
        """Public accessor for the lazily-connected NATS client.

        Panel-side consumers need the raw client for JetStream subscribe
        on turn subjects; keeping one connection per transport instance.
        """
        return await self._connect()

    async def create_response_detached(
        self,
        agent: AgentRef,
        request: dict[str, Any],
        metadata: dict[str, Any],
        *,
        turn_id: str,
        stream_subject: str,
        timeout: float,
    ) -> dict[str, Any]:
        """Fire a detached Responses turn.

        The agent acks immediately and then publishes ``{seq, event}``
        chunks to *stream_subject* on JetStream, decoupled from this caller.
        """
        nc = await self._connect()
        subject = self.resolve_address(agent.canonical_name)
        payload = self._build_envelope_for_method(
            "responses/createDetached",
            {"request": request, "turn_id": turn_id, "stream_subject": stream_subject},
            metadata,
        )
        logger.info(
            "tx responses/createDetached subject=%s turn=%s stream=%s",
            subject, turn_id, stream_subject,
        )
        try:
            reply = await nc.request(subject, payload, timeout=timeout)
        except TimeoutError as e:
            raise TimeoutError(
                f"NATS request to {subject} (responses/createDetached) "
                f"timed out after {timeout}s"
            ) from e
        body = json.loads(reply.data)
        if body.get("error"):
            raise RuntimeError(
                f"responses/createDetached failed: {body['error'].get('message')}"
            )
        return body.get("result", {})
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/python/vystak-transport-nats/tests/ -v`
Expected: all PASS

- [ ] **Step 5: Lint and commit**

```bash
just lint-python
git add packages/python/vystak-transport-nats
git commit -m "feat(transport-nats): responses/createDetached client + public connection accessor"
```

---

### Task 3: Template bridge — proxy `responses/create` and `responses/get`

**Files:**
- Modify: `packages/python/vystak-template-langchain-python/_vystak/runtime/nats_bridge.py`
- Test: `packages/python/vystak-template-langchain-python/tests/test_nats_bridge.py` (append; follow the file's existing fake-msg/fake-nc patterns)

**Interfaces:**
- `NatsHttpBridge.__init__` gains keyword arg `local_base: str` (e.g. `http://localhost:8000`). The existing `local_url` (the `/a2a` URL) stays for backward compat with existing tests, but `maybe_build_bridge` now passes both: `local_base=f"http://localhost:{port}"`, `local_url=f"http://localhost:{port}/a2a"`.
- New wire behavior (consumed by `NatsTransport.create_response` / `get_response` which already send these methods): `responses/create` → `{jsonrpc, id, result: <response object>}` reply; `responses/get` → `{jsonrpc, id, result: <response object | null>}`.

- [ ] **Step 1: Write the failing tests.** Mirror the existing test file's fakes. If it has no reusable fakes, add:

```python
import json

import httpx
import pytest

from _vystak.runtime.nats_bridge import NatsHttpBridge


class RecordingNC:
    def __init__(self):
        self.published: list[tuple[str, dict]] = []

    async def publish(self, subject, payload):
        self.published.append((subject, json.loads(payload)))


class FakeMsg:
    def __init__(self, envelope: dict, reply: str = "_INBOX.r1"):
        self.data = json.dumps(envelope).encode()
        self.reply = reply
        self.subject = "vystak.multi.agents.a.tasks"


def _bridge_with_mock_http(handler) -> tuple[NatsHttpBridge, RecordingNC]:
    bridge = NatsHttpBridge(
        nats_url="nats://ignored:4222",
        subject="vystak.multi.agents.a.tasks",
        queue_group="agents.a",
        local_url="http://localhost:8000/a2a",
        local_base="http://localhost:8000",
    )
    bridge._nc = RecordingNC()
    bridge._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return bridge, bridge._nc


@pytest.mark.asyncio
async def test_responses_create_proxies_to_local_v1_responses():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"id": "resp_1", "status": "completed"})

    bridge, nc = _bridge_with_mock_http(handler)
    env = {"jsonrpc": "2.0", "id": "42", "method": "responses/create",
           "params": {"request": {"input": "hi", "stream": True}}}
    await bridge._forward(FakeMsg(env))

    assert seen["url"] == "http://localhost:8000/v1/responses"
    assert seen["body"]["stream"] is False  # forced non-stream
    subject, reply = nc.published[0]
    assert subject == "_INBOX.r1"
    assert reply["result"]["id"] == "resp_1"
    assert reply["id"] == "42"


@pytest.mark.asyncio
async def test_responses_get_proxies_and_maps_404_to_null_result():
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "http://localhost:8000/v1/responses/resp_x"
        return httpx.Response(404, json={"detail": "not found"})

    bridge, nc = _bridge_with_mock_http(handler)
    env = {"jsonrpc": "2.0", "id": "43", "method": "responses/get",
           "params": {"response_id": "resp_x"}}
    await bridge._forward(FakeMsg(env))

    _, reply = nc.published[0]
    assert reply["result"] is None
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest packages/python/vystak-template-langchain-python/tests/test_nats_bridge.py -v -k responses`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'local_base'` (or the a2a-forward path replying with an a2a-shaped body instead of a Responses result)

- [ ] **Step 3: Implement.** In `nats_bridge.py`:

1. Constructor: add `local_base: str = ""` keyword; store `self._local_base = local_base or local_url.removesuffix("/a2a")`.
2. `maybe_build_bridge`: pass `local_base=f"http://localhost:{port}"`.
3. In `_forward`, after `method = envelope.get("method", "?")` is read, insert routing **before** the existing trace-context /a2a forwarding:

```python
            if method == "responses/create":
                await self._handle_responses_create(envelope, reply_subject)
                return
            if method == "responses/get":
                await self._handle_responses_get(envelope, reply_subject)
                return
```

4. New methods on the class:

```python
    async def _handle_responses_create(self, envelope: dict, reply_subject: str) -> None:
        """Proxy responses/create to the local /v1/responses (non-stream)."""
        request = dict((envelope.get("params") or {}).get("request") or {})
        request["stream"] = False
        assert self._http is not None
        try:
            resp = await self._http.post(f"{self._local_base}/v1/responses", json=request)
            resp.raise_for_status()
            result = resp.json()
        except Exception as e:  # noqa: BLE001 — reply with JSON-RPC error, never raise
            await self._publish_error_async(
                reply_subject, code=-32603,
                message=f"responses/create failed: {e}",
                request_id=envelope.get("id"),
            )
            return
        reply = {"jsonrpc": "2.0", "id": envelope.get("id"), "result": result}
        if reply_subject:
            await self._nc.publish(reply_subject, json.dumps(reply).encode())

    async def _handle_responses_get(self, envelope: dict, reply_subject: str) -> None:
        """Proxy responses/get to the local GET /v1/responses/{id}."""
        response_id = (envelope.get("params") or {}).get("response_id") or ""
        assert self._http is not None
        result = None
        try:
            resp = await self._http.get(f"{self._local_base}/v1/responses/{response_id}")
            if resp.status_code == 200:
                result = resp.json()
            elif resp.status_code != 404:
                resp.raise_for_status()
        except Exception as e:  # noqa: BLE001
            await self._publish_error_async(
                reply_subject, code=-32603,
                message=f"responses/get failed: {e}",
                request_id=envelope.get("id"),
            )
            return
        reply = {"jsonrpc": "2.0", "id": envelope.get("id"), "result": result}
        if reply_subject:
            await self._nc.publish(reply_subject, json.dumps(reply).encode())
```

- [ ] **Step 4: Run the template test suite**

Run: `uv run pytest packages/python/vystak-template-langchain-python/tests/test_nats_bridge.py -v`
Expected: all PASS (existing a2a-forward tests must still pass — the new routing only intercepts the two Responses methods)

- [ ] **Step 5: Sync the vendored example runtime and commit.** The `examples/docker-panel/_vystak` tree vendors this runtime; parity is tested by `test_codegen_parity.py`. Run it:

Run: `uv run pytest packages/python/vystak-template-langchain-python/tests/test_codegen_parity.py -v`
If it fails on the changed file, copy the modified `nats_bridge.py` over the example copies it names (e.g. `cp packages/python/vystak-template-langchain-python/_vystak/runtime/nats_bridge.py examples/docker-panel/_vystak/runtime/nats_bridge.py`) and re-run.

```bash
just lint-python
git add packages/python/vystak-template-langchain-python examples/*/_vystak/runtime/nats_bridge.py
git commit -m "feat(template): proxy responses/create + responses/get over the NATS bridge"
```

---

### Task 4: Template bridge — `responses/createDetached` + JetStream publisher

**Files:**
- Modify: `packages/python/vystak-template-langchain-python/_vystak/runtime/nats_bridge.py`
- Test: `packages/python/vystak-template-langchain-python/tests/test_nats_bridge.py` (append)

**Interfaces:**
- Wire behavior (consumed by Task 2's client): on `responses/createDetached` with `params.{request, turn_id, stream_subject}` the bridge (1) replies `{jsonrpc, id, result: {turn_id, stream_subject}}` immediately, (2) spawns a tracked task that POSTs `{**request, "stream": true}` to `{local_base}/v1/responses`, parses SSE `data:` lines, and publishes each parsed event as `{"seq": n, "event": event}` to `stream_subject` via `js.publish()`. `[DONE]` ends the task. Any failure publishes a synthesized `response.failed` terminal event.
- Missing params → JSON-RPC error `-32602`, no task spawned.
- Local naming helpers `_stream_base_of_turn_subject(subject)` and `_ensure_turn_stream(js, base)` — duplicated from `vystak_transport_nats.streams` with keep-in-sync comments (Global Constraints: template must not import that package).

- [ ] **Step 1: Write the failing tests** (append; reuses Task 3's `RecordingNC`/`FakeMsg`/`_bridge_with_mock_http`):

```python
import asyncio


class RecordingJS:
    def __init__(self):
        self.published: list[tuple[str, dict]] = []
        self.streams_added: list = []

    async def add_stream(self, cfg):
        self.streams_added.append(cfg)

    async def update_stream(self, cfg):
        pass

    async def publish(self, subject, payload):
        self.published.append((subject, json.loads(payload)))


def _sse_bytes(*events: dict, done: bool = True) -> bytes:
    lines = [f"data: {json.dumps(e)}\n\n" for e in events]
    if done:
        lines.append("data: [DONE]\n\n")
    return "".join(lines).encode()


@pytest.mark.asyncio
async def test_create_detached_acks_then_publishes_stream_to_jetstream():
    sse = _sse_bytes(
        {"type": "response.created", "response": {"id": "r1"}},
        {"type": "response.output_text.delta", "delta": "hel"},
        {"type": "response.output_text.delta", "delta": "lo"},
        {"type": "response.completed", "response": {"id": "r1"}},
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "http://localhost:8000/v1/responses"
        assert json.loads(request.content)["stream"] is True
        return httpx.Response(200, content=sse, headers={"content-type": "text/event-stream"})

    bridge, nc = _bridge_with_mock_http(handler)
    js = RecordingJS()
    nc.jetstream = lambda: js  # RecordingNC gains jetstream() for this test

    env = {"jsonrpc": "2.0", "id": "7", "method": "responses/createDetached",
           "params": {"request": {"input": "hi"}, "turn_id": "t1",
                      "stream_subject": "vystak.multi.streams.c1.t1"}}
    await bridge._forward(FakeMsg(env))
    # ack must be immediate and correct
    _, ack = nc.published[0]
    assert ack["result"] == {"turn_id": "t1", "stream_subject": "vystak.multi.streams.c1.t1"}
    # drain the detached task
    await asyncio.gather(*bridge._inflight)

    assert js.streams_added and js.streams_added[0].name == "vystak-multi-streams"
    subjects = {s for s, _ in js.published}
    assert subjects == {"vystak.multi.streams.c1.t1"}
    payloads = [p for _, p in js.published]
    assert [p["seq"] for p in payloads] == [0, 1, 2, 3]
    assert payloads[-1]["event"]["type"] == "response.completed"


@pytest.mark.asyncio
async def test_create_detached_publishes_failed_event_on_http_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    bridge, nc = _bridge_with_mock_http(handler)
    js = RecordingJS()
    nc.jetstream = lambda: js

    env = {"jsonrpc": "2.0", "id": "8", "method": "responses/createDetached",
           "params": {"request": {"input": "hi"}, "turn_id": "t2",
                      "stream_subject": "vystak.multi.streams.c1.t2"}}
    await bridge._forward(FakeMsg(env))
    await asyncio.gather(*bridge._inflight)

    payloads = [p for _, p in js.published]
    assert len(payloads) == 1
    assert payloads[0]["event"]["type"] == "response.failed"


@pytest.mark.asyncio
async def test_create_detached_missing_params_is_invalid_params_error():
    bridge, nc = _bridge_with_mock_http(lambda r: httpx.Response(200))
    env = {"jsonrpc": "2.0", "id": "9", "method": "responses/createDetached",
           "params": {"request": {"input": "hi"}}}
    await bridge._forward(FakeMsg(env))
    _, reply = nc.published[0]
    assert reply["error"]["code"] == -32602
    assert not bridge._inflight
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest packages/python/vystak-template-langchain-python/tests/test_nats_bridge.py -v -k detached`
Expected: FAIL (method falls through to /a2a forwarding, no ack `result` with turn_id)

- [ ] **Step 3: Implement.** In `nats_bridge.py`:

1. Routing in `_forward` (extend Task 3's block):

```python
            if method == "responses/createDetached":
                await self._handle_responses_create_detached(envelope, reply_subject)
                return
```

2. Module-level helpers (bottom of file, near `_slug`):

```python
# KEEP IN SYNC with vystak_transport_nats/streams.py — the template cannot
# import that package (agent images install vystak from PyPI only). Same
# convention: turn subject "{base}.streams.{conv}.{turn}", stream name
# "{base with . -> -}-streams", subject filter "{base}.streams.>".
def _stream_base_of_turn_subject(stream_subject: str) -> str:
    base, sep, _ = stream_subject.partition(".streams.")
    if not sep:
        raise ValueError(f"not a turn subject: {stream_subject!r}")
    return base


async def _ensure_turn_stream(js: Any, base: str) -> None:
    from nats.js.api import RetentionPolicy, StorageType, StreamConfig

    cfg = StreamConfig(
        name=base.replace(".", "-") + "-streams",
        subjects=[f"{base}.streams.>"],
        retention=RetentionPolicy.LIMITS,
        max_age=3600.0,
        storage=StorageType.FILE,
    )
    try:
        await js.add_stream(cfg)
    except Exception:  # noqa: BLE001 — exists; converge
        await js.update_stream(cfg)


def _failed_event(message: str) -> dict:
    return {
        "type": "response.failed",
        "response": {"status": "failed", "error": {"message": message}},
    }
```

3. Handler + detached task on the class:

```python
    async def _handle_responses_create_detached(
        self, envelope: dict, reply_subject: str
    ) -> None:
        """Ack immediately, then run the turn to completion publishing every
        Responses SSE event durably to JetStream — the turn's lifetime is
        decoupled from the requester (and from any browser)."""
        params = envelope.get("params") or {}
        request = params.get("request")
        turn_id = params.get("turn_id")
        stream_subject = params.get("stream_subject")
        if not request or not turn_id or not stream_subject:
            await self._publish_error_async(
                reply_subject, code=-32602,
                message="responses/createDetached requires request, turn_id, stream_subject",
                request_id=envelope.get("id"),
            )
            return
        ack = {
            "jsonrpc": "2.0",
            "id": envelope.get("id"),
            "result": {"turn_id": turn_id, "stream_subject": stream_subject},
        }
        if reply_subject:
            await self._nc.publish(reply_subject, json.dumps(ack).encode())
        task = asyncio.create_task(self._run_detached(dict(request), stream_subject))
        self._inflight.add(task)
        task.add_done_callback(self._inflight.discard)

    async def _run_detached(self, request: dict, stream_subject: str) -> None:
        js = self._nc.jetstream()
        seq = 0

        async def publish(event: dict) -> None:
            nonlocal seq
            await js.publish(
                stream_subject, json.dumps({"seq": seq, "event": event}).encode()
            )
            seq += 1

        try:
            await _ensure_turn_stream(js, _stream_base_of_turn_subject(stream_subject))
        except Exception:
            logger.exception("nats_bridge.detached_ensure_stream_failed")
            return
        request["stream"] = True
        assert self._http is not None
        try:
            async with self._http.stream(
                "POST",
                f"{self._local_base}/v1/responses",
                json=request,
                # Long-lived LLM stream: the client-level 120s total timeout
                # would kill slow turns; only bound connect + inter-chunk read.
                timeout=httpx.Timeout(None, connect=10.0, read=300.0),
            ) as resp:
                if resp.status_code != 200:
                    await publish(_failed_event(f"local /v1/responses returned {resp.status_code}"))
                    return
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data_str = line[6:]
                    if data_str == "[DONE]":
                        return
                    try:
                        event = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue
                    await publish(event)
                # Truncated stream (no [DONE], no terminal event): make sure
                # consumers still terminate.
                await publish(_failed_event("agent stream ended without a terminal event"))
        except Exception as e:  # noqa: BLE001 — the failure must reach consumers
            logger.exception("nats_bridge.detached_failed")
            try:
                await publish(_failed_event(str(e)))
            except Exception:  # noqa: BLE001 — nothing left to do
                logger.exception("nats_bridge.detached_failed_publish")
```

Also add `from typing import Any` if not imported (it is — check the header) and `import httpx` is already present.

**Watch out:** the truncated-stream `publish(_failed_event(...))` must NOT run when the loop exited via `[DONE]` — the `return` inside the loop handles that; when the terminal event WAS already published (normal path: `response.completed` arrives before `[DONE]`), consumers stop at the terminal event, and the `[DONE]` line returns before the fallback line runs. Keep that control flow exactly.

- [ ] **Step 4: Run tests**

Run: `uv run pytest packages/python/vystak-template-langchain-python/tests/test_nats_bridge.py -v`
Expected: all PASS

- [ ] **Step 5: Parity-sync, lint, commit**

Run `uv run pytest packages/python/vystak-template-langchain-python/tests/test_codegen_parity.py -v`; copy `nats_bridge.py` into the example `_vystak` trees it flags, re-run until green.

```bash
just lint-python
git add packages/python/vystak-template-langchain-python examples/*/_vystak/runtime/nats_bridge.py
git commit -m "feat(template): responses/createDetached — detached JetStream turn publisher"
```

---

### Task 5: Panel store — schema v4 (active turns) + turn methods

**Files:**
- Modify: `packages/python/vystak-channel-panel/src/vystak_channel_panel/store.py`
- Modify: `packages/python/vystak-channel-panel/src/vystak_channel_panel/models.py`
- Test: `packages/python/vystak-channel-panel/tests/test_store_migrations.py`, `packages/python/vystak-channel-panel/tests/test_store_conversations.py` (append; follow existing fixture style — they create stores on tmp paths)

**Interfaces:**
- Produces (used by Tasks 7–8):
  - `Conversation.active_turn_id: str | None` (model field), `PanelMessage.turn_id: str | None`
  - `async SqlitePanelStore.set_active_turn(conversation_id: str, turn_id: str) -> None`
  - `async SqlitePanelStore.clear_active_turn(conversation_id: str, turn_id: str) -> bool` — clears only when it still equals `turn_id`; True if a row changed
  - `async SqlitePanelStore.list_active_turns() -> list[Conversation]`
  - `add_message(..., turn_id: str | None = None)` — new keyword, persisted to the new column

- [ ] **Step 1: Write the failing tests**

Append to `test_store_migrations.py` (mirror how the v3 migration test builds an old-schema DB — copy its approach; the essential assertions):

```python
@pytest.mark.asyncio
async def test_v4_adds_turn_columns(tmp_path):
    # Build a store, then simulate an existing v3 DB by dropping the new
    # columns is not possible in SQLite — instead assert a fresh connect()
    # yields the columns and schema_version == 4.
    store = SqlitePanelStore(tmp_path / "p.db")
    await store.connect()
    async with store.db.execute("PRAGMA table_info(conversations)") as cur:
        conv_cols = {row["name"] async for row in cur}
    async with store.db.execute("PRAGMA table_info(messages)") as cur:
        msg_cols = {row["name"] async for row in cur}
    assert "active_turn_id" in conv_cols
    assert "turn_id" in msg_cols
    assert await store.get_setting("schema_version") == "4"
    await store.close()
```

Also add a re-migration test in the same style the file already uses for v2→v3 (create a DB with the v3 `_SCHEMA` inline, connect the real store over it, assert the ALTERs applied). Reuse the file's existing old-schema fixture pattern verbatim, appending the two new columns to its expectations.

Append to `test_store_conversations.py`:

```python
@pytest.mark.asyncio
async def test_active_turn_lifecycle(store):
    # `store` fixture: whatever the file already uses (connected store +
    # seeded user/project); adapt names to match.
    conv = await store.create_conversation(project.id, user.id, "agent-a")
    assert conv.active_turn_id is None

    await store.set_active_turn(conv.id, "turn-1")
    conv2 = await store.get_conversation(conv.id)
    assert conv2.active_turn_id == "turn-1"
    assert [c.id for c in await store.list_active_turns()] == [conv.id]

    # mismatched turn id: no-op
    assert await store.clear_active_turn(conv.id, "other-turn") is False
    assert (await store.get_conversation(conv.id)).active_turn_id == "turn-1"

    assert await store.clear_active_turn(conv.id, "turn-1") is True
    assert (await store.get_conversation(conv.id)).active_turn_id is None
    assert await store.list_active_turns() == []
    # idempotent second clear
    assert await store.clear_active_turn(conv.id, "turn-1") is False


@pytest.mark.asyncio
async def test_add_message_persists_turn_id(store):
    conv = await store.create_conversation(project.id, user.id, "agent-a")
    msg = await store.add_message(conv.id, "assistant", "hello", turn_id="turn-9")
    fetched = (await store.list_messages(conv.id))[-1]
    assert fetched.turn_id == "turn-9"
    assert msg.turn_id == "turn-9"
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest packages/python/vystak-channel-panel/tests/test_store_conversations.py packages/python/vystak-channel-panel/tests/test_store_migrations.py -v`
Expected: FAIL — `AttributeError: 'SqlitePanelStore' object has no attribute 'set_active_turn'` / missing columns

- [ ] **Step 3: Implement**

1. `models.py`: add `active_turn_id: str | None = None` to `Conversation`; add `turn_id: str | None = None` to `PanelMessage`.
2. `store.py`:
   - `SCHEMA_VERSION = 4`.
   - `_SCHEMA`: add `active_turn_id TEXT` to the `conversations` CREATE, `turn_id TEXT` to `messages`.
   - `_migrate()`: it already reads `PRAGMA table_info(messages)` into `columns` and `PRAGMA table_info(users)` into `user_columns`; add a `PRAGMA table_info(conversations)` read into `conv_columns`, and inside the `_write()` block:

```python
            if "active_turn_id" not in conv_columns:
                await db.execute(
                    "ALTER TABLE conversations ADD COLUMN active_turn_id TEXT"
                )
            if "turn_id" not in columns:
                await db.execute("ALTER TABLE messages ADD COLUMN turn_id TEXT")
```

   - New methods next to `update_conversation`:

```python
    async def set_active_turn(self, conversation_id: str, turn_id: str) -> None:
        async with self._write() as db:
            await db.execute(
                "UPDATE conversations SET active_turn_id = ?, updated_at = ? "
                "WHERE id = ?",
                (turn_id, _now(), conversation_id),
            )

    async def clear_active_turn(self, conversation_id: str, turn_id: str) -> bool:
        """Clear only while the active turn is still *turn_id*.

        The compare-and-clear makes concurrent persisters safe: whichever
        finishes second matches nothing and returns False.
        """
        async with self._write() as db:
            cur = await db.execute(
                "UPDATE conversations SET active_turn_id = NULL, updated_at = ? "
                "WHERE id = ? AND active_turn_id = ?",
                (_now(), conversation_id, turn_id),
            )
            return cur.rowcount > 0

    async def list_active_turns(self) -> list[Conversation]:
        async with self.db.execute(
            "SELECT * FROM conversations WHERE active_turn_id IS NOT NULL"
        ) as cur:
            rows = await cur.fetchall()
        return [Conversation(**dict(r)) for r in rows]
```

   - `add_message`: add `turn_id: str | None = None` keyword; include in the `PanelMessage(...)` construction and the INSERT column list/values.
   - Find the message row→model mapping (`list_messages` / wherever `PanelMessage(**...)` is built from rows) and confirm it picks up `turn_id` from `dict(row)` automatically (it will, since the model field exists and the column is selected by `SELECT *`; if the file parses `parts` manually, add `turn_id` handling alongside).

- [ ] **Step 4: Run panel store tests**

Run: `uv run pytest packages/python/vystak-channel-panel/tests/ -v -k store`
Expected: all PASS

- [ ] **Step 5: Lint and commit**

```bash
just lint-python
git add packages/python/vystak-channel-panel
git commit -m "feat(panel): schema v4 — active_turn_id + message turn_id"
```

---

### Task 6: Panel — shared event translator + `TurnAccumulator` (refactor, no behavior change)

**Files:**
- Create: `packages/python/vystak-channel-panel/src/vystak_channel_panel/turn_stream.py`
- Modify: `packages/python/vystak-channel-panel/src/vystak_channel_panel/responses_client.py` (use the shared translator)
- Modify: `packages/python/vystak-channel-panel/src/vystak_channel_panel/routes_messages.py` (use `TurnAccumulator` + `browser_frame`)
- Test: `packages/python/vystak-channel-panel/tests/test_turn_stream.py` (new)

**Interfaces:**
- Produces (used by Tasks 7–8):
  - `translate_responses_event(data: dict, pending_calls: dict[str, dict]) -> PanelStreamEvent | None` — one OpenAI Responses SSE payload → panel event; `pending_calls` is caller-owned mutable state; returns None for non-events (`response.created`, arg deltas, unknown types)
  - `class TurnAccumulator` with: `feed(ev: PanelStreamEvent) -> None` (state update for token/tool_call/tool_result), `content: str` property, `parts() -> list[dict] | None` (flushes open text), `has_output: bool` property
  - `browser_frame(ev: PanelStreamEvent) -> dict` — the SSE payload dict the panel sends browsers for token/tool_call/tool_result/error events (exact shapes currently inlined in `routes_messages.py`)

- [ ] **Step 1: Write the failing tests**

```python
# packages/python/vystak-channel-panel/tests/test_turn_stream.py
"""Tests for the shared Responses-event translator and turn accumulator."""

from vystak_channel_panel.responses_client import PanelStreamEvent
from vystak_channel_panel.turn_stream import (
    TurnAccumulator,
    browser_frame,
    translate_responses_event,
)


def test_translate_text_delta():
    ev = translate_responses_event(
        {"type": "response.output_text.delta", "delta": "hi"}, {}
    )
    assert ev.type == "token" and ev.text == "hi"


def test_translate_tool_call_correlates_name_and_args():
    pending: dict = {}
    assert translate_responses_event(
        {"type": "response.output_item.added",
         "item": {"type": "function_call", "call_id": "c1", "name": "get_time"}},
        pending,
    ) is None
    assert translate_responses_event(
        {"type": "response.function_call_arguments.delta", "call_id": "c1", "delta": '{"a"'},
        pending,
    ) is None
    ev = translate_responses_event(
        {"type": "response.function_call_arguments.done", "call_id": "c1", "arguments": ""},
        pending,
    )
    assert ev.type == "tool_call"
    assert ev.tool_name == "get_time"
    assert ev.arguments == '{"a"'


def test_translate_tool_result_and_terminals():
    ev = translate_responses_event(
        {"type": "response.output_item.added",
         "item": {"type": "function_call_output", "call_id": "c1",
                  "output": "12:00", "error": False}},
        {},
    )
    assert ev.type == "tool_result" and ev.output == "12:00"
    done = translate_responses_event(
        {"type": "response.completed", "response": {"id": "r9"}}, {}
    )
    assert done.type == "done" and done.response_id == "r9"
    failed = translate_responses_event(
        {"type": "response.failed", "response": {"error": {"message": "boom"}}}, {}
    )
    assert failed.type == "error" and failed.text == "boom"
    assert translate_responses_event({"type": "response.created"}, {}) is None


def test_accumulator_orders_text_and_tools():
    acc = TurnAccumulator()
    acc.feed(PanelStreamEvent(type="token", text="a"))
    acc.feed(PanelStreamEvent(type="tool_call", tool_call_id="c1",
                              tool_name="t", arguments="{}"))
    acc.feed(PanelStreamEvent(type="tool_result", tool_call_id="c1", output="ok"))
    acc.feed(PanelStreamEvent(type="token", text="b"))
    assert acc.content == "ab"
    parts = acc.parts()
    assert [p["type"] for p in parts] == ["text", "tool", "text"]
    assert parts[1]["tool_name"] == "t"
    assert acc.has_output


def test_accumulator_drops_unmatched_tool_call():
    acc = TurnAccumulator()
    acc.feed(PanelStreamEvent(type="tool_call", tool_call_id="c1",
                              tool_name="t", arguments="{}"))
    assert acc.parts() is None
    assert not acc.has_output


def test_browser_frames():
    assert browser_frame(PanelStreamEvent(type="token", text="x")) == {
        "type": "delta", "text": "x"}
    assert browser_frame(PanelStreamEvent(
        type="tool_call", tool_call_id="c", tool_name="n", arguments="{}")) == {
        "type": "tool_call", "tool_call_id": "c", "tool_name": "n", "arguments": "{}"}
    assert browser_frame(PanelStreamEvent(
        type="tool_result", tool_call_id="c", output="o", is_error=True)) == {
        "type": "tool_result", "tool_call_id": "c", "output": "o", "is_error": True}
    assert browser_frame(PanelStreamEvent(type="error", text="bad")) == {
        "type": "error", "message": "bad"}
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest packages/python/vystak-channel-panel/tests/test_turn_stream.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement `turn_stream.py`.** The translator is a **verbatim move** of the event-mapping block in `responses_client.py` lines 102–157 (return instead of yield; `response.function_call_arguments.delta` mutates `pending_calls` and returns None). The accumulator is a verbatim move of the state in `routes_messages.py`'s `gen()` (`text_chunks`/`current_text`/`msg_parts`/`pending_tool_calls`/`flush_text` — including the drop-unmatched-tool-call comment and behavior):

```python
# packages/python/vystak-channel-panel/src/vystak_channel_panel/turn_stream.py
"""Shared turn-stream machinery: Responses-event translation, accumulation,
and browser-frame shapes. Used by both the HTTP proxy path and the NATS
JetStream path so the two can never drift."""

from __future__ import annotations

from vystak_channel_panel.responses_client import PanelStreamEvent


def translate_responses_event(
    data: dict, pending_calls: dict[str, dict]
) -> PanelStreamEvent | None:
    event_type = data.get("type", "")
    if event_type == "response.output_text.delta":
        return PanelStreamEvent(type="token", text=data.get("delta", ""))
    if event_type == "response.output_item.added":
        item = data.get("item") or {}
        item_type = item.get("type")
        if item_type == "function_call":
            call_id = item.get("call_id") or item.get("id") or ""
            if call_id:
                pending_calls[call_id] = {
                    "tool_name": item.get("name", ""),
                    "arguments": "",
                }
            return None
        if item_type == "function_call_output":
            return PanelStreamEvent(
                type="tool_result",
                tool_call_id=item.get("call_id", ""),
                output=item.get("output", ""),
                is_error=bool(item.get("error", False)),
            )
        return None
    if event_type == "response.function_call_arguments.delta":
        pending = pending_calls.get(data.get("call_id", ""))
        if pending is not None:
            pending["arguments"] += data.get("delta", "")
        return None
    if event_type == "response.function_call_arguments.done":
        call_id = data.get("call_id", "")
        pending = pending_calls.pop(call_id, None)
        if pending is not None:
            tool_name = pending["tool_name"]
            arguments = pending["arguments"]
        else:
            # No matching output_item.added seen — fall back to this event's
            # own payload rather than dropping the call.
            tool_name = ""
            arguments = data.get("arguments", "")
        return PanelStreamEvent(
            type="tool_call",
            tool_call_id=call_id,
            tool_name=tool_name,
            arguments=arguments,
        )
    if event_type == "response.completed":
        return PanelStreamEvent(
            type="done", response_id=data.get("response", {}).get("id", "")
        )
    if event_type == "response.failed":
        err = (
            data.get("response", {}).get("error", {})
            .get("message", "agent stream failed")
        )
        return PanelStreamEvent(type="error", text=err)
    return None


class TurnAccumulator:
    """Accumulates one turn's events into (content, parts) for persistence.

    Mirrors the ordering rules documented in routes_messages.py: `content`
    is every text token in order; `parts` interleaves text segments with
    completed tool calls; a tool_call with no matching tool_result is
    deliberately dropped from parts.
    """

    def __init__(self) -> None:
        self.text_chunks: list[str] = []
        self._current_text: list[str] = []
        self.msg_parts: list[dict] = []
        self._pending_tool_calls: dict[str, dict] = {}

    def feed(self, ev: PanelStreamEvent) -> None:
        if ev.type == "token":
            self.text_chunks.append(ev.text)
            self._current_text.append(ev.text)
        elif ev.type == "tool_call":
            self._flush_text()
            self._pending_tool_calls[ev.tool_call_id] = {
                "tool_name": ev.tool_name,
                "arguments": ev.arguments,
            }
        elif ev.type == "tool_result":
            call = self._pending_tool_calls.pop(ev.tool_call_id, None)
            self.msg_parts.append({
                "type": "tool",
                "tool_call_id": ev.tool_call_id,
                "tool_name": call["tool_name"] if call else "",
                "input": call["arguments"] if call else "",
                "output": ev.output,
                "is_error": ev.is_error,
            })

    def _flush_text(self) -> None:
        if self._current_text:
            self.msg_parts.append({"type": "text", "text": "".join(self._current_text)})
            self._current_text.clear()

    @property
    def content(self) -> str:
        return "".join(self.text_chunks)

    def parts(self) -> list[dict] | None:
        self._flush_text()
        return self.msg_parts or None

    @property
    def has_output(self) -> bool:
        return bool(self.text_chunks or self.msg_parts or self._current_text)


def browser_frame(ev: PanelStreamEvent) -> dict:
    """The panel→browser SSE payload for one streaming event."""
    if ev.type == "token":
        return {"type": "delta", "text": ev.text}
    if ev.type == "tool_call":
        return {
            "type": "tool_call",
            "tool_call_id": ev.tool_call_id,
            "tool_name": ev.tool_name,
            "arguments": ev.arguments,
        }
    if ev.type == "tool_result":
        return {
            "type": "tool_result",
            "tool_call_id": ev.tool_call_id,
            "output": ev.output,
            "is_error": ev.is_error,
        }
    return {"type": "error", "message": ev.text}
```

Then refactor the two call sites:
- `responses_client.py`: replace the `if event_type == ...` chain (lines 102–157) with:

```python
                        ev = translate_responses_event(data, pending_calls)
                        if ev is not None:
                            yield ev
```
  (import `translate_responses_event` **lazily inside the method or at the bottom** — no: `turn_stream` imports `PanelStreamEvent` FROM `responses_client`, so `responses_client` importing `turn_stream` at module top would be circular. Do the import inside `stream_message` with a `# circular: turn_stream imports PanelStreamEvent from this module` comment.)
- `routes_messages.py`: replace `text_chunks`/`current_text`/`msg_parts`/`pending_tool_calls`/`flush_text` in `gen()` with one `acc = TurnAccumulator()`; each streaming branch becomes `acc.feed(ev)` + `yield _sse(browser_frame(ev))`; `persist()` becomes `add_message(conv_id, "assistant", acc.content, response_id=response_id, parts=acc.parts())`; the `if text_chunks or msg_parts:` guards become `if acc.has_output:`.

- [ ] **Step 4: Run the full panel suite — this is a refactor, everything must stay green**

Run: `uv run pytest packages/python/vystak-channel-panel/tests/ -v`
Expected: all PASS, including the existing `test_api_messages_stream.py` and `test_responses_client.py`

- [ ] **Step 5: Lint and commit**

```bash
just lint-python
git add packages/python/vystak-channel-panel
git commit -m "refactor(panel): extract shared turn-stream translator + accumulator"
```

---

### Task 7: Panel — NATS turn client, persister worker, runtime wiring

**Files:**
- Create: `packages/python/vystak-channel-panel/src/vystak_channel_panel/nats_client.py`
- Create: `packages/python/vystak-channel-panel/src/vystak_channel_panel/turn_worker.py`
- Modify: `packages/python/vystak-channel-panel/src/vystak_channel_panel/runtime.py`
- Test: `packages/python/vystak-channel-panel/tests/test_turn_worker.py` (new)

**Interfaces:**
- Produces (used by Task 8):
  - `class PanelNatsClient`:
    - `__init__(nats_url: str, *, timeout_s: float = 30.0, idle_timeout_s: float = 120.0)`
    - `@staticmethod turn_subject_for(route_entry: dict, conversation_id: str, turn_id: str) -> str`
    - `async start_turn(route_entry: dict, text: str, *, conv_id: str, turn_id: str, previous_response_id: str | None, user_id: str | None, project_id: str | None) -> str` — ensures the stream, sends `responses/createDetached`, returns the turn subject
    - `async stream_turn_events(subject: str) -> AsyncIterator[tuple[int, PanelStreamEvent]]` — replays from seq 0, yields `(seq, event)`, ends after done/error event; raises `TurnStreamIdle` on idle
  - `async run_turn_persister(rt, conv_id: str, turn_id: str, subject: str) -> None`
  - `PanelChannelRuntime.transport_type: str`, `.nats_client: PanelNatsClient | None`, `.turn_tasks: dict[str, asyncio.Task]`, `.spawn_persister(conv_id, turn_id, subject)`, `async ._resume_active_turns()`

- [ ] **Step 1: Write the failing tests**

```python
# packages/python/vystak-channel-panel/tests/test_turn_worker.py
"""Persister worker tests with a fake NATS client."""

import asyncio

import pytest
from vystak_channel_panel.responses_client import PanelStreamEvent
from vystak_channel_panel.turn_worker import run_turn_persister
from vystak_transport_nats.streams import TurnStreamIdle


class FakeNatsClient:
    def __init__(self, events, *, idle=False):
        self._events = events
        self._idle = idle

    async def stream_turn_events(self, subject):
        for seq, ev in enumerate(self._events):
            yield seq, ev
        if self._idle:
            raise TurnStreamIdle(subject)


class FakeRuntime:
    def __init__(self, store, nats_client):
        self.panel_store = store
        self.nats_client = nats_client
        self.turn_tasks = {}


@pytest.mark.asyncio
async def test_persister_writes_row_and_clears_turn(panel_store, conversation):
    # `panel_store` / `conversation` fixtures: connected store + a
    # conversation row — mirror conftest.py's existing fixtures.
    await panel_store.set_active_turn(conversation.id, "t1")
    rt = FakeRuntime(panel_store, FakeNatsClient([
        PanelStreamEvent(type="token", text="hel"),
        PanelStreamEvent(type="token", text="lo"),
        PanelStreamEvent(type="done", response_id="resp_9"),
    ]))
    await run_turn_persister(rt, conversation.id, "t1", "subj")

    msgs = await panel_store.list_messages(conversation.id)
    assistant = [m for m in msgs if m.role == "assistant"]
    assert len(assistant) == 1
    assert assistant[0].content == "hello"
    assert assistant[0].turn_id == "t1"
    assert assistant[0].response_id == "resp_9"
    conv = await panel_store.get_conversation(conversation.id)
    assert conv.active_turn_id is None
    assert conv.last_response_id == "resp_9"


@pytest.mark.asyncio
async def test_persister_error_event_persists_partial(panel_store, conversation):
    await panel_store.set_active_turn(conversation.id, "t2")
    rt = FakeRuntime(panel_store, FakeNatsClient([
        PanelStreamEvent(type="token", text="par"),
        PanelStreamEvent(type="error", text="boom"),
    ]))
    await run_turn_persister(rt, conversation.id, "t2", "subj")
    assistant = [m for m in await panel_store.list_messages(conversation.id)
                 if m.role == "assistant"]
    assert len(assistant) == 1
    assert assistant[0].content == "par"
    assert assistant[0].response_id is None
    conv = await panel_store.get_conversation(conversation.id)
    assert conv.active_turn_id is None
    assert conv.last_response_id is None  # untouched on error


@pytest.mark.asyncio
async def test_persister_error_with_no_output_writes_no_row(panel_store, conversation):
    await panel_store.set_active_turn(conversation.id, "t3")
    rt = FakeRuntime(panel_store, FakeNatsClient([
        PanelStreamEvent(type="error", text="boom"),
    ]))
    await run_turn_persister(rt, conversation.id, "t3", "subj")
    assert [m for m in await panel_store.list_messages(conversation.id)
            if m.role == "assistant"] == []
    assert (await panel_store.get_conversation(conversation.id)).active_turn_id is None


@pytest.mark.asyncio
async def test_persister_idle_timeout_persists_partial(panel_store, conversation):
    await panel_store.set_active_turn(conversation.id, "t4")
    rt = FakeRuntime(panel_store, FakeNatsClient(
        [PanelStreamEvent(type="token", text="part")], idle=True))
    await run_turn_persister(rt, conversation.id, "t4", "subj")
    assistant = [m for m in await panel_store.list_messages(conversation.id)
                 if m.role == "assistant"]
    assert len(assistant) == 1 and assistant[0].content == "part"
    assert (await panel_store.get_conversation(conversation.id)).active_turn_id is None
```

Also test `PanelNatsClient.turn_subject_for`:

```python
def test_turn_subject_for():
    from vystak_channel_panel.nats_client import PanelNatsClient

    entry = {"canonical": "time-agent.agents.multi",
             "address": "vystak.multi.agents.time-agent.tasks"}
    assert (PanelNatsClient.turn_subject_for(entry, "c1", "t1")
            == "vystak.multi.streams.c1.t1")
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest packages/python/vystak-channel-panel/tests/test_turn_worker.py -v`
Expected: FAIL — modules not found

- [ ] **Step 3: Implement**

First, declare the new dependency: in
`packages/python/vystak-channel-panel/pyproject.toml`, add
`"vystak-transport-nats"` to `[project] dependencies` (match how the file
declares its other workspace deps, e.g. `vystak-channel-runtime`). The uv
workspace already installs it editable, and channel images bundle its
source, but the dependency must be declared for standalone installs.

```python
# packages/python/vystak-channel-panel/src/vystak_channel_panel/nats_client.py
"""NATS-transport client for the panel: detached turn start + JetStream replay."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from vystak.transport import AgentRef
from vystak_transport_nats import NatsTransport
from vystak_transport_nats.streams import (
    ensure_stream,
    read_turn_events,
    stream_base,
    turn_subject,
)

from vystak_channel_panel.responses_client import PanelStreamEvent
from vystak_channel_panel.turn_stream import translate_responses_event

logger = logging.getLogger("vystak.channel.panel.nats")


class PanelNatsClient:
    def __init__(
        self,
        nats_url: str,
        *,
        timeout_s: float = 30.0,
        idle_timeout_s: float = 120.0,
    ) -> None:
        self._transport = NatsTransport(nats_url)
        self._timeout = timeout_s
        self.idle_timeout_s = idle_timeout_s

    @staticmethod
    def turn_subject_for(route_entry: dict, conversation_id: str, turn_id: str) -> str:
        return turn_subject(stream_base(route_entry["address"]), conversation_id, turn_id)

    async def start_turn(
        self,
        route_entry: dict,
        text: str,
        *,
        conv_id: str,
        turn_id: str,
        previous_response_id: str | None,
        user_id: str | None,
        project_id: str | None,
    ) -> str:
        base = stream_base(route_entry["address"])
        subject = turn_subject(base, conv_id, turn_id)
        nc = await self._transport.nats_connection()
        await ensure_stream(nc.jetstream(), base)
        request = {
            "model": "",
            "input": text,
            "previous_response_id": previous_response_id,
            "store": True,
            "stream": True,
            "user_id": user_id,
            "project_id": project_id,
        }
        await self._transport.create_response_detached(
            AgentRef(canonical_name=route_entry["canonical"]),
            request,
            {},
            turn_id=turn_id,
            stream_subject=subject,
            timeout=self._timeout,
        )
        return subject

    async def stream_turn_events(
        self, subject: str
    ) -> AsyncIterator[tuple[int, PanelStreamEvent]]:
        nc = await self._transport.nats_connection()
        pending_calls: dict[str, dict] = {}
        async for payload in read_turn_events(
            nc, subject, idle_timeout_s=self.idle_timeout_s
        ):
            ev = translate_responses_event(payload.get("event") or {}, pending_calls)
            if ev is not None:
                yield int(payload.get("seq", 0)), ev
```

```python
# packages/python/vystak-channel-panel/src/vystak_channel_panel/turn_worker.py
"""Process-owned turn persister — consumes a turn's JetStream subject and
writes the assistant row, independent of any browser connection."""

from __future__ import annotations

import logging
from typing import Any

from vystak_transport_nats.streams import TurnStreamIdle

from vystak_channel_panel.turn_stream import TurnAccumulator

logger = logging.getLogger("vystak.channel.panel.turns")


async def run_turn_persister(
    rt: Any, conv_id: str, turn_id: str, subject: str
) -> None:
    acc = TurnAccumulator()
    response_id: str | None = None
    errored = False
    try:
        async for _seq, ev in rt.nats_client.stream_turn_events(subject):
            if ev.type == "done":
                response_id = ev.response_id or None
                break
            if ev.type == "error":
                errored = True
                break
            acc.feed(ev)
    except TurnStreamIdle:
        logger.warning("turn idle timeout conv=%s turn=%s", conv_id, turn_id)
        errored = True
    except Exception:  # noqa: BLE001 — persister must reach the cleanup below
        logger.exception("turn persister failed conv=%s turn=%s", conv_id, turn_id)
        errored = True
    try:
        # Same rules as the HTTP path: a clean done always persists (even
        # empty); an errored turn persists only what the user already saw.
        if not errored or acc.has_output:
            await rt.panel_store.add_message(
                conv_id, "assistant", acc.content,
                response_id=response_id, parts=acc.parts(), turn_id=turn_id,
            )
        if response_id:
            await rt.panel_store.update_conversation(
                conv_id, last_response_id=response_id
            )
    finally:
        await rt.panel_store.clear_active_turn(conv_id, turn_id)
        rt.turn_tasks.pop(turn_id, None)
```

`runtime.py` changes (in `PanelChannelRuntime`):

```python
# imports at top
import asyncio
import os
```

In `__init__`, after `self.responses_client = ...`:

```python
        self.transport_type = self.config.get("transport_type", "http")
        self.nats_client = None
        if self.transport_type == "nats":
            from vystak_channel_panel.nats_client import PanelNatsClient

            self.nats_client = PanelNatsClient(
                os.environ.get("VYSTAK_NATS_URL", "nats://vystak-nats:4222"),
                idle_timeout_s=float(self.config.get("turn_idle_timeout_s", 120.0)),
            )
        self.turn_tasks: dict[str, asyncio.Task] = {}
```

New methods:

```python
    def spawn_persister(self, conv_id: str, turn_id: str, subject: str) -> None:
        from vystak_channel_panel.turn_worker import run_turn_persister

        task = asyncio.create_task(run_turn_persister(self, conv_id, turn_id, subject))
        self.turn_tasks[turn_id] = task

    async def _resume_active_turns(self) -> None:
        """Re-attach persisters for turns that were in flight when the panel
        last stopped — JetStream replay-from-0 rebuilds the accumulator."""
        if self.nats_client is None:
            return
        from vystak_channel_panel.nats_client import PanelNatsClient

        for conv in await self.panel_store.list_active_turns():
            route = self.routes.get(conv.agent_name)
            if route is None or not conv.active_turn_id:
                continue
            subject = PanelNatsClient.turn_subject_for(
                route, conv.id, conv.active_turn_id
            )
            self.spawn_persister(conv.id, conv.active_turn_id, subject)
```

In `start()`, after `await self.panel_store.connect()` (inside the `_owns_store` block won't do — the rescan needs a connected store regardless; place it right before `await self._server.serve()`):

```python
        await self._resume_active_turns()
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest packages/python/vystak-channel-panel/tests/ -v`
Expected: all PASS

- [ ] **Step 5: Lint and commit**

```bash
just lint-python
git add packages/python/vystak-channel-panel
git commit -m "feat(panel): NATS turn client + detached persister worker"
```

---

### Task 8: Panel routes — NATS POST path + GET resume endpoint

**Files:**
- Modify: `packages/python/vystak-channel-panel/src/vystak_channel_panel/routes_messages.py`
- Test: `packages/python/vystak-channel-panel/tests/test_api_messages_stream.py` (append; follow the file's existing app/TestClient fixture style)

**Interfaces:**
- `POST /api/conversations/{conv_id}/messages` — when `rt.nats_client` is set: persists user row + title, generates `turn_id = uuid.uuid4().hex`, `set_active_turn`, `start_turn`, `spawn_persister`, and returns an SSE proxy of `stream_turn_events`. Frames are `browser_frame(ev)` plus `"turn_id"` and `"seq"` keys; the terminal frame is `{"type": "done", "turn_id", "seq", "response_id", "title"}` (no `message_id` — the persister owns the row; the UI ignores `done` and refetches). On `start_turn` failure: clear the active turn, return one `{"type": "error", ...}` frame.
- `GET /api/conversations/{conv_id}/stream` — 204 when `rt.nats_client is None` or no `active_turn_id`; otherwise the same SSE proxy replaying from seq 0.

- [ ] **Step 1: Write the failing tests** (adapt fixture names to the file's existing ones — it already builds a `PanelChannelRuntime` + FastAPI TestClient; give the runtime a fake NATS client):

```python
class FakePanelNatsClient:
    idle_timeout_s = 120.0

    def __init__(self):
        self.started: list[dict] = []
        self.events = [
            (0, PanelStreamEvent(type="token", text="hi")),
            (1, PanelStreamEvent(type="done", response_id="resp_1")),
        ]

    @staticmethod
    def turn_subject_for(route_entry, conv_id, turn_id):
        return f"base.streams.{conv_id}.{turn_id}"

    async def start_turn(self, route_entry, text, **kw):
        self.started.append({"text": text, **kw})
        return f"base.streams.{kw['conv_id']}.{kw['turn_id']}"

    async def stream_turn_events(self, subject):
        for seq, ev in self.events:
            yield seq, ev


def test_post_message_nats_path_streams_and_marks_active_turn(client, rt, conversation):
    rt.nats_client = FakePanelNatsClient()
    rt.turn_tasks = {}
    rt.spawn_persister = lambda *a, **k: None  # persister covered by test_turn_worker

    resp = client.post(
        f"/api/conversations/{conversation.id}/messages",
        json={"text": "hello"},
        headers=AUTH_HEADERS,
    )
    assert resp.status_code == 200
    frames = [json.loads(line[6:]) for line in resp.text.splitlines()
              if line.startswith("data: ")]
    assert frames[0]["type"] == "delta"
    assert frames[0]["text"] == "hi"
    assert frames[0]["seq"] == 0
    assert frames[0]["turn_id"]  # generated uuid hex — non-empty is enough
    assert frames[-1]["type"] == "done"
    assert frames[-1]["response_id"] == "resp_1"
    assert rt.nats_client.started[0]["conv_id"] == conversation.id


def test_resume_endpoint_204_when_no_active_turn(client, rt, conversation):
    rt.nats_client = FakePanelNatsClient()
    resp = client.get(
        f"/api/conversations/{conversation.id}/stream", headers=AUTH_HEADERS
    )
    assert resp.status_code == 204


def test_resume_endpoint_replays_active_turn(client, rt, conversation, panel_store_sync):
    rt.nats_client = FakePanelNatsClient()
    # mark the turn active the way the POST path would
    run_sync(panel_store.set_active_turn(conversation.id, "turnZ"))
    resp = client.get(
        f"/api/conversations/{conversation.id}/stream", headers=AUTH_HEADERS
    )
    assert resp.status_code == 200
    frames = [json.loads(line[6:]) for line in resp.text.splitlines()
              if line.startswith("data: ")]
    assert frames[0]["type"] == "delta" and frames[0]["turn_id"] == "turnZ"


def test_resume_endpoint_204_on_http_transport(client, rt, conversation):
    rt.nats_client = None
    resp = client.get(
        f"/api/conversations/{conversation.id}/stream", headers=AUTH_HEADERS
    )
    assert resp.status_code == 204
```

(`AUTH_HEADERS`, `run_sync`, fixture names: copy from the file's existing tests.)

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest packages/python/vystak-channel-panel/tests/test_api_messages_stream.py -v -k "nats or resume"`
Expected: FAIL — 404 on the GET route; POST path hits `agent_base_url` on a NATS subject

- [ ] **Step 3: Implement in `routes_messages.py`**

Add imports: `import uuid`, `from fastapi import Response`, `from vystak_channel_panel.turn_stream import browser_frame` (TurnAccumulator import already added in Task 6).

In `post_message`, replace the current `base_url = agent_base_url(route_entry)` + HTTP `gen()` selection with a branch **after** the user-row/title persistence (move the `add_message`/title block above the branch so both paths share it):

```python
        if rt.nats_client is not None:
            return await _post_message_nats(rt, conv, conv_id, text, user, title)
        base_url = agent_base_url(route_entry)
        # ... existing HTTP gen() path, unchanged ...
```

New module-level functions:

```python
async def _post_message_nats(rt, conv, conv_id: str, text: str, user, title: str):
    route_entry = rt.routes.get(conv.agent_name)
    turn_id = uuid.uuid4().hex
    await rt.panel_store.set_active_turn(conv_id, turn_id)
    try:
        subject = await rt.nats_client.start_turn(
            route_entry, text,
            conv_id=conv_id, turn_id=turn_id,
            previous_response_id=conv.last_response_id,
            user_id=user.id, project_id=conv.project_id,
        )
    except Exception as exc:  # noqa: BLE001 — surface as an SSE error frame
        logger.exception("createDetached failed conv=%s", conv_id)
        await rt.panel_store.clear_active_turn(conv_id, turn_id)

        async def err_gen():
            yield _sse({"type": "error", "message": f"agent unreachable: {exc}"})

        return StreamingResponse(err_gen(), media_type="text/event-stream")

    rt.spawn_persister(conv_id, turn_id, subject)
    gen = _proxy_turn(rt, subject, turn_id, title)
    return StreamingResponse(gen, media_type="text/event-stream")


async def _proxy_turn(rt, subject: str, turn_id: str, title: str | None):
    """Browser-facing SSE proxy over a turn's JetStream subject. Read-only:
    persistence belongs to the persister task, so any number of these can
    attach or vanish without consequence."""
    try:
        async for seq, ev in rt.nats_client.stream_turn_events(subject):
            if ev.type == "done":
                yield _sse({
                    "type": "done", "turn_id": turn_id, "seq": seq,
                    "response_id": ev.response_id, "title": title,
                })
                return
            frame = browser_frame(ev)
            frame["turn_id"] = turn_id
            frame["seq"] = seq
            yield _sse(frame)
            if ev.type == "error":
                return
    except Exception as exc:  # noqa: BLE001 — stream must not raise
        logger.exception("turn proxy failed subject=%s", subject)
        yield _sse({"type": "error", "message": str(exc), "turn_id": turn_id})
```

New route in `build_messages_router`:

```python
    @router.get("/{conv_id}/stream")
    async def resume_stream(conv_id: str, user: PanelUser = Depends(current_user)):
        conv = await require_conversation_access(rt, conv_id, user)
        if rt.nats_client is None or not conv.active_turn_id:
            return Response(status_code=204)
        route_entry = rt.routes.get(conv.agent_name)
        if route_entry is None:
            raise HTTPException(
                status_code=503, detail=f"agent not routed: {conv.agent_name}"
            )
        subject = rt.nats_client.turn_subject_for(
            route_entry, conv.id, conv.active_turn_id
        )
        gen = _proxy_turn(rt, subject, conv.active_turn_id, conv.title)
        return StreamingResponse(gen, media_type="text/event-stream")
```

- [ ] **Step 4: Run the panel suite**

Run: `uv run pytest packages/python/vystak-channel-panel/tests/ -v`
Expected: all PASS (HTTP-path tests unchanged and green)

- [ ] **Step 5: Lint and commit**

```bash
just lint-python
git add packages/python/vystak-channel-panel
git commit -m "feat(panel): NATS detached turn route + resumable stream endpoint"
```

---

### Task 9: Next.js — resume route + `useChat` resume

**Files:**
- Modify: `packages/typescript/vystak-panel/lib/panel.ts`
- Create: `packages/typescript/vystak-panel/app/api/chat/[id]/stream/route.ts`
- Modify: `packages/typescript/vystak-panel/components/chat.tsx`

**Interfaces:**
- AI SDK v5 contract (verified against current docs): `useChat({ resume: true })` fires a GET to `/api/chat/{id}/stream` on mount (`id` = the `useChat` id, which is already `conversationId` here); a 204 means nothing to resume; otherwise the response must be a UI message stream.

- [ ] **Step 1: Add the panel fetch helper.** In `lib/panel.ts`, after `streamConversationMessage`:

```typescript
export const resumeConversationStream = (email: string, convId: string) =>
  panelFetch(email, `/api/conversations/${convId}/stream`);
```

- [ ] **Step 2: Create the resume route handler**

```typescript
// packages/typescript/vystak-panel/app/api/chat/[id]/stream/route.ts
import { createUIMessageStreamResponse } from 'ai';
import { auth } from '@/auth';
import { resumeConversationStream } from '@/lib/panel';
import { panelStreamToUIChunks } from '@/lib/stream';

export async function GET(
  _req: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const session = await auth();
  const email = session?.user?.email?.toLowerCase();
  if (!email) return new Response('Unauthorized', { status: 401 });

  const { id } = await params;
  let upstream: Response;
  try {
    upstream = await resumeConversationStream(email, id);
  } catch {
    // Panel unreachable — nothing to resume is the safe answer here; the
    // page still renders persisted history.
    return new Response(null, { status: 204 });
  }
  if (upstream.status === 204 || !upstream.ok || !upstream.body) {
    return new Response(null, { status: 204 });
  }
  return createUIMessageStreamResponse({
    stream: panelStreamToUIChunks(upstream.body),
  });
}
```

- [ ] **Step 3: Enable resume in the chat component.** In `components/chat.tsx`, add `resume: true` to the `useChat` options (after `messages: initialMessages,`):

```typescript
    resume: true,
```

No transport change needed — the default reconnect pattern is exactly `/api/chat/{id}/stream`.

- [ ] **Step 4: Verify gates**

Run: `pnpm --filter vystak-panel run lint && just typecheck-typescript`
Expected: both PASS. If `vystak-panel` has a `test` script (check its `package.json`), run `pnpm --filter vystak-panel run test` too.

- [ ] **Step 5: Commit**

```bash
git add packages/typescript/vystak-panel
git commit -m "feat(panel-ui): resume in-flight streams via AI SDK resume"
```

---

### Task 10: Example — `examples/docker-panel-nats`

**Files:**
- Create: `examples/docker-panel-nats/` (copied from `examples/docker-panel`, minus deploy artifacts)

- [ ] **Step 1: Copy the example, excluding runtime state**

```bash
mkdir -p examples/docker-panel-nats
rsync -a --exclude '.vystak' --exclude '__pycache__' --exclude '.env' \
  examples/docker-panel/ examples/docker-panel-nats/
```

- [ ] **Step 2: Edit `examples/docker-panel-nats/vystak.py`.** Change the module docstring's first line to note the NATS transport, and the platform to:

```python
platform = ast.Platform(
    name="local",
    type="docker",
    provider=docker,
    namespace="panel-nats",
    transport=ast.Transport(
        name="bus",
        type="nats",
        config=ast.NatsConfig(jetstream=True),
    ),
)
```

(Namespace differs from docker-panel's `multi` so both examples can coexist on one machine. Everything else — agents, models, panel channel on port 18100 — stays identical.)

- [ ] **Step 3: Update `examples/docker-panel-nats/README.md`** (if the copied example has one): retitle for NATS, add one paragraph: deploying declares `transport: nats`, the panel starts turns via `responses/createDetached`, streams flow through JetStream (`vystak-panel-nats-streams` stream on the `vystak-nats` broker), and in-flight responses survive browser refreshes and panel restarts; resume replays from the start of the turn.

- [ ] **Step 4: Sanity-check the definition loads**

Run: `uv run python -c "import pathlib, sys; sys.path.insert(0, 'examples/docker-panel-nats'); import runpy; runpy.run_path('examples/docker-panel-nats/vystak.py')"`
Expected: exits 0 (definition parses; `ast.NatsConfig` resolves).

- [ ] **Step 5: Commit**

```bash
git add examples/docker-panel-nats
git commit -m "docs(examples): docker-panel-nats — panel on the NATS transport"
```

---

### Task 11: Release test — detached persistence over NATS

**Files:**
- Create: `packages/python/vystak-provider-docker/tests/release/test_panel_nats_resume.py`

**Interfaces:**
- Consumes conftest fixtures `project` (tmp dir with sentinel `.env` + guaranteed destroy) and helpers `assert_apply_ok`, `assert_destroy_ok`, `docker_running` (see `test_D4_docker_default_chat_stream.py` for the idioms).
- Marker: `release_integration` (+ `docker`), so default pytest skips it.

- [ ] **Step 1: Write the test.** The agents run with sentinel credentials, so the LLM call fails — which is exactly what we exploit: the failure is published to JetStream as `response.failed` and the panel's **detached** persister must still write the assistant row and clear the active turn even though the client dropped the POST immediately.

```python
"""Panel × NATS — detached, resumable streaming (integration tier).

Deploys the panel channel on the NATS transport, starts a turn, and drops
the POST connection immediately. With sentinel credentials the agent turn
fails fast — but the failure flows through JetStream to the panel's
detached persister, which must write the assistant row and clear
`active_turn_id` with no browser attached. Then the resume endpoint must
report 204 (turn over). This proves the decoupling that HTTP streaming
cannot provide: the turn outcome lands regardless of the requester.
"""

from __future__ import annotations

import json
import time

import httpx
import pytest

from .conftest import assert_apply_ok, assert_destroy_ok, docker_running

pytestmark = [pytest.mark.release_integration, pytest.mark.docker]

PANEL_PORT = 18111
SERVICE_TOKEN = "test-panel-token"
ADMIN = "admin@example.test"

PANEL_NATS_YAML = f"""\
providers:
  docker: {{type: docker}}
  anthropic: {{type: anthropic}}
platforms:
  local:
    type: docker
    provider: docker
    namespace: panel-nats-test
    transport:
      name: bus
      type: nats
      config: {{type: nats, jetstream: true}}
models:
  sonnet: {{provider: anthropic, model_name: claude-sonnet-4-20250514}}
channels:
  - name: panel
    type: panel
    platform: local
    config: {{port: {PANEL_PORT}}}
    secrets:
      - {{name: PANEL_SERVICE_TOKEN}}
agents:
  - name: paneled
    default_model: sonnet
    platform: local
    secrets:
      - {{name: ANTHROPIC_API_KEY}}
      - {{name: ANTHROPIC_API_URL}}
"""


def _panel(path: str) -> str:
    return f"http://localhost:{PANEL_PORT}{path}"


def _headers(user: str = ADMIN) -> dict:
    return {"Authorization": f"Bearer {SERVICE_TOKEN}", "X-Panel-User": user}


def test_panel_nats_detached_persistence(project):
    (project / "vystak.yaml").write_text(PANEL_NATS_YAML)
    with (project / ".env").open("a") as f:
        f.write(f"PANEL_SERVICE_TOKEN={SERVICE_TOKEN}\n")

    assert_apply_ok(cwd=project)
    assert docker_running("vystak-nats")
    assert docker_running("vystak-channel-panel")

    with httpx.Client(timeout=30.0) as client:
        # panel readiness
        for _ in range(30):
            try:
                if client.get(_panel("/health")).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(1)
        else:
            pytest.fail("panel API never became healthy")

        # bootstrap admin + conversation
        client.post(_panel("/api/setup"),
                    json={"email": ADMIN, "name": "Admin", "image": ""},
                    headers=_headers())
        boot = client.get(_panel("/api/bootstrap"), headers=_headers()).json()
        project_id = boot["default_project_id"]
        conv = client.post(
            _panel(f"/api/projects/{project_id}/conversations"),
            json={"agent_name": "paneled"}, headers=_headers(),
        ).json()["conversation"]

        # Start a turn and DROP the connection immediately: stream one line
        # at most, then close. The detached persister must finish the job.
        try:
            with client.stream(
                "POST", _panel(f"/api/conversations/{conv['id']}/messages"),
                json={"text": "ping"}, headers=_headers(),
            ) as resp:
                assert resp.status_code == 200
        except httpx.HTTPError:
            pass  # dropping mid-stream can surface as a transport error

        # Poll for the detached outcome: assistant row persisted with a
        # turn_id and the active turn cleared.
        deadline = time.time() + 120
        assistant_rows: list[dict] = []
        while time.time() < deadline:
            msgs = client.get(
                _panel(f"/api/conversations/{conv['id']}/messages"),
                headers=_headers(),
            ).json()["messages"]
            assistant_rows = [m for m in msgs if m["role"] == "assistant"]
            if assistant_rows:
                break
            time.sleep(2)
        # Sentinel key -> turn fails with no output; an errored empty turn
        # writes no row (matches HTTP semantics), so accept either a row OR
        # a cleared active turn as proof the persister ran to completion.
        resume = client.get(
            _panel(f"/api/conversations/{conv['id']}/stream"), headers=_headers()
        )
        assert resume.status_code == 204, (
            f"expected turn to be over (204), got {resume.status_code}"
        )
        if assistant_rows:
            assert assistant_rows[0].get("turn_id"), "assistant row missing turn_id"

    assert_destroy_ok(cwd=project)
```

**Note for the implementer:** if the panel messages-list endpoint path or response shape differs (check `routes_conversations.py` / the panel API), adjust the polling block — the assertions that matter are (1) resume returns 204 once the persister finished, (2) any persisted assistant row carries `turn_id`. If `assert_apply_ok`/`assert_destroy_ok` require extra fixtures (e.g. `docker_required`), copy the decorator/fixture usage from `test_D4_docker_default_chat_stream.py` exactly.

- [ ] **Step 2: Run it (requires Docker; ~2–4 min)**

Run: `uv run pytest packages/python/vystak-provider-docker/tests/release/test_panel_nats_resume.py -v -m release_integration`
Expected: PASS. Also confirm default runs still skip it: `uv run pytest packages/python/vystak-provider-docker/tests/release/test_panel_nats_resume.py -v` → deselected/skipped.

- [ ] **Step 3: Full regression gate**

Run: `just ci-live`
Expected: all four gates PASS.

- [ ] **Step 4: Commit**

```bash
git add packages/python/vystak-provider-docker/tests/release
git commit -m "test(release): panel NATS detached persistence cell"
```

---

## Manual end-to-end verification (after all tasks)

1. `cd examples/docker-panel-nats && cp .env.example .env` (fill real `ANTHROPIC_API_KEY` + `PANEL_SERVICE_TOKEN`), `uv run vystak apply`.
2. Run the Next.js panel (`pnpm --filter vystak-panel dev` with `PANEL_API_URL=http://localhost:18100`, `PANEL_SERVICE_TOKEN` matching).
3. Ask an agent something long ("write 3 paragraphs about NATS"), refresh the browser mid-answer → the answer continues streaming after reload (replayed from the start of the turn).
4. Ask again, and mid-answer `docker restart vystak-channel-panel` → after the panel returns, reload: the completed answer is persisted (the detached agent turn + JetStream held it).
5. `docker exec vystak-nats nats-server --jetstream` sanity is implicit — `vystak-panel-nats-streams` stream exists iff turns ran.
