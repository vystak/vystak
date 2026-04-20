"""Tests for HttpTransport."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import pytest
import uvicorn
from fastapi import FastAPI, Request
from sse_starlette.sse import EventSourceResponse
from vystak.transport import (
    A2AMessage,
    AgentRef,
)
from vystak.transport.contract import TransportContract
from vystak_transport_http import HttpTransport


def _build_app(handler) -> FastAPI:
    """Minimal FastAPI app exposing /a2a for the test agent.

    ``handler`` is a ``ServerDispatcherProtocol`` (per Plan C), so A2A calls
    route via ``dispatch_a2a`` / ``dispatch_a2a_stream``.
    """
    app = FastAPI()

    @app.post("/a2a")
    async def a2a_endpoint(request: Request):
        body = await request.json()
        params = body.get("params", {})
        metadata = params.get("metadata", {})
        msg_params = params.get("message", {})
        message = A2AMessage(
            role=msg_params.get("role", "user"),
            parts=msg_params.get("parts", []),
            correlation_id=params.get("id") or metadata.get("correlation_id", ""),
            metadata=metadata,
        )

        if body.get("method") == "tasks/sendSubscribe":
            async def gen():
                async for ev in handler.dispatch_a2a_stream(message, metadata):
                    yield {"data": ev.model_dump_json()}

            return EventSourceResponse(gen())

        result = await handler.dispatch_a2a(message, metadata)
        return {
            "jsonrpc": "2.0",
            "id": body.get("id"),
            "result": {
                "status": {
                    "message": {
                        "parts": [{"text": result.text}]
                    }
                },
                "correlation_id": result.correlation_id,
            },
        }

    return app


@asynccontextmanager
async def _serve(app: FastAPI, port: int):
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    # Wait for the server to bind.
    for _ in range(100):
        if server.started:
            break
        await asyncio.sleep(0.01)
    try:
        yield
    finally:
        server.should_exit = True
        await task


class TestHttpTransport(TransportContract):
    """Runs the shared transport contract against HttpTransport."""

    @pytest.fixture
    def serve_agent(self, unused_tcp_port):
        @asynccontextmanager
        async def _ctx(canonical_name: str, handler):
            app = _build_app(handler)
            async with _serve(app, unused_tcp_port):
                client = HttpTransport(
                    routes={
                        canonical_name: f"http://127.0.0.1:{unused_tcp_port}/a2a"
                    }
                )
                yield client
        return _ctx


class TestHttpTransportBasics:
    def test_type(self):
        t = HttpTransport(routes={})
        assert t.type == "http"
        assert t.supports_streaming is True

    def test_resolve_address_lookup(self):
        t = HttpTransport(routes={"x.agents.default": "http://example:8000/a2a"})
        assert t.resolve_address("x.agents.default") == "http://example:8000/a2a"

    def test_resolve_address_unknown(self):
        t = HttpTransport(routes={})
        with pytest.raises(KeyError):
            t.resolve_address("unknown.agents.default")

    @pytest.mark.asyncio
    async def test_serve_is_noop(self):
        t = HttpTransport(routes={})
        # serve() returns immediately; the actual /a2a route is served by
        # the generated agent's FastAPI app.
        await t.serve("x.agents.default", handler=None)

    @pytest.mark.asyncio
    async def test_create_response_posts_to_agent(self, unused_tcp_port):
        """create_response POSTs the request body to the agent's /v1/responses."""
        from fastapi import FastAPI
        from fastapi.responses import JSONResponse

        received: dict = {}
        app = FastAPI()

        @app.post("/v1/responses")
        async def handler(request: Request):  # Request imported at module level
            received["body"] = await request.json()
            return JSONResponse({
                "id": "resp-1",
                "object": "response",
                "created_at": 1,
                "model": "vystak/test",
                "output": [{"type": "message", "content": "hi"}],
                "status": "completed",
            })

        async with _serve(app, unused_tcp_port):
            routes = {"test.agents.default": f"http://127.0.0.1:{unused_tcp_port}/a2a"}
            t = HttpTransport(routes=routes)
            ref = AgentRef(canonical_name="test.agents.default")
            result = await t.create_response(
                ref, {"model": "vystak/test", "input": "hello"}, {}, timeout=5
            )
            assert result["id"] == "resp-1"
            assert received["body"]["input"] == "hello"

    @pytest.mark.asyncio
    async def test_get_response_returns_none_on_404(self, unused_tcp_port):
        from fastapi import FastAPI
        from fastapi.responses import JSONResponse

        app = FastAPI()

        @app.get("/v1/responses/{response_id}")
        async def handler(response_id: str):
            if response_id == "missing":
                return JSONResponse({"error": "not found"}, status_code=404)
            return JSONResponse({"id": response_id, "object": "response"})

        async with _serve(app, unused_tcp_port):
            routes = {"test.agents.default": f"http://127.0.0.1:{unused_tcp_port}/a2a"}
            t = HttpTransport(routes=routes)
            ref = AgentRef(canonical_name="test.agents.default")
            assert await t.get_response(ref, "missing", timeout=5) is None
            got = await t.get_response(ref, "resp-1", timeout=5)
            assert got["id"] == "resp-1"

    def test_agent_base_url_strips_a2a(self):
        routes = {"x.agents.default": "http://vystak-x:8000/a2a"}
        t = HttpTransport(routes=routes)
        ref = AgentRef(canonical_name="x.agents.default")
        assert t._agent_base_url(ref) == "http://vystak-x:8000"
