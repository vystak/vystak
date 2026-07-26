"""Tests for the unified store-driven TaskScheduler.

Fixture pattern ported from the deleted v2 `test_scheduler.py`: AsyncMock
transport/delivery, `SimpleNamespace` replies. Fire-semantics assertions are
made against `_fire_one` directly wherever that keeps timing deterministic
(no sleep-based flakiness); `_fire_due` is exercised for its own
scheduling-advance behaviour (busy-skip, next_fire_at recompute/clear), plus
one full integration test that drains `sched._fire_tasks` via
`asyncio.gather` to prove the `_fire_due` -> `_fire_one` wiring end to end.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, _Call

import pytest
from vystak.schema.schedule import ScheduledTask
from vystak_channel_runtime.heartbeat import DEFAULT_PROMPT
from vystak_heartbeat.schedule_store import SqliteScheduleStore
from vystak_heartbeat.session_store import InMemoryStore
from vystak_heartbeat.task_scheduler import TaskScheduler

AGENT = "a.agents.default"
NOW = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)


def now() -> datetime:
    return NOW


def past() -> datetime:
    return NOW - timedelta(minutes=1)


def future() -> datetime:
    return NOW + timedelta(minutes=5)


def _reply(text: str, model_resolved: str | None = None):
    return SimpleNamespace(
        text=text,
        metadata={"model_resolved": model_resolved} if model_resolved else {},
    )


def _sent_message(awaited_call: _Call):
    return awaited_call.args[1]


def _sent_metadata(awaited_call: _Call) -> dict:
    return awaited_call.kwargs["metadata"]


@pytest.fixture
async def store(tmp_path):
    s = SqliteScheduleStore(str(tmp_path / "sched.db"))
    await s.connect()
    yield s
    await s.close()


@pytest.fixture
def transport():
    t = AsyncMock()
    t.send_task = AsyncMock(return_value=_reply("pong"))
    return t


@pytest.fixture
def delivery():
    return AsyncMock()


@pytest.fixture
def sessions():
    return InMemoryStore()


@pytest.fixture
def sched(store, transport, delivery, sessions):
    return TaskScheduler(
        store=store,
        transport=transport,
        delivery=delivery,
        sessions=sessions,
        agent_names={AGENT: "bot"},
    )


class TestFireSemantics:
    async def test_fires_due_task_and_delivers(self, sched, store, transport, delivery):
        rec = await store.create_runtime(
            AGENT,
            ScheduledTask(
                name="r",
                cron="* * * * *",
                prompt="go",
                target_channel="chat.channels.dev",
                target_thread="t1",
            ),
            created_by="cli",
        )
        await store.set_next_fire(rec.id, past())
        await sched._fire_due(now())
        await asyncio.gather(*sched._fire_tasks)
        transport.send_task.assert_awaited_once()
        delivery.deliver.assert_awaited_once()
        assert (await store.get(rec.id)).last_fire_at is not None

    async def test_no_target_channel_no_delivery(self, sched, store, transport, delivery):
        rec = await store.create_runtime(
            AGENT,
            ScheduledTask(name="r", cron="* * * * *", prompt="go", target_thread="t1"),
            created_by="cli",
        )
        await sched._fire_one(rec)
        transport.send_task.assert_awaited_once()
        delivery.deliver.assert_not_called()

    async def test_no_target_thread_no_delivery(self, sched, store, transport, delivery):
        rec = await store.create_runtime(
            AGENT,
            ScheduledTask(
                name="r", cron="* * * * *", prompt="go",
                target_channel="chat.channels.dev",
            ),
            created_by="cli",
        )
        await sched._fire_one(rec)
        transport.send_task.assert_awaited_once()
        delivery.deliver.assert_not_called()

    async def test_ack_suppresses_delivery(self, sched, store, transport, delivery):
        transport.send_task = AsyncMock(return_value=_reply("HEARTBEAT_OK"))
        rec = await store.create_runtime(
            AGENT,
            ScheduledTask(
                name="r",
                cron="* * * * *",
                prompt="go",
                ack_max_chars=300,
                target_channel="chat.channels.dev",
                target_thread="t1",
            ),
            created_by="cli",
        )
        await sched._fire_one(rec)
        delivery.deliver.assert_not_called()

    async def test_ack_not_suppressed_without_ack_max_chars(
        self, sched, store, transport, delivery
    ):
        transport.send_task = AsyncMock(return_value=_reply("HEARTBEAT_OK"))
        rec = await store.create_runtime(
            AGENT,
            ScheduledTask(
                name="r",
                cron="* * * * *",
                prompt="go",
                target_channel="chat.channels.dev",
                target_thread="t1",
            ),
            created_by="cli",
        )
        await sched._fire_one(rec)
        delivery.deliver.assert_awaited_once()

    async def test_heartbeat_task_uses_default_prompt(self, sched, store, transport):
        rec = await store.create_runtime(
            AGENT,
            ScheduledTask(name="heartbeat", cron="* * * * *"),
            created_by="definition",
        )
        await sched._fire_one(rec)
        sent = _sent_message(transport.send_task.await_args)
        assert sent.parts[0]["text"] == DEFAULT_PROMPT

    async def test_other_promptless_task_uses_name_fallback(self, sched, store, transport):
        rec = await store.create_runtime(
            AGENT,
            ScheduledTask(name="digest", cron="* * * * *"),
            created_by="cli",
        )
        await sched._fire_one(rec)
        sent = _sent_message(transport.send_task.await_args)
        assert sent.parts[0]["text"] == "Scheduled task 'digest' fired."

    async def test_oneshot_completes_after_fire(self, sched, store, transport):
        rec = await store.create_runtime(
            AGENT, ScheduledTask(name="once", at=future()), created_by="cli"
        )
        await store.set_next_fire(rec.id, past())
        await sched._fire_due(now())
        await asyncio.gather(*sched._fire_tasks)
        got = await store.get(rec.id)
        assert got.status == "completed"
        assert got.next_fire_at is None

    async def test_recurring_reschedules_after_fire(self, sched, store, transport):
        rec = await store.create_runtime(
            AGENT, ScheduledTask(name="r", cron="* * * * *"), created_by="cli"
        )
        await store.set_next_fire(rec.id, past())
        await sched._fire_due(now())
        got = await store.get(rec.id)
        assert got.next_fire_at is not None
        assert got.next_fire_at > now()
        await asyncio.gather(*sched._fire_tasks)

    async def test_skip_when_busy(self, sched, store, transport):
        rec = await store.create_runtime(
            AGENT,
            ScheduledTask(name="r", cron="* * * * *", skip_when_busy=True),
            created_by="cli",
        )
        await store.set_next_fire(rec.id, past())
        sched._busy.add(rec.id)
        await sched._fire_due(now())
        transport.send_task.assert_not_called()
        assert not sched._fire_tasks
        # Documents current behaviour, not a design requirement: the skip
        # branch runs BEFORE the next_fire_at advance, so a busy-skipped row
        # is left due (`next_fire_at` unchanged, still in the past) rather
        # than rescheduled — `_run`'s poll would tight-loop on this row until
        # `_busy` clears. Known, flagged in the task report; not fixed here.
        assert (await store.get(rec.id)).next_fire_at == past()

    async def test_not_skipped_when_busy_flag_disabled(self, sched, store, transport):
        rec = await store.create_runtime(
            AGENT,
            ScheduledTask(name="r", cron="* * * * *", skip_when_busy=False),
            created_by="cli",
        )
        await store.set_next_fire(rec.id, past())
        sched._busy.add(rec.id)
        await sched._fire_due(now())
        await asyncio.gather(*sched._fire_tasks)
        transport.send_task.assert_awaited_once()

    async def test_isolated_session_synthetic_id(self, sched, store, transport):
        rec = await store.create_runtime(
            AGENT,
            ScheduledTask(name="r", cron="* * * * *", isolated_session=True),
            created_by="cli",
        )
        await sched._fire_one(rec)
        md = _sent_metadata(transport.send_task.await_args)
        assert md["session_id"].startswith("__scheduled__")

    async def test_non_isolated_session_uses_target_thread(self, sched, store, transport):
        rec = await store.create_runtime(
            AGENT,
            ScheduledTask(
                name="r", cron="* * * * *", isolated_session=False, target_thread="t1"
            ),
            created_by="cli",
        )
        await sched._fire_one(rec)
        md = _sent_metadata(transport.send_task.await_args)
        assert md["session_id"] == "t1"

    async def test_scheduled_task_metadata_key(self, sched, store, transport):
        rec = await store.create_runtime(
            AGENT, ScheduledTask(name="r", cron="* * * * *"), created_by="cli"
        )
        await sched._fire_one(rec)
        md = _sent_metadata(transport.send_task.await_args)
        assert md["scheduled_task"] == "r"

    async def test_busy_cleared_on_transport_error(self, sched, store, transport):
        transport.send_task = AsyncMock(side_effect=RuntimeError("boom"))
        rec = await store.create_runtime(
            AGENT, ScheduledTask(name="r", cron="* * * * *"), created_by="cli"
        )
        # Errors are caught and logged inside _fire_one — spawned fires must
        # never crash the loop.
        await sched._fire_one(rec)
        assert rec.id not in sched._busy


class TestModelStickiness:
    """Ported verbatim from `HeartbeatScheduler._fire` (old scheduler.py)."""

    async def test_persists_model_on_first_resolve(self, sched, store, transport, sessions):
        transport.send_task = AsyncMock(return_value=_reply("alert", "haiku"))
        rec = await store.create_runtime(
            AGENT,
            ScheduledTask(
                name="r", cron="* * * * *", isolated_session=False,
                target_thread="C1", model="opus",
            ),
            created_by="cli",
        )
        await sched._fire_one(rec)
        assert await sessions.get_model("C1") == "haiku"

    async def test_does_not_overwrite_stored_model(self, sched, store, transport, sessions):
        await sessions.set_model("C1", "haiku")
        transport.send_task = AsyncMock(return_value=_reply("alert", "sonnet"))
        rec = await store.create_runtime(
            AGENT,
            ScheduledTask(
                name="r", cron="* * * * *", isolated_session=False, target_thread="C1"
            ),
            created_by="cli",
        )
        await sched._fire_one(rec)
        assert await sessions.get_model("C1") == "haiku"

    async def test_uses_stored_model_as_override(self, sched, store, transport, sessions):
        await sessions.set_model("C1", "haiku")
        rec = await store.create_runtime(
            AGENT,
            ScheduledTask(
                name="r", cron="* * * * *", isolated_session=False,
                target_thread="C1", model="opus",
            ),
            created_by="cli",
        )
        await sched._fire_one(rec)
        md = _sent_metadata(transport.send_task.await_args)
        assert md["model_override"] == "haiku"

    async def test_falls_back_to_task_model_when_nothing_stored(
        self, sched, store, transport, sessions
    ):
        rec = await store.create_runtime(
            AGENT,
            ScheduledTask(
                name="r", cron="* * * * *", isolated_session=False,
                target_thread="C1", model="opus",
            ),
            created_by="cli",
        )
        await sched._fire_one(rec)
        md = _sent_metadata(transport.send_task.await_args)
        assert md["model_override"] == "opus"


class TestStartupReconcile:
    async def test_oneshot_within_grace_fires_on_startup(self, sched, store):
        at = datetime.now(UTC) - timedelta(hours=2)
        rec = await store.create_runtime(
            AGENT, ScheduledTask(name="o", at=at), created_by="cli"
        )
        await sched.startup_reconcile_next_fires()
        got = await store.get(rec.id)
        assert got.status == "active"
        due = await store.due(datetime.now(UTC) + timedelta(seconds=1))
        assert rec.id in [d.id for d in due]

    async def test_oneshot_beyond_grace_marked_missed(self, sched, store):
        at = datetime.now(UTC) - timedelta(days=2)
        rec = await store.create_runtime(
            AGENT, ScheduledTask(name="o", at=at), created_by="cli"
        )
        await sched.startup_reconcile_next_fires()
        got = await store.get(rec.id)
        assert got.status == "missed"

    async def test_oneshot_future_scheduled_not_fired(self, sched, store):
        at = datetime.now(UTC) + timedelta(hours=1)
        rec = await store.create_runtime(
            AGENT, ScheduledTask(name="o", at=at), created_by="cli"
        )
        await sched.startup_reconcile_next_fires()
        got = await store.get(rec.id)
        assert got.status == "active"
        assert got.next_fire_at is not None
        assert got.next_fire_at > datetime.now(UTC)

    async def test_recurring_recomputed_from_now(self, sched, store):
        rec = await store.create_runtime(
            AGENT, ScheduledTask(name="r", every="1h"), created_by="cli"
        )
        start = datetime.now(UTC)
        await sched.startup_reconcile_next_fires()
        end = datetime.now(UTC)
        got = await store.get(rec.id)
        assert got.next_fire_at is not None
        assert start + timedelta(hours=1) <= got.next_fire_at <= end + timedelta(hours=1)


class TestWakeAndLifecycle:
    def test_wake_sets_event(self, sched):
        assert not sched._wake.is_set()
        sched.wake()
        assert sched._wake.is_set()

    async def test_start_and_stop_lifecycle(self, sched):
        await sched.start()
        assert sched._task is not None
        await sched.stop()
        assert sched._task is None

    async def test_stop_without_start_is_a_noop(self, sched):
        await sched.stop()


class TestBackfill:
    async def test_new_runtime_task_gets_next_fire_backfilled(self, sched, store):
        rec = await store.create_runtime(
            AGENT, ScheduledTask(name="r", every="30m"), created_by="cli"
        )
        assert rec.next_fire_at is None
        await sched._backfill_next_fires(now())
        got = await store.get(rec.id)
        assert got.next_fire_at == now() + timedelta(minutes=30)

    async def test_backfill_leaves_existing_next_fire_untouched(self, sched, store):
        rec = await store.create_runtime(
            AGENT, ScheduledTask(name="r", cron="* * * * *"), created_by="cli"
        )
        await store.set_next_fire(rec.id, future())
        await sched._backfill_next_fires(now())
        got = await store.get(rec.id)
        assert got.next_fire_at == future()
