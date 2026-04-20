"""Tests for NatsTransport."""

from __future__ import annotations

import asyncio
import contextlib
import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from vystak.transport import A2AEvent, A2AMessage, A2AResult
from vystak.transport.contract import TransportContract
from vystak_transport_nats import NatsTransport

# ---------------------------------------------------------------------------
# Unit tests — no NATS server required
# ---------------------------------------------------------------------------


class TestNatsTransportUnit:
    """Unit tests for NatsTransport helpers. No live NATS connection needed."""

    def test_type_and_streaming(self):
        t = NatsTransport(url="nats://localhost:4222")
        assert t.type == "nats"
        assert t.supports_streaming is True

    def test_resolve_address_default_prefix(self):
        t = NatsTransport(url="nats://localhost:4222")
        addr = t.resolve_address("echo.agents.default")
        assert addr == "vystak.default.agents.echo.tasks"

    def test_resolve_address_custom_prefix_and_namespace(self):
        t = NatsTransport(url="nats://localhost:4222", subject_prefix="myapp")
        addr = t.resolve_address("weather.agents.prod")
        assert addr == "myapp.prod.agents.weather.tasks"

    def test_resolve_address_invalid_canonical_raises(self):
        t = NatsTransport(url="nats://localhost:4222")
        with pytest.raises(ValueError):
            t.resolve_address("badname")

    def test_build_envelope_structure(self):
        t = NatsTransport(url="nats://localhost:4222")
        msg = A2AMessage.from_text("hello", correlation_id="cid-123")
        data = t._build_envelope("tasks/send", msg, {"extra": "meta"})
        body = json.loads(data)
        assert body["jsonrpc"] == "2.0"
        assert body["method"] == "tasks/send"
        assert "id" in body  # auto-generated uuid
        params = body["params"]
        assert params["id"] == "cid-123"
        assert params["message"]["role"] == "user"
        assert params["message"]["parts"] == [{"text": "hello"}]
        assert params["metadata"]["extra"] == "meta"

    def test_parse_result_extracts_text(self):
        t = NatsTransport(url="nats://localhost:4222")
        body = {
            "jsonrpc": "2.0",
            "id": "req-1",
            "result": {
                "status": {"message": {"parts": [{"text": "hello"}, {"text": " world"}]}},
                "correlation_id": "cid-abc",
            },
        }
        result = t._parse_result(body, "fallback-cid")
        assert result.text == "hello world"
        assert result.correlation_id == "cid-abc"

    def test_parse_result_uses_fallback_cid(self):
        t = NatsTransport(url="nats://localhost:4222")
        body = {"result": {"status": {"message": {"parts": [{"text": "hi"}]}}}}
        result = t._parse_result(body, "fb-cid")
        assert result.correlation_id == "fb-cid"

    def test_parse_result_empty_body(self):
        t = NatsTransport(url="nats://localhost:4222")
        result = t._parse_result({}, "fallback")
        assert result.text == ""
        assert result.correlation_id == "fallback"

    @pytest.mark.asyncio
    async def test_connect_caches_client(self):
        """_connect() must return the same client on repeated calls."""
        t = NatsTransport(url="nats://localhost:4222")
        mock_client = MagicMock()
        mock_client.is_closed = False

        with patch("nats.connect", new_callable=AsyncMock, return_value=mock_client) as m:
            c1 = await t._connect()
            c2 = await t._connect()
            assert c1 is c2
            # nats.connect should only be called once
            m.assert_awaited_once()

    def test_build_envelope_for_method_shape(self):
        t = NatsTransport(url="nats://fake:4222")
        env = t._build_envelope_for_method(
            "responses/create", {"request": {"model": "m"}}, {"trace": "t1"}
        )
        body = json.loads(env)
        assert body["method"] == "responses/create"
        assert body["params"]["request"]["model"] == "m"
        assert body["metadata"]["trace"] == "t1"

    def test_is_responses_terminal(self):
        assert NatsTransport._is_responses_terminal({"type": "response.completed"}) is True
        assert NatsTransport._is_responses_terminal({"type": "response.output_text.delta"}) is False
        assert NatsTransport._is_responses_terminal({}) is False

    def test_is_a2a_terminal(self):
        assert NatsTransport._is_a2a_terminal({"final": True}) is True
        assert NatsTransport._is_a2a_terminal({"final": False}) is False
        assert NatsTransport._is_a2a_terminal({}) is False


# ---------------------------------------------------------------------------
# _handle_inbound — method routing unit tests (no NATS server required)
# ---------------------------------------------------------------------------


