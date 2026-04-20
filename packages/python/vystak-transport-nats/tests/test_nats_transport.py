"""Tests for NatsTransport."""

from __future__ import annotations

import asyncio
import contextlib
import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from vystak.transport import A2AHandler, A2AMessage
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
        async def _ctx(canonical_name: str, handler: A2AHandler):
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
