import json

import pytest
from _vystak.runtime.turn_journal import InMemoryTurnJournal

PAYLOAD = {"kind": "tool_approval", "tool": "dangerous",
           "args": {"x": 1}, "skill": "ops"}


@pytest.mark.asyncio
async def test_park_publishes_approval_requested_event(bridge_factory):
    journal = InMemoryTurnJournal()
    bridge = bridge_factory(
        journal=journal,
        sse_events=[{"type": "response.created", "response": {"id": "resp_1"}}],
        sse_done=False,
        checkpoint_state={"checkpoint_id": "ck", "interrupted": True,
                          "interrupts": [PAYLOAD]},
    )
    await journal.create("t1", "s.t1", {})
    await bridge._run_detached({"input": "hi"}, "s.t1", "t1")

    assert (await journal.get("t1")).status == "parked"
    events = [json.loads(p)["event"] for p in bridge.published_payloads]
    approvals = [e for e in events if e["type"] == "vystak.approval.requested"]
    assert approvals == [{"type": "vystak.approval.requested", "payload": PAYLOAD}]
    # non-terminal: no response.failed / response.completed after it
    assert "response.failed" not in [e["type"] for e in events]


@pytest.mark.asyncio
async def test_turn_status_carries_interrupt_when_parked(bridge_factory):
    journal = InMemoryTurnJournal()
    await journal.create("t1", "s.t1", {})
    await journal.set_thread_id("t1", "resp_1")
    await journal.set_status("t1", "parked")
    bridge = bridge_factory(
        journal=journal,
        checkpoint_state={"checkpoint_id": "ck", "interrupted": True,
                          "interrupts": [PAYLOAD]},
    )
    await bridge._handle_envelope_for_test(
        {"id": 1, "method": "responses/turnStatus", "params": {"turn_id": "t1"}},
        "reply.inbox",
    )
    result = json.loads(bridge.replies[-1])["result"]
    assert result["status"] == "parked"
    assert result["interrupt"] == PAYLOAD


@pytest.mark.asyncio
async def test_turn_status_interrupt_null_when_running(bridge_factory):
    journal = InMemoryTurnJournal()
    await journal.create("t1", "s.t1", {})
    bridge = bridge_factory(journal=journal)
    await bridge._handle_envelope_for_test(
        {"id": 1, "method": "responses/turnStatus", "params": {"turn_id": "t1"}},
        "reply.inbox",
    )
    result = json.loads(bridge.replies[-1])["result"]
    assert result["status"] == "running"
    assert result["interrupt"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["running", "done", "failed"])
async def test_resume_detached_rejects_non_parked(bridge_factory, status):
    journal = InMemoryTurnJournal()
    await journal.create("t1", "s.t1", {})
    if status != "running":
        await journal.set_status("t1", status)
    bridge = bridge_factory(journal=journal)
    await bridge._handle_envelope_for_test(
        {"id": 1, "method": "responses/resumeDetached",
         "params": {"turn_id": "t1", "resume": {"approved": True}}},
        "reply.inbox",
    )
    reply = json.loads(bridge.replies[-1])
    assert reply["error"]["code"] == -32602
    assert "not parked" in reply["error"]["message"]
    assert (await journal.get("t1")).status == status  # unchanged
