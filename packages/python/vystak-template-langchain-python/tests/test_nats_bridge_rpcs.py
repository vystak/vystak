import asyncio
import json
from types import SimpleNamespace

import pytest
from _vystak.runtime.turn_journal import InMemoryTurnJournal


def _reply(bridge):
    return json.loads(bridge.replies[-1])["result"]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["running", "parked", "done", "failed"])
async def test_turn_status_reports_journal_status(bridge_factory, status):
    journal = InMemoryTurnJournal()
    await journal.create("t1", "s.t1", {})
    if status != "running":
        await journal.set_status("t1", status)
    bridge = bridge_factory(journal=journal)

    await bridge._handle_envelope_for_test(
        {"id": 1, "method": "responses/turnStatus", "params": {"turn_id": "t1"}},
        "reply.inbox",
    )
    assert _reply(bridge)["status"] == status


@pytest.mark.asyncio
async def test_turn_status_unknown_for_missing_row(bridge_factory):
    bridge = bridge_factory(journal=InMemoryTurnJournal())
    await bridge._handle_envelope_for_test(
        {"id": 1, "method": "responses/turnStatus", "params": {"turn_id": "ghost"}},
        "reply.inbox",
    )
    assert _reply(bridge)["status"] == "unknown"


@pytest.mark.asyncio
async def test_resume_detached_flips_parked_to_running(bridge_factory):
    journal = InMemoryTurnJournal()
    await journal.create("t1", "s.t1", {})
    await journal.set_status("t1", "parked")
    await journal.set_thread_id("t1", "resp_1")
    bridge = bridge_factory(journal=journal, resume_checkpoint_id="ck-1")

    await bridge._handle_envelope_for_test(
        {"id": 1, "method": "responses/resumeDetached",
         "params": {"turn_id": "t1", "resume": {"approved": True}}},
        "reply.inbox",
    )
    assert (await journal.get("t1")).status == "running"


@pytest.mark.asyncio
async def test_resume_detached_publishes_no_rewind(bridge_factory):
    """Nothing was lost on a park, so there is nothing to discard."""
    journal = InMemoryTurnJournal()
    await journal.create("t1", "s.t1", {})
    await journal.set_status("t1", "parked")
    await journal.set_thread_id("t1", "resp_1")
    bridge = bridge_factory(journal=journal, resume_checkpoint_id="ck-1")

    await bridge._handle_envelope_for_test(
        {"id": 1, "method": "responses/resumeDetached", "params": {"turn_id": "t1"}},
        "reply.inbox",
    )
    await asyncio.gather(*list(bridge._inflight))
    types = [json.loads(p)["event"]["type"] for p in bridge.published_payloads]
    assert "vystak.turn.rewind" not in types


@pytest.mark.asyncio
async def test_resume_detached_unknown_turn_id_errors(bridge_factory):
    bridge = bridge_factory(journal=InMemoryTurnJournal())
    await bridge._handle_envelope_for_test(
        {"id": 1, "method": "responses/resumeDetached", "params": {"turn_id": "ghost"}},
        "reply.inbox",
    )
    reply = json.loads(bridge.replies[-1])
    assert "result" not in reply
    assert reply["error"]["code"] == -32602


@pytest.mark.asyncio
async def test_resume_detached_posts_resume_value(bridge_factory):
    journal = InMemoryTurnJournal()
    await journal.create("t1", "s.t1", {})
    await journal.set_status("t1", "parked")
    await journal.set_thread_id("t1", "resp_1")
    bridge = bridge_factory(journal=journal, resume_checkpoint_id="ck-1")

    await bridge._handle_envelope_for_test(
        {"id": 1, "method": "responses/resumeDetached",
         "params": {"turn_id": "t1", "resume": {"approved": True}}},
        "reply.inbox",
    )
    await asyncio.gather(*list(bridge._inflight))
    resume_calls = [r for r in bridge.requests if r["path"] == "/v1/_vystak/resume"]
    assert resume_calls
    assert resume_calls[-1]["json"] == {"thread_id": "resp_1", "resume": {"approved": True}}


# ---------------------------------------------------------------------------
# Park detection: a truncated stream (no [DONE], no terminal event) is
# resolved against the agent's own checkpoint state.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_truncated_stream_marks_parked_when_interrupted(bridge_factory):
    journal = InMemoryTurnJournal()
    await journal.create("t1", "s.t1", {})
    bridge = bridge_factory(
        journal=journal,
        sse_events=[{"type": "response.created", "response": {"id": "resp_1"}}],
        sse_done=False,
        checkpoint_interrupted=True,
    )
    await bridge._run_detached({"input": "hi"}, "s.t1", "t1")

    assert (await journal.get("t1")).status == "parked"
    types = [json.loads(p)["event"]["type"] for p in bridge.published_payloads]
    assert "response.failed" not in types


@pytest.mark.asyncio
async def test_truncated_stream_marks_failed_when_not_interrupted(bridge_factory):
    journal = InMemoryTurnJournal()
    await journal.create("t1", "s.t1", {})
    bridge = bridge_factory(
        journal=journal,
        sse_events=[{"type": "response.created", "response": {"id": "resp_1"}}],
        sse_done=False,
        checkpoint_interrupted=False,
    )
    await bridge._run_detached({"input": "hi"}, "s.t1", "t1")

    assert (await journal.get("t1")).status == "failed"
    types = [json.loads(p)["event"]["type"] for p in bridge.published_payloads]
    assert "response.failed" in types


