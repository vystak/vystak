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


@pytest.mark.asyncio
async def test_status_rpc_failure_still_bounded_by_deadline(persister_harness):
    """A permanently unreachable agent must not loop forever — the deadline
    still applies on the turn_status-exception path."""
    h = persister_harness(
        event_batches=[[]] * 50,
        turn_status=RuntimeError("boom"),
        clock=[0.0, 10_000.0],
    )
    await run_turn_persister(h.rt, "c1", "t1", "s.t1", deadline_s=900.0)
    assert h.reattach_count < 50
    assert h.cleared_active_turn is True


@pytest.mark.asyncio
async def test_parked_time_does_not_count_toward_deadline(persister_harness):
    """Idle 10 times while parked with the clock far past the deadline —
    the persister keeps waiting because parked time is excluded."""
    h = persister_harness(
        event_batches=[[]] * 10 + [[("done", "resp_1")]],
        turn_status="parked",
        clock=[0.0] + [10_000.0] * 12,   # way past 900s, but parked
    )
    await run_turn_persister(h.rt, "c1", "t1", "s.t1")
    assert h.persisted_rows and h.persisted_rows[0]["response_id"] == "resp_1"


@pytest.mark.asyncio
async def test_confirmed_park_survives_status_rpc_flakes(persister_harness):
    """Once a park is CONFIRMED by a successful poll, subsequent turn_status
    RPC failures must not close the open parked span or count that time
    toward the deadline — 'park indefinitely' governs. Only pre-park active
    time (10s here) is ever measured, so the clock jumping to 50_000 during
    the flakes never trips the 900s deadline."""
    h = persister_harness(
        event_batches=[[]] * 6 + [[("done", "resp_1")]],
        turn_status=["parked"] + [RuntimeError("agent unreachable")] * 5,
        clock=[0.0, 10.0] + [50_000.0] * 5,
        # idx0=started, idx1=park confirmed at t=10 (10s pre-park active),
        # idx2..idx6=five flaky polls, clock stuck far past the deadline.
    )
    await run_turn_persister(h.rt, "c1", "t1", "s.t1", deadline_s=900.0)
    assert h.persisted_rows and h.persisted_rows[0]["response_id"] == "resp_1"
    assert h.cleared_active_turn is True


@pytest.mark.asyncio
async def test_confirmed_park_flake_still_bounded_by_pre_park_overrun(persister_harness):
    """Discriminates 'open span excluded from the deadline check' from
    'deadline check skipped entirely while a park is confirmed'. Pre-park
    active time alone (950s) already exceeds the 900s deadline; the park is
    confirmed at that point, and the very next RPC flake must still surface
    the overrun (via the open-span-subtracted active-time math), not swallow
    it just because a park was seen once."""
    h = persister_harness(
        event_batches=[[]] * 6 + [[("done", "resp_1")]],
        turn_status=["parked"] + [RuntimeError("agent unreachable")] * 5,
        clock=[0.0, 950.0] + [50_000.0] * 5,
    )
    await run_turn_persister(h.rt, "c1", "t1", "s.t1", deadline_s=900.0)
    assert h.reattach_count < 7
    # errored with no accumulated output means nothing gets persisted at all.
    assert h.persisted_rows == []


@pytest.mark.asyncio
async def test_parked_total_accumulates_across_two_separate_parks(persister_harness):
    """Two sequential confirmed parks (the normal shape for a turn with two
    gated tool calls) must both have their spans excluded — parked_total
    accumulates rather than being overwritten by the second span."""
    h = persister_harness(
        event_batches=[[]] * 4 + [[("done", "resp_1")]],
        turn_status=["parked", "running", "parked", "running"],
        # pre-park: 10s: park#1 confirmed at t=10, lasts 5000s (closed at
        # t=5010, active=10); inter-park: 20s more (park#2 confirmed at
        # t=5030), lasts 5000s (closed at t=10030, active=30) — always well
        # under the 900s deadline if both 5000s spans are truly excluded.
        clock=[0.0, 10.0, 5010.0, 5030.0, 10030.0],
    )
    await run_turn_persister(h.rt, "c1", "t1", "s.t1", deadline_s=900.0)
    assert h.persisted_rows and h.persisted_rows[0]["response_id"] == "resp_1"


@pytest.mark.asyncio
async def test_mixed_pre_park_flake_and_resume_concludes_normally(persister_harness):
    """800s of genuine pre-park active time, then a confirmed park, then RPC
    flakes with the clock way out (excluded), then a successful poll closes
    the span (resuming deadline accounting at the 800s mark, not at the
    flake-inflated 'now'), then done arrives — total active time never
    reaches the 900s deadline."""
    h = persister_harness(
        event_batches=[[]] * 6 + [[("done", "resp_1")]],
        turn_status=[
            "running",                          # iter0: still pre-park
            "parked",                           # iter1: park confirmed at t=800
            RuntimeError("agent unreachable"),  # iter2: flake, clock far out
            RuntimeError("agent unreachable"),  # iter3: flake, clock far out
            RuntimeError("agent unreachable"),  # iter4: flake, clock far out
            "running",                          # iter5: poll succeeds, closes span
        ],
        clock=[0.0, 800.0, 800.0, 50_000.0, 50_000.0, 50_000.0, 50_500.0],
    )
    await run_turn_persister(h.rt, "c1", "t1", "s.t1", deadline_s=900.0)
    assert h.persisted_rows and h.persisted_rows[0]["response_id"] == "resp_1"
    assert h.cleared_active_turn is True
