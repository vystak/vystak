"""Tests for the in-container NATS↔HTTP bridge."""

from __future__ import annotations

import asyncio
import json
import os
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from _vystak.runtime.nats_bridge import NatsHttpBridge, maybe_build_bridge


def test_maybe_build_bridge_noop_when_transport_unset(monkeypatch):
    """HTTP transport (default) → no bridge, lifespan path is clean no-op."""
    monkeypatch.delenv("VYSTAK_TRANSPORT_TYPE", raising=False)
    agent = SimpleNamespace(name="hero")
    assert maybe_build_bridge(agent, port=8000) is None


def test_maybe_build_bridge_noop_when_transport_http(monkeypatch):
    monkeypatch.setenv("VYSTAK_TRANSPORT_TYPE", "http")
    agent = SimpleNamespace(name="hero")
    assert maybe_build_bridge(agent, port=8000) is None


def test_maybe_build_bridge_noop_without_nats_url(monkeypatch):
    """Misconfig (NATS but no broker URL) → log + skip, never crash."""
    monkeypatch.setenv("VYSTAK_TRANSPORT_TYPE", "nats")
    monkeypatch.delenv("VYSTAK_NATS_URL", raising=False)
    monkeypatch.setenv("VYSTAK_NATS_SUBJECT", "vystak.default.agents.hero.tasks")
    agent = SimpleNamespace(name="hero")
    assert maybe_build_bridge(agent, port=8000) is None


def test_maybe_build_bridge_uses_explicit_subject(monkeypatch):
    """VYSTAK_NATS_SUBJECT (set by provider) wins over derivation."""
    monkeypatch.setenv("VYSTAK_TRANSPORT_TYPE", "nats")
    monkeypatch.setenv("VYSTAK_NATS_URL", "nats://localhost:4222")
    monkeypatch.setenv("VYSTAK_NATS_SUBJECT", "explicit.subject")
    agent = SimpleNamespace(name="hero")
    bridge = maybe_build_bridge(agent, port=9000)
    assert bridge is not None
    assert bridge._subject == "explicit.subject"
    assert bridge._local_url == "http://localhost:9000/a2a"
    assert bridge._local_base == "http://localhost:9000"
    assert bridge._queue_group == "agents.hero"


def test_maybe_build_bridge_derives_subject_when_unset(monkeypatch):
    """No explicit subject → derive from name + namespace + prefix."""
    monkeypatch.setenv("VYSTAK_TRANSPORT_TYPE", "nats")
    monkeypatch.setenv("VYSTAK_NATS_URL", "nats://localhost:4222")
    monkeypatch.setenv("VYSTAK_NATS_SUBJECT_PREFIX", "vystak-nats")
    monkeypatch.setenv("VYSTAK_NATS_NAMESPACE", "multi-nats")
    monkeypatch.delenv("VYSTAK_NATS_SUBJECT", raising=False)
    agent = SimpleNamespace(name="weather-agent")
    bridge = maybe_build_bridge(agent, port=8000)
    assert bridge is not None
    assert bridge._subject == "vystak-nats.multi-nats.agents.weather-agent.tasks"


def test_maybe_build_bridge_wires_a_sqlite_journal(monkeypatch):
    """Without a journal, everything from Task 6 onward (checkpoint
    boundaries, re-drive on startup) is inert. Bridge construction must
    default to a concrete SqliteTurnJournal."""
    from _vystak.runtime.turn_journal import SqliteTurnJournal

    monkeypatch.setenv("VYSTAK_TRANSPORT_TYPE", "nats")
    monkeypatch.setenv("VYSTAK_NATS_URL", "nats://localhost:4222")
    monkeypatch.setenv("VYSTAK_NATS_SUBJECT", "explicit.subject")
    agent = SimpleNamespace(name="hero")
    bridge = maybe_build_bridge(agent, port=9000)
    assert bridge is not None
    assert isinstance(bridge._journal, SqliteTurnJournal)


def test_resolve_turns_path_env_override(monkeypatch):
    from _vystak.runtime.nats_bridge import resolve_turns_path

    monkeypatch.setenv("VYSTAK_TURNS_PATH", "/tmp/custom-turns.db")
    assert resolve_turns_path() == "/tmp/custom-turns.db"