@pytest.mark.asyncio
async def test_truncated_stream_leaves_running_when_checkpoint_lookup_fails(bridge_factory):
    """A transient/infra failure asking the agent about its own checkpoint
    state ('couldn't ask') must not be conflated with 'asked and confirmed
    not interrupted' — the row must stay re-drive-eligible, not be stamped
    `failed` (which would remove it from `redrive_unfinished()`'s sweep for
    good)."""
    journal = InMemoryTurnJournal()
    await journal.create("t1", "s.t1", {})
    await journal.set_thread_id("t1", "resp_1")
    bridge = bridge_factory(
        journal=journal,
        sse_events=[{"type": "response.created", "response": {"id": "resp_1"}}],
        sse_done=False,
        checkpoint_raises=True,
    )
    await bridge._run_detached({"input": "hi"}, "s.t1", "t1")

    assert (await journal.get("t1")).status == "running"
    types = [json.loads(p)["event"]["type"] for p in bridge.published_payloads]
    assert "response.failed" not in types


@pytest.mark.asyncio
async def test_truncated_stream_before_thread_id_leaves_running(bridge_factory):
    """Truncation before `response.created` ever arrived: there's no
    thread_id to ask the agent about at all — also a 'couldn't ask' window,
    not a confirmed failure."""
    journal = InMemoryTurnJournal()
    await journal.create("t1", "s.t1", {})
    bridge = bridge_factory(
        journal=journal,
        sse_events=[],
        sse_done=False,
    )
    await bridge._run_detached({"input": "hi"}, "s.t1", "t1")

    rec = await journal.get("t1")
    assert rec.thread_id is None
    assert rec.status == "running"
    types = [json.loads(p)["event"]["type"] for p in bridge.published_payloads]
    assert "response.failed" not in types


# ---------------------------------------------------------------------------
# Real interrupt() integration: a real LangGraph graph that calls
# interrupt() end-to-end through the bridge's createDetached/resumeDetached
# dispatch, proving `resumeDetached` actually drives a parked graph to
# completion via `Command(resume=...)` — not just against stubbed SSE.
# ---------------------------------------------------------------------------


def _build_interrupting_app():
    """A minimal FastAPI app exposing the three routes the bridge needs
    (`/v1/responses`, `/v1/_vystak/resume`, `/v1/_vystak/checkpoint`), wired
    to a real LangGraph graph whose sole node calls `interrupt()` — a
    test-only interrupting tool/node standing in for a real tool that
    pauses for human approval. Deliberately not `build_agent_app`: this
    only needs the Responses-API surface the bridge talks to, not the
    full A2A/skills/subagents stack."""
    from typing import Any, TypedDict

    from _vystak.runtime.openai.responses import ResponsesHandler
    from fastapi import FastAPI, Request
    from fastapi.responses import StreamingResponse
    from langgraph.checkpoint.memory import MemorySaver
    from langgraph.graph import END, START, StateGraph
    from langgraph.types import interrupt

    class _State(TypedDict):
        messages: list

    async def _approval_node(state: _State) -> dict[str, Any]:
        decision = interrupt({"question": "approve?"})
        return {"messages": state["messages"] + [{"role": "assistant",
                                                    "content": f"decision:{decision}"}]}

    builder = StateGraph(_State)
    builder.add_node("approve", _approval_node)
    builder.add_edge(START, "approve")
    builder.add_edge("approve", END)
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
        config = {"configurable": {"thread_id": thread_id}}
        snapshot = await graph.aget_state(config)
        checkpoint_id = None
        interrupted = False
        if snapshot is not None:
            if snapshot.config:
                checkpoint_id = snapshot.config.get("configurable", {}).get("checkpoint_id")
            interrupted = bool(snapshot.next)
        return {"checkpoint_id": checkpoint_id, "interrupted": interrupted}

    return app


@pytest.mark.asyncio
async def test_resume_detached_drives_a_real_parked_graph_to_completion(monkeypatch):
    """Real LangGraph + real `interrupt()` + real `Command(resume=...)`,
    end-to-end through the bridge's `responses/createDetached` and
    `responses/resumeDetached` dispatch. Closes the gap noted in the
    Task 4 review: resume semantics were previously only exercised via
    stubbed SSE fixtures, never a real interrupted graph."""
    import httpx
    from _vystak.runtime import nats_bridge as nats_bridge_module
    from _vystak.runtime.nats_bridge import NatsHttpBridge

    async def _noop_ensure_turn_stream(js, base):  # noqa: ANN001
        return None

    def _noop_stream_base_of_turn_subject(stream_subject):  # noqa: ANN001
        return stream_subject

    monkeypatch.setattr(nats_bridge_module, "_ensure_turn_stream", _noop_ensure_turn_stream)
    monkeypatch.setattr(
        nats_bridge_module, "_stream_base_of_turn_subject", _noop_stream_base_of_turn_subject
    )

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

    app = _build_interrupting_app()
    journal = InMemoryTurnJournal()
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

    # 1. Dispatch responses/createDetached — runs the graph to the interrupt.
    await bridge._handle_responses_create_detached(
        {"id": 1, "params": {"request": {"input": "hi"},
                             "turn_id": "t1", "stream_subject": "s.t1"}},
        "reply.inbox",
    )
    await asyncio.gather(*list(bridge._inflight))

    rec = await journal.get("t1")
    assert rec is not None
    assert rec.status == "parked"
    assert rec.thread_id is not None

    # 2. Dispatch responses/resumeDetached — drives the parked graph home.
    await bridge._handle_resume_detached(
        {"id": 2, "params": {"turn_id": "t1", "resume": "yes"}},
        "reply.inbox",
    )
    await asyncio.gather(*list(bridge._inflight))

    final = await journal.get("t1")
    assert final is not None
    assert final.status == "done"

    types = [json.loads(p)["event"]["type"] for p in js.published_payloads]
    assert "response.completed" in types
    assert "vystak.turn.rewind" not in types

    await bridge._http.aclose()
