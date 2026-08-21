"""Real gated-tool end-to-end integration test.

Proves `wrap_tools_with_approval` (Task 2) + the bridge's park detection and
`vystak.approval.requested` publish (Task 4) actually compose: a REAL
`StateGraph` + `MemorySaver`, behind a real ASGI transport, whose only node
invokes a tool wrapped by `wrap_tools_with_approval` — driven end-to-end
through the bridge's `responses/createDetached` -> parked ->
`responses/resumeDetached` -> done dispatch. Modeled directly on
`test_nats_bridge_rpcs.py::test_resume_detached_drives_a_real_parked_graph_to_completion`;
the only real change is swapping the hand-written `interrupt()` node for a
graph node that calls a wrapped tool produced by Task 2's gate, with a
recording original tool standing in for a real dangerous action.
"""

import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
from _vystak.runtime import nats_bridge as nats_bridge_module
from _vystak.runtime.approvals import wrap_tools_with_approval
from _vystak.runtime.nats_bridge import NatsHttpBridge
from _vystak.runtime.turn_journal import InMemoryTurnJournal


def _build_gated_app(calls: list):
    """A minimal FastAPI app exposing the three routes the bridge needs
    (`/v1/responses`, `/v1/_vystak/resume`, `/v1/_vystak/checkpoint`), wired
    to a real LangGraph graph whose sole node invokes a REAL wrapped tool
    from `wrap_tools_with_approval` — the gate itself calls `interrupt()`
    internally (approvals.py), so the run parks before the tool executes,
    exactly as it would in the real `app_factory.py` checkpoint route."""
    from typing import Any, TypedDict

    from _vystak.runtime.openai.responses import ResponsesHandler
    from fastapi import FastAPI, Request
    from fastapi.responses import StreamingResponse
    from langchain_core.messages import AIMessage
    from langchain_core.tools import tool
    from langgraph.checkpoint.memory import MemorySaver
    from langgraph.graph import END, START, StateGraph

    class _State(TypedDict):
        messages: list

    @tool
    async def restart_service(name: str) -> str:
        """Restart a service."""
        calls.append(name)
        return f"restarted {name}"

    (gated,) = wrap_tools_with_approval([restart_service], {"restart_service": "ops"})

    async def _tool_node(state: _State) -> dict[str, Any]:
        result = await gated.ainvoke({"name": "svc"})
        return {"messages": [*state["messages"], AIMessage(content=result)]}

    builder = StateGraph(_State)
    builder.add_node("call_tool", _tool_node)
    builder.add_edge(START, "call_tool")
    builder.add_edge("call_tool", END)
    graph = builder.compile(checkpointer=MemorySaver())

    agent = SimpleNamespace(name="approver")
    handler = ResponsesHandler(agent=agent, graph=graph)

    app = FastAPI()

    @app.post("/v1/responses")
    async def create_response(request: Request):
        body = await request.json()
        result = await handler.create(body)
        if hasattr(result, "__aiter__"):
            return StreamingResponse(result, media_type="text/event-stream")
        return result

    @app.post("/v1/_vystak/resume")
    async def resume(request: Request):
        payload = await request.json()
        return StreamingResponse(
            handler.resume_stream(payload["thread_id"], payload.get("resume")),
            media_type="text/event-stream",
        )

    @app.get("/v1/_vystak/checkpoint")
    async def checkpoint(thread_id: str):
        # Mirrors app_factory.py's real checkpoint route exactly: surfaces
        # `.next` (interrupted) and `.tasks[*].interrupts[*].value` (the
        # tool_approval payload from approvals.py).
        config = {"configurable": {"thread_id": thread_id}}
        snapshot = await graph.aget_state(config)
        checkpoint_id = None
        interrupted = False
        interrupts: list = []
        if snapshot is not None:
            if snapshot.config:
                checkpoint_id = snapshot.config.get("configurable", {}).get("checkpoint_id")
            interrupted = bool(snapshot.next)
            for task in getattr(snapshot, "tasks", None) or ():
                for intr in getattr(task, "interrupts", None) or ():
                    interrupts.append(getattr(intr, "value", None))
        return {
            "checkpoint_id": checkpoint_id,
            "interrupted": interrupted,
            "interrupts": interrupts,
        }

    return app, graph


class _FakeJetStream:
    def __init__(self) -> None:
        self.published_payloads: list[bytes] = []

    async def add_stream(self, cfg):  # noqa: ANN001
        return None

    async def update_stream(self, cfg):  # noqa: ANN001
        return None

    async def publish(self, subject, payload):  # noqa: ANN001
        self.published_payloads.append(payload)


class _FakeNatsClient:
    def __init__(self, js) -> None:  # noqa: ANN001
        self.published: list[tuple[str, bytes]] = []
        self._js = js

    async def publish(self, subject, payload):  # noqa: ANN001
        self.published.append((subject, payload))

    def jetstream(self):
        return self._js


def _build_bridge(app, journal):
    bridge = NatsHttpBridge(
        nats_url="nats://ignored:4222",
        subject="vystak.default.agents.approver.tasks",
        queue_group="agents.approver",
        local_url="http://localhost/a2a",
        local_base="http://localhost",
        journal=journal,
    )
    js = _FakeJetStream()
    bridge._nc = _FakeNatsClient(js)
    bridge._http = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://localhost"
    )
    return bridge, js


