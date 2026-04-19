"""Tests for HttpTransport."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import pytest
import uvicorn
from fastapi import FastAPI, Request
from sse_starlette.sse import EventSourceResponse
from vystak.transport import (
    A2AHandler,
    A2AMessage,
)
from vystak.transport.contract import TransportContract
from vystak_transport_http import HttpTransport


def _build_app(handler: A2AHandler) -> FastAPI:
    """Minimal FastAPI app exposing /a2a for the test agent."""
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
                async for ev in handler.dispatch_stream(message, metadata):
                    yield {"data": ev.model_dump_json()}

            return EventSourceResponse(gen())

        result = await handler.dispatch(message, metadata)
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
        async def _ctx(canonical_name: str, handler: A2AHandler):
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
