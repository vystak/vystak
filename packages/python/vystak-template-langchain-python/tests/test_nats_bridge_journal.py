import json

import pytest
from _vystak.runtime.turn_journal import InMemoryTurnJournal


@pytest.mark.asyncio
async def test_row_created_before_ack(bridge_factory):
    journal = InMemoryTurnJournal()
    bridge = bridge_factory(journal=journal)
    await bridge._handle_responses_create_detached(
        {"id": 1, "params": {"request": {"input": "hi"},
                             "turn_id": "t1", "stream_subject": "s.t1"}},
        "reply.inbox",
    )
    rec = await journal.get("t1")
    assert rec is not None and rec.status == "running"


@pytest.mark.asyncio
async def test_thread_id_captured_from_response_created(bridge_factory):
    journal = InMemoryTurnJournal()
    bridge = bridge_factory(
        journal=journal,
        sse_events=[{"type": "response.created", "response": {"id": "resp_9"}}],
    )
    await journal.create("t1", "s.t1", {})
    await bridge._run_detached({"input": "hi"}, "s.t1", "t1")
    assert (await journal.get("t1")).thread_id == "resp_9"


@pytest.mark.asyncio
async def test_checkpoint_marker_records_boundary_and_is_not_published(bridge_factory):
    journal = InMemoryTurnJournal()
    bridge = bridge_factory(
        journal=journal,
        sse_events=[
            {"type": "response.output_text.delta", "delta": "a"},
            {"type": "vystak.checkpoint", "checkpoint_id": "ck-1"},
            {"type": "response.output_text.delta", "delta": "b"},
        ],
    )
    await journal.create("t1", "s.t1", {})
    await bridge._run_detached({"input": "hi"}, "s.t1", "t1")

    published = [json.loads(p)["event"]["type"] for p in bridge.published_payloads]
    assert "vystak.checkpoint" not in published
    # one delta published (seq 0) before the marker
    assert await journal.seq_for_checkpoint("t1", "ck-1") == 0


@pytest.mark.asyncio
async def test_terminal_event_marks_done(bridge_factory):
    journal = InMemoryTurnJournal()
    bridge = bridge_factory(
        journal=journal,
        sse_events=[{"type": "response.completed", "response": {"id": "resp_1"}}],
    )
    await journal.create("t1", "s.t1", {})
    await bridge._run_detached({"input": "hi"}, "s.t1", "t1")
    assert (await journal.get("t1")).status == "done"


@pytest.mark.asyncio
async def test_failure_marks_failed(bridge_factory):
    journal = InMemoryTurnJournal()
    bridge = bridge_factory(
        journal=journal,
        sse_events=[{"type": "response.failed", "response": {"error": {"message": "boom"}}}],
    )
    await journal.create("t1", "s.t1", {})
    await bridge._run_detached({"input": "hi"}, "s.t1", "t1")
    assert (await journal.get("t1")).status == "failed"