def test_resolve_turns_path_falls_back_to_tempdir_when_no_data_dir(monkeypatch, tmp_path):
    import tempfile

    from _vystak.runtime import nats_bridge as nats_bridge_module
    from _vystak.runtime.nats_bridge import resolve_turns_path

    missing = tmp_path / "nope"
    monkeypatch.delenv("VYSTAK_TURNS_PATH", raising=False)
    monkeypatch.setattr(nats_bridge_module, "_DATA_DIR", str(missing))
    path = resolve_turns_path()
    assert path == os.path.join(tempfile.gettempdir(), "vystak-turns.db")
    assert not path.startswith(str(missing))


# ---------------------------------------------------------------------------
# Bridge forwarding behavior
# ---------------------------------------------------------------------------


class _FakeMsg:
    def __init__(self, data: bytes, reply: str = "") -> None:
        self.data = data
        self.reply = reply


class _FakeNatsClient:
    """Records publishes; stops shutdown from blocking on real I/O."""

    def __init__(self) -> None:
        self.is_closed = False
        self.published: list[tuple[str, bytes]] = []
        self.subscribed: tuple[str, str, Any] | None = None

    async def subscribe(self, subject, queue=None, cb=None):  # noqa: ANN001
        self.subscribed = (subject, queue, cb)

        class _Sub:
            async def unsubscribe(_self):  # noqa: ANN001
                return None

        return _Sub()

    async def publish(self, subject, payload):  # noqa: ANN001
        self.published.append((subject, payload))

    async def close(self) -> None:
        self.is_closed = True


@pytest.mark.asyncio
async def test_bridge_forwards_envelope_to_local_a2a(monkeypatch):
    """Inbound NATS message → POST /a2a → publish HTTP body on reply inbox."""
    fake_nc = _FakeNatsClient()
    import nats

    async def _fake_connect(url, *args, **kwargs):  # noqa: ANN001
        return fake_nc

    monkeypatch.setattr(nats, "connect", _fake_connect)

    # Capture the POST body and return a synthetic JSON-RPC success.
    posted_url: list[str] = []
    posted_body: list[bytes] = []

    class _FakeAsyncClient:
        def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
            pass

        async def post(self, url, *, content, headers):  # noqa: ANN001
            posted_url.append(url)
            posted_body.append(content)
            return httpx.Response(
                200,
                content=json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": "rpc-1",
                        "result": {
                            "status": {
                                "state": "completed",
                                "message": {"parts": [{"text": "pong"}]},
                            }
                        },
                    }
                ).encode(),
            )

        async def aclose(self) -> None:
            return None

    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)

    bridge = NatsHttpBridge(
        nats_url="nats://localhost:4222",
        subject="vystak.default.agents.hero.tasks",
        queue_group="agents.hero",
        local_url="http://localhost:8000/a2a",
    )
    await bridge.start()

    envelope = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": "rpc-1",
            "method": "message/send",
            "params": {"message": {"role": "user", "messageId": "m1", "parts": [{"text": "hi"}]}},
        }
    ).encode()
    msg = _FakeMsg(data=envelope, reply="_INBOX.abc")

    await bridge._forward(msg)

    # The bridge POSTed the original bytes to the local /a2a.
    assert posted_url == ["http://localhost:8000/a2a"]
    assert posted_body == [envelope]
    # The bridge published the HTTP response back on the reply inbox.
    assert len(fake_nc.published) == 1
    reply_subject, reply_payload = fake_nc.published[0]
    assert reply_subject == "_INBOX.abc"
    body = json.loads(reply_payload)
    assert body["result"]["status"]["state"] == "completed"

    await bridge.stop()
    assert fake_nc.is_closed is True


@pytest.mark.asyncio
async def test_bridge_returns_jsonrpc_error_on_local_http_failure(monkeypatch):
    """Localhost POST fails → publish a JSON-RPC error envelope on inbox."""
    fake_nc = _FakeNatsClient()
    import nats

    async def _fake_connect(url, *args, **kwargs):  # noqa: ANN001
        return fake_nc

    monkeypatch.setattr(nats, "connect", _fake_connect)

    class _FailingClient:
        def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
            pass

        async def post(self, url, *, content, headers):  # noqa: ANN001
            raise httpx.ConnectError("connection refused")

        async def aclose(self) -> None:
            return None

    monkeypatch.setattr(httpx, "AsyncClient", _FailingClient)

    bridge = NatsHttpBridge(
        nats_url="nats://localhost:4222",
        subject="vystak.default.agents.hero.tasks",
        queue_group="agents.hero",
        local_url="http://localhost:8000/a2a",
    )
    await bridge.start()

    envelope = json.dumps(
        {"jsonrpc": "2.0", "id": "rpc-9", "method": "message/send", "params": {}}
    ).encode()
    await bridge._forward(_FakeMsg(data=envelope, reply="_INBOX.xyz"))

    assert len(fake_nc.published) == 1
    _, payload = fake_nc.published[0]
    body = json.loads(payload)
    assert body["error"]["code"] == -32603
    assert "local /a2a request failed" in body["error"]["message"]

    await bridge.stop()