class _FakeDispatcher:
    """Records all dispatch calls for assertion. Implements ServerDispatcherProtocol."""

    def __init__(self) -> None:
        self.a2a_calls: list[tuple[A2AMessage, dict]] = []
        self.a2a_stream_calls: list[tuple[A2AMessage, dict]] = []
        self.responses_create_calls: list[tuple[dict, dict]] = []
        self.responses_create_stream_calls: list[tuple[dict, dict]] = []
        self.responses_get_calls: list[str] = []
        self.create_stream_chunks: list[dict] = [{"type": "response.completed"}]

    async def dispatch_a2a(self, message: A2AMessage, metadata: dict) -> A2AResult:
        self.a2a_calls.append((message, metadata))
        return A2AResult(
            text="ok",
            correlation_id=message.correlation_id,
            metadata={},
        )

    def dispatch_a2a_stream(self, message: A2AMessage, metadata: dict):
        self.a2a_stream_calls.append((message, metadata))

        async def _gen():
            yield A2AEvent(type="final", text="chunk", final=True)

        return _gen()

    async def dispatch_responses_create(self, request: dict, metadata: dict) -> dict:
        self.responses_create_calls.append((request, metadata))
        return {"id": "resp-1", "status": "completed"}

    def dispatch_responses_create_stream(self, request: dict, metadata: dict):
        self.responses_create_stream_calls.append((request, metadata))
        chunks = self.create_stream_chunks

        async def _gen():
            for c in chunks:
                yield c

        return _gen()

    async def dispatch_responses_get(self, response_id: str):
        self.responses_get_calls.append(response_id)
        return {"id": response_id} if response_id != "missing" else None


class _FakeMsg:
    """Stand-in for a ``nats.aio.msg.Msg`` that records publishes via ``reply``."""

    def __init__(self, reply: str = "_INBOX.test") -> None:
        self.reply = reply


class _FakeNats:
    """Minimal NATS client that records publishes for assertion."""

    def __init__(self) -> None:
        self.published: list[tuple[str, bytes]] = []

    async def publish(self, subject: str, data: bytes) -> None:
        self.published.append((subject, data))


