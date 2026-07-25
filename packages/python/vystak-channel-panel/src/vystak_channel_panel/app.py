"""FastAPI app for the panel channel — REST + SSE API."""

from __future__ import annotations

import os
import secrets as py_secrets
from typing import TYPE_CHECKING

from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel
from vystak_channel_runtime.telemetry import instrument_app

from vystak_channel_panel.models import PanelUser

if TYPE_CHECKING:
    from vystak_channel_panel.runtime import PanelChannelRuntime


class SetupIn(BaseModel):
    email: str
    name: str = ""
    image: str = ""


def build_app(rt: PanelChannelRuntime) -> FastAPI:
    app = FastAPI(title="vystak-channel-panel")
    instrument_app(
        app,
        service_name=os.environ.get("OTEL_SERVICE_NAME", "vystak-channel-panel"),
    )

    def service_auth(request: Request) -> None:
        expected = os.environ.get("PANEL_SERVICE_TOKEN", "")
        supplied = request.headers.get("authorization", "")
        token = supplied.removeprefix("Bearer ").strip()
        if not expected or not py_secrets.compare_digest(token, expected):
            raise HTTPException(status_code=401, detail="invalid service token")

    def acting_email(request: Request) -> str:
        email = request.headers.get("x-panel-user", "").strip().lower()
        if not email:
            raise HTTPException(status_code=401, detail="missing X-Panel-User")
        return email

    async def current_user(
        request: Request, _: None = Depends(service_auth)
    ) -> PanelUser:
        user = await rt.panel_store.get_user_by_email(acting_email(request))
        if user is None or user.status != "active":
            raise HTTPException(status_code=403, detail="not invited")
        return user

    async def admin_user(user: PanelUser = Depends(current_user)) -> PanelUser:
        if user.role != "admin":
            raise HTTPException(status_code=403, detail="admin only")
        return user

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    @app.get("/api/bootstrap")
    async def bootstrap(
        request: Request, _: None = Depends(service_auth)
    ) -> dict:
        email = acting_email(request)
        setup_required = await rt.panel_store.count_users() == 0
        user = await rt.panel_store.get_user_by_email(email)
        if user is not None and user.status != "active":
            user = None
        default_project_id = None
        if user is not None:
            project = await rt.panel_store.ensure_default_project(user.id)
            default_project_id = project.id
        return {
            "setup_required": setup_required,
            "user": user.model_dump() if user else None,
            "agents": list(rt.routes.keys()),
            "default_project_id": default_project_id,
        }

    @app.post("/api/setup")
    async def setup(body: SetupIn, _: None = Depends(service_auth)) -> dict:
        if await rt.panel_store.count_users() > 0:
            raise HTTPException(status_code=409, detail="setup already completed")
        user = await rt.panel_store.create_user(
            body.email, name=body.name, image=body.image, role="admin"
        )
        await rt.panel_store.ensure_default_project(user.id)
        await rt.panel_store.set_setting("setup_complete", "1")
        return {"user": user.model_dump()}

    from vystak_channel_panel.routes_registry import mount_routes

    mount_routes(app, rt, current_user, admin_user)
    return app
