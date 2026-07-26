"""SqliteScheduleStore — persistent task storage with declarative reconciliation."""

from datetime import UTC, datetime, timedelta

import pytest
from vystak.schema.schedule import ScheduledTask
from vystak_heartbeat.schedule_store import (
    NameCollisionError,
    SqliteScheduleStore,
)

AGENT = "a.agents.default"
NOW = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)


@pytest.fixture
async def store(tmp_path):
    s = SqliteScheduleStore(str(tmp_path / "sched.db"))
    await s.connect()
    yield s
    await s.close()


def _cron(name="digest"):
    return ScheduledTask(name=name, cron="0 9 * * 1")


class TestRuntimeCrud:
    async def test_create_list_get(self, store):
        rec = await store.create_runtime(AGENT, _cron("r1"), created_by="cli")
        assert rec.source == "runtime" and rec.status == "active"
        assert (await store.get(rec.id)).task.name == "r1"
        assert [r.id for r in await store.list(agent=AGENT)] == [rec.id]

    async def test_name_collision_within_agent(self, store):
        await store.create_runtime(AGENT, _cron("x"), created_by="cli")
        with pytest.raises(NameCollisionError):
            await store.create_runtime(AGENT, _cron("x"), created_by="cli")

    async def test_cancel(self, store):
        rec = await store.create_runtime(AGENT, _cron(), created_by="cli")
        await store.cancel_runtime(rec.id)
        assert (await store.get(rec.id)).status == "cancelled"

    async def test_update_declarative_forbidden(self, store):
        await store.reconcile_declarative(AGENT, [_cron("d")])
        [rec] = await store.list(agent=AGENT, source="declarative")
        with pytest.raises(PermissionError):
            await store.update_runtime(rec.id, {"enabled": False})
        with pytest.raises(PermissionError):
            await store.cancel_runtime(rec.id)


class TestReconcile:
    async def test_upsert_and_prune(self, store):
        await store.reconcile_declarative(AGENT, [_cron("keep"), _cron("drop")])
        await store.reconcile_declarative(AGENT, [_cron("keep"),
                                                  _cron("new")])
        names = {r.task.name for r in await store.list(agent=AGENT)}
        assert names == {"keep", "new"}

    async def test_runtime_tasks_survive_reconcile(self, store):
        await store.create_runtime(AGENT, _cron("mine"), created_by="agent:" + AGENT)
        await store.reconcile_declarative(AGENT, [])
        assert {r.task.name for r in await store.list(agent=AGENT)} == {"mine"}

    async def test_runtime_collides_with_declarative(self, store):
        await store.reconcile_declarative(AGENT, [_cron("d")])
        with pytest.raises(NameCollisionError):
            await store.create_runtime(AGENT, _cron("d"), created_by="cli")

    async def test_reconcile_updates_changed_payload(self, store):
        await store.reconcile_declarative(AGENT, [_cron("d")])
        changed = ScheduledTask(name="d", cron="0 10 * * 1")
        await store.reconcile_declarative(AGENT, [changed])
        [rec] = await store.list(agent=AGENT)
        assert rec.task.cron == "0 10 * * 1"

    async def test_declarative_collision_with_runtime_skips_and_warns(
        self, store, caplog
    ):
        await store.create_runtime(AGENT, _cron("mine"), created_by="agent:" + AGENT)
        with caplog.at_level("WARNING"):
            await store.reconcile_declarative(
                AGENT, [ScheduledTask(name="mine", cron="0 10 * * 2")]
            )
        [rec] = await store.list(agent=AGENT)
        assert rec.source == "runtime"
        assert rec.task.cron == "0 9 * * 1"
        assert any("mine" in r.message for r in caplog.records)

    async def test_declarative_collision_does_not_resurrect_cancelled_runtime(
        self, store
    ):
        rec = await store.create_runtime(
            AGENT, _cron("mine"), created_by="agent:" + AGENT
        )
        await store.cancel_runtime(rec.id)
        await store.reconcile_declarative(
            AGENT, [ScheduledTask(name="mine", cron="0 10 * * 2")]
        )
        got = await store.get(rec.id)
        assert got.status == "cancelled"
        assert got.task.cron == "0 9 * * 1"

    async def test_collision_skip_does_not_block_other_declaratives(self, store):
        await store.create_runtime(AGENT, _cron("mine"), created_by="agent:" + AGENT)
        await store.reconcile_declarative(
            AGENT,
            [ScheduledTask(name="mine", cron="0 10 * * 2"), _cron("other")],
        )
        [other] = await store.list(agent=AGENT, source="declarative")
        assert other.task.name == "other"
        assert other.status == "active"
        [mine] = await store.list(agent=AGENT, source="runtime")
        assert mine.task.cron == "0 9 * * 1"


