"""Project + membership routes."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from vystak_channel_panel.models import PanelUser, Project

if TYPE_CHECKING:
    from vystak_channel_panel.runtime import PanelChannelRuntime


class ProjectCreateIn(BaseModel):
    name: str


class MemberAddIn(BaseModel):
    email: str


async def require_project_access(
    rt: PanelChannelRuntime, project_id: str, user: PanelUser
) -> Project:
    project = await rt.panel_store.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="unknown project")
    if not await rt.panel_store.user_can_access_project(project_id, user.id):
        raise HTTPException(status_code=403, detail="no access to project")
    return project


async def require_project_owner(
    rt: PanelChannelRuntime, project_id: str, user: PanelUser
) -> Project:
    project = await require_project_access(rt, project_id, user)
    if project.owner_id != user.id:
        raise HTTPException(status_code=403, detail="owner only")
    return project


def build_projects_router(rt: PanelChannelRuntime, current_user) -> APIRouter:
    router = APIRouter(prefix="/api/projects")

    @router.get("")
    async def list_projects(user: PanelUser = Depends(current_user)) -> dict:
        projects = await rt.panel_store.list_projects_for_user(user.id)
        return {"projects": [p.model_dump() for p in projects]}

    @router.post("")
    async def create_project(
        body: ProjectCreateIn, user: PanelUser = Depends(current_user)
    ) -> dict:
        name = body.name.strip()
        if not name:
            raise HTTPException(status_code=422, detail="name required")
        project = await rt.panel_store.create_project(name, user.id)
        return {"project": project.model_dump()}

    @router.delete("/{project_id}", status_code=204)
    async def delete_project(
        project_id: str, user: PanelUser = Depends(current_user)
    ) -> Response:
        project = await require_project_owner(rt, project_id, user)
        if project.is_default:
            raise HTTPException(
                status_code=400, detail="cannot delete default project"
            )
        await rt.panel_store.delete_project(project_id)
        return Response(status_code=204)

    @router.get("/{project_id}/members")
    async def list_members(
        project_id: str, user: PanelUser = Depends(current_user)
    ) -> dict:
        await require_project_access(rt, project_id, user)
        members = await rt.panel_store.list_members(project_id)
        return {"members": [m.model_dump() for m in members]}

    @router.post("/{project_id}/members", status_code=204)
    async def add_member(
        project_id: str, body: MemberAddIn, user: PanelUser = Depends(current_user)
    ) -> Response:
        await require_project_owner(rt, project_id, user)
        member = await rt.panel_store.get_user_by_email(body.email)
        if member is None:
            raise HTTPException(status_code=404, detail="unknown user email")
        await rt.panel_store.add_member(project_id, member.id)
        return Response(status_code=204)

    @router.delete("/{project_id}/members/{user_id}", status_code=204)
    async def remove_member(
        project_id: str, user_id: str, user: PanelUser = Depends(current_user)
    ) -> Response:
        await require_project_owner(rt, project_id, user)
        await rt.panel_store.remove_member(project_id, user_id)
        return Response(status_code=204)

    return router