@pytest.mark.asyncio
async def test_bridge_handles_invalid_json_payload(monkeypatch):
    """Malformed inbound bytes → publish parse-error envelope, don't crash."""
    fake_nc = _FakeNatsClient()
    import nats

    async def _fake_connect(url, *args, **kwargs):  # noqa: ANN001
        return fake_nc

    monkeypatch.setattr(nats, "connect", _fake_connect)

    class _NoCallClient:
        def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
            pass

        async def post(self, *args, **kwargs):  # noqa: ANN002, ANN003
            raise AssertionError("HTTP should not be called for invalid payload")

        async def aclose(self) -> None:
            return None

    monkeypatch.setattr(httpx, "AsyncClient", _NoCallClient)

    bridge = NatsHttpBridge(
        nats_url="nats://localhost:4222",
        subject="vystak.default.agents.hero.tasks",
        queue_group="agents.hero",
        local_url="http://localhost:8000/a2a",
    )
    await bridge.start()

    await bridge._forward(_FakeMsg(data=b"not-json", reply="_INBOX.bad"))

    assert any(b"parse error" in p[1] for p in fake_nc.published)

    await bridge.stop()


@pytest.mark.asyncio
async def test_bridge_silently_drops_when_no_reply_subject(monkeypatch):
    """A NATS message without a reply inbox (fire-and-forget) → no publish."""
    fake_nc = _FakeNatsClient()
    import nats

    async def _fake_connect(url, *args, **kwargs):  # noqa: ANN001
        return fake_nc

    monkeypatch.setattr(nats, "connect", _fake_connect)

    class _OkClient:
        def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
            pass

        async def post(self, url, *, content, headers):  # noqa: ANN001
            return httpx.Response(200, content=b'{"jsonrpc":"2.0","id":"x","result":{}}')

        async def aclose(self) -> None:
            return None

    monkeypatch.setattr(httpx, "AsyncClient", _OkClient)

    bridge = NatsHttpBridge(
        nats_url="nats://localhost:4222",
        subject="vystak.default.agents.hero.tasks",
        queue_group="agents.hero",
        local_url="http://localhost:8000/a2a",
    )
    await bridge.start()
    envelope = json.dumps(
        {"jsonrpc": "2.0", "id": "rpc-9", "method": "message/send", "params": {}}
    ).encode()
    await bridge._forward(_FakeMsg(data=envelope, reply=""))

    # No reply inbox → bridge must not attempt a publish (would crash with
    # an empty subject in nats-py).
    assert fake_nc.published == []
    await bridge.stop()


@pytest.mark.asyncio
async def test_bridge_propagates_traceparent_to_local_a2a(monkeypatch):
    """Inbound metadata.traceparent → forwarded as HTTP traceparent header.

    Confirms the bridge extracts the upstream W3C trace context and
    re-injects it onto the local /a2a call so FastAPIInstrumentor on the
    receiver can continue the trace.
    """
    pytest.importorskip("opentelemetry.exporter.otlp.proto.grpc.trace_exporter")
    from opentelemetry import trace
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider

    # Bare provider so propagate.inject() emits real traceparent headers
    # for the active context.
    provider = TracerProvider(resource=Resource.create({"service.name": "test"}))
    trace.set_tracer_provider(provider)

    fake_nc = _FakeNatsClient()
    import nats

    async def _fake_connect(url, *args, **kwargs):  # noqa: ANN001
        return fake_nc

    monkeypatch.setattr(nats, "connect", _fake_connect)

    captured_headers: list[dict] = []

    class _CapturingClient:
        def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
            pass

        async def post(self, url, *, content, headers):  # noqa: ANN001
            captured_headers.append(dict(headers))
            return httpx.Response(
                200,
                content=json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": "x",
                        "result": {"status": {"message": {"parts": [{"text": "ok"}]}}},
                    }
                ).encode(),
            )

        async def aclose(self) -> None:
            return None

    monkeypatch.setattr(httpx, "AsyncClient", _CapturingClient)

    bridge = NatsHttpBridge(
        nats_url="nats://localhost:4222",
        subject="vystak.default.agents.hero.tasks",
        queue_group="agents.hero",
        local_url="http://localhost:8000/a2a",
    )
    await bridge.start()

    upstream_tp = "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"
    envelope = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": "rpc-1",
            "method": "message/send",
            "params": {
                "message": {
                    "role": "user",
                    "messageId": "m1",
                    "parts": [{"text": "hi"}],
                    "metadata": {"traceparent": upstream_tp},
                },
            },
        }
    ).encode()

    await bridge._forward(_FakeMsg(data=envelope, reply="_INBOX.abc"))

    assert len(captured_headers) == 1
    headers = captured_headers[0]
    # Re-injected via propagate.inject — same trace ID as upstream so the
    # span chain links back to the publisher.
    assert "traceparent" in headers
    parts = headers["traceparent"].split("-")
    assert len(parts) == 4
    assert parts[1] == "0af7651916cd43dd8448eb211c80319c"

    await bridge.stop()
    provider.shutdown()