class TestFireBookkeeping:
    async def test_due_and_next_fire(self, store):
        rec = await store.create_runtime(AGENT, _cron(), created_by="cli")
        await store.set_next_fire(rec.id, NOW - timedelta(minutes=1))
        assert [r.id for r in await store.due(NOW)] == [rec.id]
        assert await store.min_next_fire() == NOW - timedelta(minutes=1)

    async def test_disabled_not_due(self, store):
        rec = await store.create_runtime(
            AGENT, ScheduledTask(name="off", cron="* * * * *", enabled=False),
            created_by="cli")
        await store.set_next_fire(rec.id, NOW - timedelta(minutes=1))
        assert await store.due(NOW) == []

    async def test_record_fire_completes_oneshot(self, store):
        rec = await store.create_runtime(
            AGENT, ScheduledTask(name="once", at=NOW), created_by="cli")
        await store.record_fire(rec.id, NOW, "done", completed=True)
        got = await store.get(rec.id)
        assert got.status == "completed" and got.last_result == "done"

    async def test_persistence_across_reconnect(self, store, tmp_path):
        rec = await store.create_runtime(AGENT, _cron("p"), created_by="cli")
        await store.close()
        s2 = SqliteScheduleStore(str(tmp_path / "sched.db"))
        await s2.connect()
        assert (await s2.get(rec.id)).task.name == "p"
        await s2.close()


# Extra coverage beyond the brief's test file: contract paths Tasks 6-9 will
# call directly but the brief's suite above doesn't exercise.
class TestExtraContractCoverage:
    async def test_update_runtime_happy_path(self, store):
        rec = await store.create_runtime(AGENT, _cron("r"), created_by="cli")
        updated = await store.update_runtime(rec.id, {"prompt": "new prompt"})
        assert updated.task.prompt == "new prompt"
        assert updated.next_fire_at is None
        got = await store.get(rec.id)
        assert got.task.prompt == "new prompt"

    async def test_update_runtime_clears_next_fire_on_shape_change(self, store):
        rec = await store.create_runtime(AGENT, _cron("r"), created_by="cli")
        await store.set_next_fire(rec.id, NOW)
        updated = await store.update_runtime(rec.id, {"cron": "0 10 * * 1"})
        assert updated.task.cron == "0 10 * * 1"
        assert updated.next_fire_at is None

    async def test_update_runtime_keeps_next_fire_when_shape_unchanged(self, store):
        rec = await store.create_runtime(AGENT, _cron("r"), created_by="cli")
        await store.set_next_fire(rec.id, NOW)
        updated = await store.update_runtime(rec.id, {"prompt": "hi"})
        assert updated.next_fire_at == NOW

    async def test_update_runtime_missing_id_raises_key_error(self, store):
        with pytest.raises(KeyError):
            await store.update_runtime("nope", {"enabled": False})

    async def test_cancel_runtime_missing_id_raises_key_error(self, store):
        with pytest.raises(KeyError):
            await store.cancel_runtime("nope")

    async def test_record_fire_recurring_leaves_status_active(self, store):
        rec = await store.create_runtime(AGENT, _cron("r"), created_by="cli")
        await store.record_fire(rec.id, NOW, "ok")
        got = await store.get(rec.id)
        assert got.status == "active"
        assert got.last_result == "ok"
        assert got.last_fire_at == NOW

    async def test_mark_missed(self, store):
        rec = await store.create_runtime(AGENT, _cron("r"), created_by="cli")
        await store.mark_missed(rec.id)
        assert (await store.get(rec.id)).status == "missed"

    async def test_set_next_fire_none_clears(self, store):
        rec = await store.create_runtime(AGENT, _cron("r"), created_by="cli")
        await store.set_next_fire(rec.id, NOW)
        await store.set_next_fire(rec.id, None)
        assert (await store.get(rec.id)).next_fire_at is None

    async def test_min_next_fire_across_multiple_rows(self, store):
        r1 = await store.create_runtime(AGENT, _cron("a"), created_by="cli")
        r2 = await store.create_runtime(AGENT, _cron("b"), created_by="cli")
        await store.set_next_fire(r1.id, NOW)
        await store.set_next_fire(r2.id, NOW - timedelta(hours=1))
        assert await store.min_next_fire() == NOW - timedelta(hours=1)
