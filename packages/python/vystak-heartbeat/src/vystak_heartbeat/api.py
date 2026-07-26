"""Scheduler REST API — internal platform network + 127.0.0.1 host publish."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException, Response
from pydantic import ValidationError
from vystak.schema.schedule import ScheduledTask

from vystak_heartbeat.schedule_store import NameCollisionError


class TaskIn(ScheduledTask):
    agent: str          # agent canonical_name
    created_by: str = "api"


def _out(rec) -> dict:
    return {
        "id": rec.id, "agent": rec.agent_canonical, "name": rec.task.name,
        "source": rec.source, "status": rec.status, "created_by": rec.created_by,
        "next_fire_at": rec.next_fire_at.isoformat() if rec.next_fire_at else None,
        "last_fire_at": rec.last_fire_at.isoformat() if rec.last_fire_at else None,
        "last_result": rec.last_result,
        "task": rec.task.model_dump(mode="json"),
    }


def build_api(store, scheduler) -> FastAPI:
    app = FastAPI(title="vystak-scheduler")

    @app.get("/healthz")
    async def healthz():
        return {"status": "ok"}

    @app.get("/tasks")
    async def list_tasks(agent: str | None = None, source: str | None = None,
                         status: str | None = None):
        recs = await store.list(agent=agent, source=source, status=status)
        return {"tasks": [_out(r) for r in recs]}

    @app.post("/tasks", status_code=201)
    async def create_task(body: TaskIn):
        task = ScheduledTask.model_validate(
            body.model_dump(exclude={"agent", "created_by"}))
        try:
            rec = await store.create_runtime(body.agent, task,
                                             created_by=body.created_by)
        except NameCollisionError as e:
            raise HTTPException(409, str(e)) from e
        scheduler.wake()
        return _out(rec)

    @app.get("/tasks/{task_id}")
    async def get_task(task_id: str):
        rec = await store.get(task_id)
        if rec is None:
            raise HTTPException(404, "task not found")
        return _out(rec)

    @app.patch("/tasks/{task_id}")
    async def patch_task(task_id: str, patch: dict):
        try:
            rec = await store.update_runtime(task_id, patch)
        except KeyError:
            raise HTTPException(404, "task not found") from None
        except PermissionError:
            raise HTTPException(
                409, "declarative task — change the YAML definition and re-apply"
            ) from None
        except ValidationError as e:
            raise HTTPException(422, str(e)) from None
        scheduler.wake()
        return _out(rec)

    @app.delete("/tasks/{task_id}", status_code=204)
    async def delete_task(task_id: str):
        try:
            await store.cancel_runtime(task_id)
        except KeyError:
            raise HTTPException(404, "task not found") from None
        except PermissionError:
            raise HTTPException(
                409, "declarative task — change the YAML definition and re-apply"
            ) from None
        scheduler.wake()
        return Response(status_code=204)

    return app
