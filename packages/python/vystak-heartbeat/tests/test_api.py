"""Tests for the scheduler REST API (`build_api`).

Fixture pattern: real `SqliteScheduleStore` (tmp_path) + a `MagicMock()`
scheduler for the CRUD/mutation tests (mirrors the ASGITransport +
AsyncClient convention used by `vystak-channel-panel`'s API tests). The
backfill test swaps in a real `TaskScheduler` with mocked transport/delivery
to prove the create -> backfill -> GET wiring end to end.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from vystak.schema.schedule import ScheduledTask
from vystak_heartbeat.schedule_store import SqliteScheduleStore
from vystak_heartbeat.session_store import InMemoryStore
from vystak_heartbeat.task_scheduler import TaskScheduler

AGENT = "bot.agents.default"


def _body(name: str = "digest", agent: str = AGENT, **overrides) -> dict:
    body = {"agent": agent, "name": name, "cron": "0 9 * * 1"}
    body.update(overrides)
    return body


@pytest.fixture
async def store(tmp_path):
    s = SqliteScheduleStore(str(tmp_path / "sched.db"))
    await s.connect()
    yield s
    await s.close()


@pytest.fixture
def scheduler():
    return MagicMock()


@pytest.fixture
async def client(store, scheduler):
    from vystak_heartbeat.api import build_api

    app = build_api(store, scheduler)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://sched") as c:
        yield c


async def test_healthz(client):
    resp = await client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def test_create_task(client, scheduler):
    resp = await client.post("/tasks", json=_body())
    assert resp.status_code == 201
    body = resp.json()
    assert body["agent"] == AGENT
    assert body["name"] == "digest"
    assert body["source"] == "runtime"
    assert body["status"] == "active"
    assert body["created_by"] == "api"
    assert body["next_fire_at"] is None
    assert body["last_fire_at"] is None
    assert body["last_result"] is None
    assert body["task"]["cron"] == "0 9 * * 1"
    assert "id" in body
    scheduler.wake.assert_called_once()


async def test_list_tasks(client):
    await client.post("/tasks", json=_body(name="a"))
    await client.post("/tasks", json=_body(name="b"))
    resp = await client.get("/tasks", params={"agent": AGENT})
    assert resp.status_code == 200
    names = {t["name"] for t in resp.json()["tasks"]}
    assert names == {"a", "b"}


async def test_list_tasks_filters_by_status(client):
    created = (await client.post("/tasks", json=_body(name="a"))).json()
    await client.post("/tasks", json=_body(name="b"))
    await client.delete(f"/tasks/{created['id']}")
    resp = await client.get("/tasks", params={"status": "active"})
    names = {t["name"] for t in resp.json()["tasks"]}
    assert names == {"b"}


async def test_get_task(client):
    created = (await client.post("/tasks", json=_body())).json()
    resp = await client.get(f"/tasks/{created['id']}")
    assert resp.status_code == 200
    assert resp.json()["id"] == created["id"]


async def test_get_task_404(client):
    resp = await client.get("/tasks/does-not-exist")
    assert resp.status_code == 404


async def test_patch_task(client, scheduler):
    created = (await client.post("/tasks", json=_body())).json()
    scheduler.reset_mock()
    resp = await client.patch(f"/tasks/{created['id']}", json={"enabled": False})
    assert resp.status_code == 200
    assert resp.json()["task"]["enabled"] is False
    scheduler.wake.assert_called_once()


async def test_patch_task_404(client):
    resp = await client.patch("/tasks/does-not-exist", json={"enabled": False})
    assert resp.status_code == 404


async def test_delete_task(client, scheduler):
    created = (await client.post("/tasks", json=_body())).json()
    scheduler.reset_mock()
    resp = await client.delete(f"/tasks/{created['id']}")
    assert resp.status_code == 204
    scheduler.wake.assert_called_once()
    # cancel_runtime soft-cancels — the row is still readable, just inactive.
    resp2 = await client.get(f"/tasks/{created['id']}")
    assert resp2.status_code == 200
    assert resp2.json()["status"] == "cancelled"


async def test_delete_task_404(client):
    resp = await client.delete("/tasks/does-not-exist")
    assert resp.status_code == 404


async def test_create_name_collision_409(client):
    await client.post("/tasks", json=_body(name="dup"))
    resp = await client.post("/tasks", json=_body(name="dup"))
    assert resp.status_code == 409


async def test_create_two_shapes_422(client):
    # cron (from _body's default) AND every both set -> validator rejects.
    resp = await client.post("/tasks", json=_body(every="5m"))
    assert resp.status_code == 422


async def test_patch_declarative_409(client, store):
    await store.reconcile_declarative(
        AGENT, [ScheduledTask(name="heartbeat", cron="*/5 * * * *")]
    )
    [rec] = await store.list(agent=AGENT, source="declarative")
    resp = await client.patch(f"/tasks/{rec.id}", json={"enabled": False})
    assert resp.status_code == 409
    assert (
        resp.json()["detail"]
        == "declarative task — change the YAML definition and re-apply"
    )


async def test_delete_declarative_409(client, store):
    await store.reconcile_declarative(
        AGENT, [ScheduledTask(name="heartbeat", cron="*/5 * * * *")]
    )
    [rec] = await store.list(agent=AGENT, source="declarative")
    resp = await client.delete(f"/tasks/{rec.id}")
    assert resp.status_code == 409
    assert (
        resp.json()["detail"]
        == "declarative task — change the YAML definition and re-apply"
    )


async def test_patch_invalid_shape_422(client, scheduler):
    """PATCH with both cron and every set → 422, scheduler.wake not called."""
    created = (await client.post("/tasks", json=_body())).json()
    scheduler.reset_mock()
    # Try to add every to a task that already has cron
    resp = await client.patch(f"/tasks/{created['id']}", json={"every": "5m"})
    assert resp.status_code == 422
    # Validate that the error mentions the shape constraint
    detail = resp.json()["detail"]
    assert "exactly one" in detail.lower()
    scheduler.wake.assert_not_called()


async def test_patch_invalid_cron_422(client, scheduler):
    """PATCH with invalid cron string → 422, scheduler.wake not called."""
    created = (await client.post("/tasks", json=_body())).json()
    scheduler.reset_mock()
    resp = await client.patch(f"/tasks/{created['id']}", json={"cron": "not a cron"})
    assert resp.status_code == 422
    scheduler.wake.assert_not_called()


async def test_backfill_integration(store):
    """POST leaves next_fire_at NULL; a real scheduler's backfill fills it."""
    from vystak_heartbeat.api import build_api

    transport = AsyncMock()
    delivery = AsyncMock()
    sessions = InMemoryStore()
    real_scheduler = TaskScheduler(
        store=store,
        transport=transport,
        delivery=delivery,
        sessions=sessions,
        agent_names={AGENT: "bot"},
    )
    app = build_api(store, real_scheduler)
    asgi_transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=asgi_transport, base_url="http://sched"
    ) as client:
        created = (await client.post("/tasks", json=_body())).json()
        assert created["next_fire_at"] is None

        await real_scheduler._backfill_next_fires(datetime.now(UTC))

        resp = await client.get(f"/tasks/{created['id']}")
        assert resp.json()["next_fire_at"] is not None