# ---------------------------------------------------------------------------
# Responses-API proxying (responses/create, responses/get)
# ---------------------------------------------------------------------------


def _bridge_with_mock_http(handler: Any) -> tuple[NatsHttpBridge, _FakeNatsClient]:
    """Build a bridge with a fake NATS client and a mocked local HTTP client,
    bypassing bridge.start() (no real NATS connect needed for these tests)."""
    bridge = NatsHttpBridge(
        nats_url="nats://ignored:4222",
        subject="vystak.default.agents.hero.tasks",
        queue_group="agents.hero",
        local_url="http://localhost:8000/a2a",
        local_base="http://localhost:8000",
    )
    fake_nc = _FakeNatsClient()
    bridge._nc = fake_nc
    bridge._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return bridge, fake_nc


@pytest.mark.asyncio
async def test_responses_create_proxies_to_local_v1_responses():
    """responses/create → POST /v1/responses (forced non-stream) → JSON-RPC result."""
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"id": "resp_1", "status": "completed"})

    bridge, fake_nc = _bridge_with_mock_http(handler)
    envelope = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": "42",
            "method": "responses/create",
            "params": {"request": {"input": "hi", "stream": True}},
        }
    ).encode()
    await bridge._forward(_FakeMsg(data=envelope, reply="_INBOX.r1"))

    assert seen["url"] == "http://localhost:8000/v1/responses"
    assert seen["body"]["stream"] is False  # forced non-stream

    assert len(fake_nc.published) == 1
    reply_subject, payload = fake_nc.published[0]
    reply = json.loads(payload)
    assert reply_subject == "_INBOX.r1"
    assert reply["id"] == "42"
    assert reply["result"]["id"] == "resp_1"


