import json

import pytest
from _vystak.runtime.nats_bridge import MAX_REDRIVE_ATTEMPTS
from _vystak.runtime.turn_journal import InMemoryTurnJournal


@pytest.mark.asyncio
async def test_rewind_targets_the_resumed_checkpoint(bridge_factory):
    journal = InMemoryTurnJournal()
    await journal.create("t1", "s.t1", {"input": "hi"})
    await journal.set_thread_id("t1", "resp_1")
    await journal.record_boundary("t1", "ck-1", 3)
    await journal.record_boundary("t1", "ck-2", 8)
    await journal.set_last_seq("t1", 12)

    # LangGraph will resume from ck-1, not the last boundary we observed.
    bridge = bridge_factory(journal=journal, resume_checkpoint_id="ck-1")
    await bridge.redrive_unfinished()

    first = json.loads(bridge.published_payloads[0])
    assert first["seq"] == 13
    assert first["event"] == {"type": "vystak.turn.rewind", "to_seq": 3}


@pytest.mark.asyncio
async def test_falls_back_to_boundary_seq_when_checkpoint_unknown(bridge_factory):
    journal = InMemoryTurnJournal()
    await journal.create("t1", "s.t1", {})
    await journal.set_thread_id("t1", "resp_1")
    await journal.record_boundary("t1", "ck-2", 8)
    await journal.set_last_seq("t1", 12)

    bridge = bridge_factory(journal=journal, resume_checkpoint_id="ck-unknown")
    await bridge.redrive_unfinished()

    assert json.loads(bridge.published_payloads[0])["event"]["to_seq"] == 8


@pytest.mark.asyncio
async def test_parked_turns_are_not_redriven(bridge_factory):
    journal = InMemoryTurnJournal()
    await journal.create("t1", "s.t1", {})
    await journal.set_status("t1", "parked")
    bridge = bridge_factory(journal=journal)
    assert await bridge.redrive_unfinished() == 0
    assert bridge.published_payloads == []


@pytest.mark.asyncio
async def test_attempts_cap_fails_the_turn(bridge_factory):
    journal = InMemoryTurnJournal()
    await journal.create("t1", "s.t1", {})
    await journal.set_last_seq("t1", 5)
    for _ in range(MAX_REDRIVE_ATTEMPTS):
        await journal.bump_attempts("t1")

    bridge = bridge_factory(journal=journal)
    await bridge.redrive_unfinished()

    assert (await journal.get("t1")).status == "failed"
    published = [json.loads(p)["event"]["type"] for p in bridge.published_payloads]
    assert published == ["response.failed"]


@pytest.mark.asyncio
async def test_attempts_increment_on_redrive(bridge_factory):
    journal = InMemoryTurnJournal()
    await journal.create("t1", "s.t1", {})
    await journal.set_thread_id("t1", "resp_1")
    bridge = bridge_factory(journal=journal, resume_checkpoint_id="ck-1")
    await bridge.redrive_unfinished()
    assert (await journal.get("t1")).attempts == 1


@pytest.mark.asyncio
async def test_turn_with_no_thread_id_fails_immediately_without_a_rewind(bridge_factory):
    # A turn that crashed before `response.created` ever arrived has no
    # thread_id — there is nothing the resume endpoint can drive. It should
    # be failed on the spot, without wasting a rewind marker on a resume
    # that's guaranteed to be impossible.
    journal = InMemoryTurnJournal()
    await journal.create("t1", "s.t1", {})
    await journal.set_last_seq("t1", 5)

    bridge = bridge_factory(journal=journal)
    await bridge.redrive_unfinished()

    assert (await journal.get("t1")).status == "failed"
    published = [json.loads(p)["event"]["type"] for p in bridge.published_payloads]
    assert published == ["response.failed"]