async def _drive_to_parked(bridge, journal, turn_id="t1"):
    await bridge._handle_responses_create_detached(
        {
            "id": 1,
            "params": {
                "request": {"input": "hi"},
                "turn_id": turn_id,
                "stream_subject": f"s.{turn_id}",
            },
        },
        "reply.inbox",
    )
    await asyncio.gather(*list(bridge._inflight))

    rec = await journal.get(turn_id)
    assert rec is not None
    assert rec.status == "parked"
    assert rec.thread_id is not None
    return rec


@pytest.mark.asyncio
async def test_real_gated_tool_parks_and_resumes_on_approval(monkeypatch):
    """approve: journal parks with the real tool_approval payload, resume
    executes the ORIGINAL tool exactly once, and the turn completes."""

    async def _noop_ensure_turn_stream(js, base):  # noqa: ANN001
        return None

    def _noop_stream_base_of_turn_subject(stream_subject):  # noqa: ANN001
        return stream_subject

    monkeypatch.setattr(nats_bridge_module, "_ensure_turn_stream", _noop_ensure_turn_stream)
    monkeypatch.setattr(
        nats_bridge_module, "_stream_base_of_turn_subject", _noop_stream_base_of_turn_subject
    )

    calls: list[str] = []
    app, _graph = _build_gated_app(calls)
    journal = InMemoryTurnJournal()
    bridge, js = _build_bridge(app, journal)

    await _drive_to_parked(bridge, journal, "t1")

    events = [json.loads(p)["event"] for p in js.published_payloads]
    approval_events = [e for e in events if e["type"] == "vystak.approval.requested"]
    assert approval_events, "expected vystak.approval.requested to be published on park"
    payload = approval_events[-1]["payload"]
    assert payload["tool"] == "restart_service"
    assert payload["args"] == {"name": "svc"}

    # Tool must not have executed yet — it's parked BEFORE the real call.
    assert calls == []

    await bridge._handle_resume_detached(
        {
            "id": 2,
            "params": {
                "turn_id": "t1",
                "resume": {"approved": True, "decided_by": "qa@example.com", "note": None},
            },
        },
        "reply.inbox",
    )
    await asyncio.gather(*list(bridge._inflight))

    assert calls == ["svc"]

    final = await journal.get("t1")
    assert final is not None
    assert final.status == "done"

    types = [json.loads(p)["event"]["type"] for p in js.published_payloads]
    assert "response.completed" in types

    await bridge._http.aclose()


@pytest.mark.asyncio
async def test_real_gated_tool_denied_never_executes_and_completes(monkeypatch):
    """deny: the original tool never runs; the turn still completes (not
    fails) and the graph's final message carries the denial reason."""

    async def _noop_ensure_turn_stream(js, base):  # noqa: ANN001
        return None

    def _noop_stream_base_of_turn_subject(stream_subject):  # noqa: ANN001
        return stream_subject

    monkeypatch.setattr(nats_bridge_module, "_ensure_turn_stream", _noop_ensure_turn_stream)
    monkeypatch.setattr(
        nats_bridge_module, "_stream_base_of_turn_subject", _noop_stream_base_of_turn_subject
    )

    calls: list[str] = []
    app, graph = _build_gated_app(calls)
    journal = InMemoryTurnJournal()
    bridge, js = _build_bridge(app, journal)

    rec = await _drive_to_parked(bridge, journal, "t1")

    await bridge._handle_resume_detached(
        {
            "id": 2,
            "params": {
                "turn_id": "t1",
                "resume": {
                    "approved": False,
                    "decided_by": "qa@example.com",
                    "note": "nope",
                },
            },
        },
        "reply.inbox",
    )
    await asyncio.gather(*list(bridge._inflight))

    assert calls == []

    final = await journal.get("t1")
    assert final is not None
    assert final.status == "done"

    types = [json.loads(p)["event"]["type"] for p in js.published_payloads]
    assert "response.failed" not in types

    # The final text isn't observable off the SSE stream here: the node
    # returns the denial string directly (no chat-model token streaming),
    # so `response.completed`'s output text — built from streamed deltas —
    # is empty. Confirm the denial reached the graph's own state instead,
    # per the brief's explicit allowance ("published deltas or graph state
    # message").
    config = {"configurable": {"thread_id": rec.thread_id}}
    snapshot = await graph.aget_state(config)
    last_message = snapshot.values["messages"][-1]
    content = last_message.content if hasattr(last_message, "content") else last_message["content"]
    assert "Denied by qa@example.com: nope" in content

    # It also reaches the wire: `astream_events` fires `on_tool_end` for the
    # gated tool's own invocation (the gate itself is a real tool call), so
    # `_stream_iterator` publishes a `function_call_output` item carrying the
    # denial string even though `response.completed`'s own output text is
    # empty (see the comment above — that text only ever comes from
    # `on_chat_model_stream` deltas, and this graph has no chat model).
    blob = b"".join(js.published_payloads).decode()
    assert "Denied by qa@example.com: nope" in blob

    await bridge._http.aclose()