@pytest.mark.asyncio
async def test_responses_get_proxies_and_maps_404_to_null_result():
    """responses/get → GET /v1/responses/{id}; 404 maps to result: null."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "http://localhost:8000/v1/responses/resp_x"
        return httpx.Response(404, json={"detail": "not found"})

    bridge, fake_nc = _bridge_with_mock_http(handler)
    envelope = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": "43",
            "method": "responses/get",
            "params": {"response_id": "resp_x"},
        }
    ).encode()
    await bridge._forward(_FakeMsg(data=envelope, reply="_INBOX.r1"))

    assert len(fake_nc.published) == 1
    _, payload = fake_nc.published[0]
    reply = json.loads(payload)
    assert reply["id"] == "43"
    assert reply["result"] is None


# ---------------------------------------------------------------------------
# responses/createDetached — detached JetStream turn publisher
# ---------------------------------------------------------------------------


class _RecordingJS:
    """Fake JetStream context: records add_stream calls and decoded publishes."""

    def __init__(self) -> None:
        self.published: list[tuple[str, dict]] = []
        self.streams_added: list = []

    async def add_stream(self, cfg):  # noqa: ANN001
        self.streams_added.append(cfg)

    async def update_stream(self, cfg):  # noqa: ANN001
        pass

    async def publish(self, subject, payload):  # noqa: ANN001
        self.published.append((subject, json.loads(payload)))


def _sse_bytes(*events: dict, done: bool = True) -> bytes:
    lines = [f"data: {json.dumps(e)}\n\n" for e in events]
    if done:
        lines.append("data: [DONE]\n\n")
    return "".join(lines).encode()


@pytest.mark.asyncio
async def test_create_detached_acks_then_publishes_stream_to_jetstream():
    """responses/createDetached acks immediately with {turn_id, stream_subject},
    then a detached task streams every SSE event to JetStream as {seq, event}."""
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

    bridge, fake_nc = _bridge_with_mock_http(handler)
    js = _RecordingJS()
    fake_nc.jetstream = lambda: js

    envelope = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": "7",
            "method": "responses/createDetached",
            "params": {
                "request": {"input": "hi"},
                "turn_id": "t1",
                "stream_subject": "vystak.multi.streams.c1.t1",
            },
        }
    ).encode()
    await bridge._forward(_FakeMsg(data=envelope, reply="_INBOX.r7"))

    # The ack must be published immediately, before the stream is drained.
    assert len(fake_nc.published) == 1
    reply_subject, payload = fake_nc.published[0]
    assert reply_subject == "_INBOX.r7"
    ack = json.loads(payload)
    assert ack["result"] == {"turn_id": "t1", "stream_subject": "vystak.multi.streams.c1.t1"}

    # Drain the detached task.
    await asyncio.gather(*bridge._inflight)

    assert js.streams_added and js.streams_added[0].name == "vystak-multi-streams"
    subjects = {s for s, _ in js.published}
    assert subjects == {"vystak.multi.streams.c1.t1"}
    payloads = [p for _, p in js.published]
    assert [p["seq"] for p in payloads] == [0, 1, 2, 3]
    assert payloads[-1]["event"]["type"] == "response.completed"


@pytest.mark.asyncio
async def test_create_detached_publishes_failed_event_on_http_error():
    """A non-200 local /v1/responses response publishes a single synthesized
    response.failed terminal event so consumers stop waiting."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    bridge, fake_nc = _bridge_with_mock_http(handler)
    js = _RecordingJS()
    fake_nc.jetstream = lambda: js

    envelope = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": "8",
            "method": "responses/createDetached",
            "params": {
                "request": {"input": "hi"},
                "turn_id": "t2",
                "stream_subject": "vystak.multi.streams.c1.t2",
            },
        }
    ).encode()
    await bridge._forward(_FakeMsg(data=envelope, reply="_INBOX.r8"))
    await asyncio.gather(*bridge._inflight)

    payloads = [p for _, p in js.published]
    assert len(payloads) == 1
    assert payloads[0]["event"]["type"] == "response.failed"


class _FailingEnsureJS(_RecordingJS):
    """add_stream AND update_stream both fail — _ensure_turn_stream can't
    converge, but the stream may still exist and be publishable."""

    async def add_stream(self, cfg):  # noqa: ANN001
        raise RuntimeError("add_stream conflict")

    async def update_stream(self, cfg):  # noqa: ANN001
        raise RuntimeError("update_stream also failed")


@pytest.mark.asyncio
async def test_create_detached_publishes_failed_event_when_ensure_stream_fails():
    """_ensure_turn_stream failing (add_stream AND update_stream both raise)
    still publishes exactly one synthesized response.failed terminal event,
    so the JetStream consumer doesn't hang until its idle timeout."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("local /v1/responses should not be called")

    bridge, fake_nc = _bridge_with_mock_http(handler)
    js = _FailingEnsureJS()
    fake_nc.jetstream = lambda: js

    envelope = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": "10",
            "method": "responses/createDetached",
            "params": {
                "request": {"input": "hi"},
                "turn_id": "t3",
                "stream_subject": "vystak.multi.streams.c1.t3",
            },
        }
    ).encode()
    await bridge._forward(_FakeMsg(data=envelope, reply="_INBOX.r10"))
    await asyncio.gather(*bridge._inflight)

    assert len(js.published) == 1
    subject, payload = js.published[0]
    assert subject == "vystak.multi.streams.c1.t3"
    assert payload["event"]["type"] == "response.failed"


@pytest.mark.asyncio
async def test_create_detached_missing_params_is_invalid_params_error():
    """Missing request/turn_id/stream_subject → JSON-RPC -32602, no task spawned."""
    bridge, fake_nc = _bridge_with_mock_http(lambda r: httpx.Response(200))
    envelope = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": "9",
            "method": "responses/createDetached",
            "params": {"request": {"input": "hi"}},
        }
    ).encode()
    await bridge._forward(_FakeMsg(data=envelope, reply="_INBOX.r9"))

    assert len(fake_nc.published) == 1
    _, payload = fake_nc.published[0]
    reply = json.loads(payload)
    assert reply["error"]["code"] == -32602
    assert not bridge._inflight
