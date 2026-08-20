"""Idle-during-a-turn must consult the agent's turn status instead of
concluding the turn outright — Task 10."""

import pytest
from vystak_channel_panel.turn_worker import run_turn_persister


@pytest.mark.asyncio
async def test_idle_with_running_status_keeps_waiting(persister_harness):
    h = persister_harness(
        event_batches=[[], [("done", "resp_1")]],  # idle, then the reply
        turn_status="running",
    )
    await run_turn_persister(h.rt, "c1", "t1", "s.t1")

    assert h.reattach_count == 2
    assert h.persisted_rows[0]["response_id"] == "resp_1"
    assert h.cleared_active_turn is True


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["done", "failed", "unknown"])
async def test_idle_with_terminal_status_concludes(persister_harness, status):
    h = persister_harness(event_batches=[[]], turn_status=status)
    await run_turn_persister(h.rt, "c1", "t1", "s.t1")
    assert h.reattach_count == 1
    assert h.cleared_active_turn is True


@pytest.mark.asyncio
async def test_status_rpc_failure_keeps_waiting(persister_harness):
    """The agent being unreachable is exactly when the answer matters."""
    h = persister_harness(
        event_batches=[[], [("done", "resp_1")]],
        turn_status=RuntimeError("agent unreachable"),
    )
    await run_turn_persister(h.rt, "c1", "t1", "s.t1")
    assert h.reattach_count == 2
    assert h.persisted_rows[0]["response_id"] == "resp_1"


@pytest.mark.asyncio
async def test_overall_deadline_concludes_as_errored(persister_harness):
    h = persister_harness(
        event_batches=[[]] * 50,
        turn_status="running",
        clock=[0.0, 901.0],
    )
    await run_turn_persister(h.rt, "c1", "t1", "s.t1", deadline_s=900.0)
    assert h.cleared_active_turn is True
    assert h.reattach_count < 50


@pytest.mark.asyncio
async def test_parked_status_keeps_waiting(persister_harness):
    h = persister_harness(event_batches=[[], [("done", "resp_1")]], turn_status="parked")
    await run_turn_persister(h.rt, "c1", "t1", "s.t1")
    assert h.reattach_count == 2
