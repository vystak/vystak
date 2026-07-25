"""Admin user-management routes."""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from vystak_channel_panel.models import PanelUser

if TYPE_CHECKING:
    from vystak_channel_panel.runtime import PanelChannelRuntime


class UserCreateIn(BaseModel):
    email: str
    role: str = "member"


class UserPatchIn(BaseModel):
    role: str | None = None
    status: str | None = None


def build_users_router(rt: PanelChannelRuntime, admin_user) -> APIRouter:
    router = APIRouter(prefix="/api/users")

    @router.get("")
    async def list_users(_: PanelUser = Depends(admin_user)) -> dict:
        return {"users": [u.model_dump() for u in await rt.panel_store.list_users()]}

    @router.post("")
    async def add_user(
        body: UserCreateIn, _: PanelUser = Depends(admin_user)
    ) -> dict:
        if body.role not in ("admin", "member"):
            raise HTTPException(status_code=422, detail="invalid role")
        if await rt.panel_store.get_user_by_email(body.email) is not None:
            raise HTTPException(status_code=409, detail="user already exists")
        try:
            user = await rt.panel_store.create_user(body.email, role=body.role)
        except sqlite3.IntegrityError:
            raise HTTPException(
                status_code=409, detail="user already exists"
            ) from None
        return {"user": user.model_dump()}

    @router.patch("/{user_id}")
    async def patch_user(
        user_id: str, body: UserPatchIn, _: PanelUser = Depends(admin_user)
    ) -> dict:
        if body.role is not None and body.role not in ("admin", "member"):
            raise HTTPException(status_code=422, detail="invalid role")
        if body.status is not None and body.status not in ("active", "deactivated"):
            raise HTTPException(status_code=422, detail="invalid status")
        user = await rt.panel_store.update_user(
            user_id, role=body.role, status=body.status
        )
        if user is None:
            raise HTTPException(status_code=404, detail="unknown user")
        return {"user": user.model_dump()}

    return router
