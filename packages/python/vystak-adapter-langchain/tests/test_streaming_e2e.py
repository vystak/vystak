"""End-to-end SSE round-trip: emitted server source <-> HttpTransport.stream_task.

Catches wire-format bugs invisible to string-presence assertions: malformed
JSON, JSON-RPC envelope vs A2AEvent shape mismatches, missing event types in
the SSE generator, etc.
"""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager

import pytest
import uvicorn
from fastapi import FastAPI, Request
from sse_starlette.sse import EventSourceResponse
from vystak.transport import (
    A2AEvent,
    A2AHandler,
    A2AMessage,
)


def _build_app(events: list[A2AEvent]) -> FastAPI:
    """Build a minimal FastAPI app with a /a2a route that streams the given
    event list through an A2AHandler. The SSE wire shape mirrors what the
    LangChain adapter's emitted server.py uses for tool_call/tool_result/final
    (bare A2AEvent JSON via model_dump_json)."""
    app = FastAPI()

    async def _one_shot(message: A2AMessage, metadata: dict) -> str:
        return ""  # not exercised in this test

    async def _streaming(message: A2AMessage, metadata: dict):
        for ev in events:
            yield ev

    handler = A2AHandler(one_shot=_one_shot, streaming=_streaming)

    @app.post("/a2a")
    async def a2a(request: Request):
        body = await request.json()
        params = body.get("params", {})
        msg = A2AMessage(
            role=params.get("message", {}).get("role", "user"),
            parts=params.get("message", {}).get("parts", []),
            correlation_id=params.get("id"),
            metadata=params.get("metadata", {}),
        )
        if body.get("method") == "tasks/sendSubscribe":

            async def gen():
                async for ev in handler.dispatch_stream(msg, params.get("metadata", {})):
                    if ev.type in ("tool_call", "tool_result", "final"):
                        yield {"data": ev.model_dump_json()}
                    elif ev.type == "token":
                        yield {
                            "data": json.dumps(
                                {
                                    "jsonrpc": "2.0",
                                    "id": body.get("id"),
                                    "result": {
                                        "artifact": {"parts": [{"text": ev.text or ""}]}
                                    },
                                }
                            )
                        }

            return EventSourceResponse(gen())
        return {"jsonrpc": "2.0", "id": body.get("id"), "result": {}}

    return app


@asynccontextmanager
async def _serve(app: FastAPI, port: int):
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    for _ in range(100):
        if server.started:
            break
        await asyncio.sleep(0.01)
    try:
        yield
    finally:
        server.should_exit = True
        await task


@pytest.mark.asyncio
async def test_tool_call_events_round_trip(unused_tcp_port):
    from vystak.transport import AgentRef
    from vystak_transport_http import HttpTransport

    events = [
        A2AEvent(type="tool_call", data={"tool_name": "ask_weather", "started_at": 1.0}),
        A2AEvent(type="tool_result", data={"tool_name": "ask_weather", "duration_ms": 2100}),
        A2AEvent(type="final", text="It's sunny in Lisbon.", final=True),
    ]
    app = _build_app(events)
    async with _serve(app, unused_tcp_port):
        transport = HttpTransport(
            routes={"probe.agents.default": f"http://127.0.0.1:{unused_tcp_port}/a2a"}
        )
        ref = AgentRef(canonical_name="probe.agents.default")
        msg = A2AMessage(role="user", parts=[{"text": "weather?"}], metadata={})

        received = []
        async for ev in transport.stream_task(ref, msg, {}, timeout=5):
            received.append(ev)

        assert len(received) == 3
        assert received[0].type == "tool_call"
        assert (received[0].data or {}).get("tool_name") == "ask_weather"
        assert received[1].type == "tool_result"
        assert (received[1].data or {}).get("duration_ms") == 2100
        assert received[2].type == "final"
        assert received[2].text == "It's sunny in Lisbon."


@pytest.mark.asyncio
async def test_token_envelope_does_not_break_stream(unused_tcp_port):
    """Mixed wire frames: legacy JSON-RPC envelopes for tokens + bare
    A2AEvent frames for tool_call/tool_result/final must coexist on the
    SSE stream. The transport may skip envelope frames silently (since
    they don't validate as A2AEvent) but must still surface every
    bare-A2AEvent frame to the consumer.
    """
    from vystak.transport import AgentRef
    from vystak_transport_http import HttpTransport

    events = [
        A2AEvent(type="token", text="thinking..."),  # -> JSON-RPC envelope on wire
        A2AEvent(type="tool_call", data={"tool_name": "ask_weather"}),
        A2AEvent(type="final", text="done", final=True),
    ]
    app = _build_app(events)
    async with _serve(app, unused_tcp_port):
        transport = HttpTransport(
            routes={"probe.agents.default": f"http://127.0.0.1:{unused_tcp_port}/a2a"}
        )
        ref = AgentRef(canonical_name="probe.agents.default")
        msg = A2AMessage(role="user", parts=[{"text": "x"}], metadata={})

        types_seen = []
        async for ev in transport.stream_task(ref, msg, {}, timeout=5):
            types_seen.append(ev.type)

        # The token envelope frame may or may not surface depending on
        # whether transport.py skips ValidationError. The two bare frames
        # MUST surface in order.
        assert "tool_call" in types_seen
        assert "final" in types_seen
        assert types_seen.index("tool_call") < types_seen.index("final")