class TestNatsHandleInboundRouting:
    """Exercises _handle_inbound in isolation. No NATS required."""

    @pytest.mark.asyncio
    async def test_tasks_send_routes_to_dispatch_a2a(self):
        t = NatsTransport(url="nats://fake:4222")
        dispatcher = _FakeDispatcher()
        nc = _FakeNats()
        msg = _FakeMsg()
        body = {
            "jsonrpc": "2.0",
            "id": "req-1",
            "method": "tasks/send",
            "params": {
                "id": "cid-1",
                "message": {"role": "user", "parts": [{"text": "hi"}]},
                "metadata": {"k": "v"},
            },
        }
        await t._handle_inbound(body, msg, dispatcher, nc)
        assert len(dispatcher.a2a_calls) == 1
        m, meta = dispatcher.a2a_calls[0]
        assert m.correlation_id == "cid-1"
        assert meta == {"k": "v"}
        # Reply envelope wraps the A2AResult in A2A-shaped status body.
        assert len(nc.published) == 1
        reply = json.loads(nc.published[0][1])
        assert reply["result"]["status"]["message"]["parts"][0]["text"] == "ok"

    @pytest.mark.asyncio
    async def test_tasks_send_subscribe_routes_to_dispatch_a2a_stream(self):
        t = NatsTransport(url="nats://fake:4222")
        dispatcher = _FakeDispatcher()
        nc = _FakeNats()
        msg = _FakeMsg()
        body = {
            "jsonrpc": "2.0",
            "id": "req-2",
            "method": "tasks/sendSubscribe",
            "params": {
                "id": "cid-2",
                "message": {"role": "user", "parts": [{"text": "hi"}]},
                "metadata": {},
            },
        }
        await t._handle_inbound(body, msg, dispatcher, nc)
        assert len(dispatcher.a2a_stream_calls) == 1
        # One streamed event published
        assert len(nc.published) == 1
        ev = json.loads(nc.published[0][1])
        assert ev["final"] is True
        assert ev["text"] == "chunk"

    @pytest.mark.asyncio
    async def test_responses_create_routes_to_handler(self):
        t = NatsTransport(url="nats://fake:4222")
        dispatcher = _FakeDispatcher()
        nc = _FakeNats()
        msg = _FakeMsg()
        body = {
            "jsonrpc": "2.0",
            "id": "req-3",
            "method": "responses/create",
            "params": {"request": {"model": "m"}},
            "metadata": {"trace": "t1"},
        }
        await t._handle_inbound(body, msg, dispatcher, nc)
        assert len(dispatcher.responses_create_calls) == 1
        req, meta = dispatcher.responses_create_calls[0]
        assert req == {"model": "m"}
        assert meta == {"trace": "t1"}
        reply = json.loads(nc.published[0][1])
        assert reply["id"] == "req-3"
        assert reply["result"]["id"] == "resp-1"

    @pytest.mark.asyncio
    async def test_responses_create_stream_publishes_each_chunk(self):
        t = NatsTransport(url="nats://fake:4222")
        dispatcher = _FakeDispatcher()
        dispatcher.create_stream_chunks = [
            {"type": "response.output_text.delta", "delta": "hel"},
            {"type": "response.output_text.delta", "delta": "lo"},
            {"type": "response.completed"},
        ]
        nc = _FakeNats()
        msg = _FakeMsg()
        body = {
            "jsonrpc": "2.0",
            "id": "req-4",
            "method": "responses/createStream",
            "params": {"request": {"model": "m", "stream": True}},
            "metadata": {},
        }
        await t._handle_inbound(body, msg, dispatcher, nc)
        assert len(dispatcher.responses_create_stream_calls) == 1
        # Every chunk republished to the reply inbox.
        assert len(nc.published) == 3
        last = json.loads(nc.published[-1][1])
        assert last["type"] == "response.completed"

    @pytest.mark.asyncio
    async def test_responses_get_routes_to_handler(self):
        t = NatsTransport(url="nats://fake:4222")
        dispatcher = _FakeDispatcher()
        nc = _FakeNats()
        msg = _FakeMsg()
        body = {
            "jsonrpc": "2.0",
            "id": "req-5",
            "method": "responses/get",
            "params": {"response_id": "resp-xyz"},
        }
        await t._handle_inbound(body, msg, dispatcher, nc)
        assert dispatcher.responses_get_calls == ["resp-xyz"]
        reply = json.loads(nc.published[0][1])
        assert reply["result"] == {"id": "resp-xyz"}

    @pytest.mark.asyncio
    async def test_responses_get_missing_returns_null_result(self):
        t = NatsTransport(url="nats://fake:4222")
        dispatcher = _FakeDispatcher()
        nc = _FakeNats()
        msg = _FakeMsg()
        body = {
            "jsonrpc": "2.0",
            "id": "req-6",
            "method": "responses/get",
            "params": {"response_id": "missing"},
        }
        await t._handle_inbound(body, msg, dispatcher, nc)
        reply = json.loads(nc.published[0][1])
        assert reply["result"] is None

    @pytest.mark.asyncio
    async def test_unknown_method_returns_jsonrpc_error(self):
        t = NatsTransport(url="nats://fake:4222")
        dispatcher = _FakeDispatcher()
        nc = _FakeNats()
        msg = _FakeMsg()
        body = {"jsonrpc": "2.0", "id": "req-7", "method": "bogus/method"}
        await t._handle_inbound(body, msg, dispatcher, nc)
        assert dispatcher.a2a_calls == []
        assert dispatcher.responses_create_calls == []
        err = json.loads(nc.published[0][1])
        assert err["error"]["code"] == -32601
        assert "Unknown method" in err["error"]["message"]

    @pytest.mark.asyncio
    async def test_exception_in_dispatcher_produces_internal_error(self):
        t = NatsTransport(url="nats://fake:4222")

        class _Boom:
            async def dispatch_a2a(self, message, metadata):
                raise RuntimeError("kaboom")

            def dispatch_a2a_stream(self, message, metadata):
                async def _g():
                    if False:
                        yield

                return _g()

            async def dispatch_responses_create(self, request, metadata):
                return {}

            def dispatch_responses_create_stream(self, request, metadata):
                async def _g():
                    if False:
                        yield

                return _g()

            async def dispatch_responses_get(self, response_id):
                return None

        dispatcher = _Boom()
        nc = _FakeNats()
        msg = _FakeMsg()
        body = {
            "jsonrpc": "2.0",
            "id": "req-8",
            "method": "tasks/send",
            "params": {
                "id": "cid-8",
                "message": {"role": "user", "parts": [{"text": "hi"}]},
            },
        }
        await t._handle_inbound(body, msg, dispatcher, nc)
        err = json.loads(nc.published[0][1])
        assert err["error"]["code"] == -32603
        assert "kaboom" in err["error"]["message"]


# ---------------------------------------------------------------------------
# Docker integration tests — opt-in with -m docker
# ---------------------------------------------------------------------------


@pytest.mark.docker
class TestNatsTransport(TransportContract):
    """Runs the shared transport contract against a live NATS container."""

    @pytest.fixture(scope="class")
    def nats_container(self):
        # Spin up nats:2.10-alpine on a random high port
        import time

        import docker

        client = docker.from_env()
        with contextlib.suppress(Exception):
            client.images.pull("nats:2.10-alpine")
        c = client.containers.run(
            "nats:2.10-alpine",
            command=["-js"],  # enable JetStream
            detach=True,
            remove=True,
            ports={"4222/tcp": None},  # random host port
        )
        try:
            c.reload()
            port = c.ports["4222/tcp"][0]["HostPort"]
            # Wait for NATS to be ready
            time.sleep(1)
            yield f"nats://127.0.0.1:{port}"
        finally:
            with contextlib.suppress(Exception):
                c.stop(timeout=3)

    @pytest.fixture
    def serve_agent(self, nats_container):
        @asynccontextmanager
        async def _ctx(canonical_name: str, handler):
            client = NatsTransport(url=nats_container, subject_prefix="vystak-test")
            serve_task = asyncio.create_task(client.serve(canonical_name, handler))
            # Give the subscription a moment to register
            await asyncio.sleep(0.1)
            try:
                yield client
            finally:
                serve_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await serve_task
                if client._nc and not client._nc.is_closed:
                    await client._nc.close()

        return _ctx
