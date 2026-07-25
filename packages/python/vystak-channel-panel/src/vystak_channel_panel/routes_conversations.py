"""Conversation + message-history routes."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from vystak_channel_panel.models import Conversation, PanelUser
from vystak_channel_panel.routes_projects import require_project_access

if TYPE_CHECKING:
    from vystak_channel_panel.runtime import PanelChannelRuntime


class ConversationCreateIn(BaseModel):
    agent_name: str
    title: str = ""


class ConversationPatchIn(BaseModel):
    title: str


async def require_conversation_access(
    rt: PanelChannelRuntime, conv_id: str, user: PanelUser
) -> Conversation:
    conv = await rt.panel_store.get_conversation(conv_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="unknown conversation")
    await require_project_access(rt, conv.project_id, user)
    return conv


def build_conversations_router(
    rt: PanelChannelRuntime, current_user
) -> APIRouter:
    router = APIRouter(prefix="/api")

    @router.get("/projects/{project_id}/conversations")
    async def list_conversations(
        project_id: str, user: PanelUser = Depends(current_user)
    ) -> dict:
        await require_project_access(rt, project_id, user)
        convs = await rt.panel_store.list_conversations(project_id)
        return {"conversations": [c.model_dump() for c in convs]}

    @router.post("/projects/{project_id}/conversations")
    async def create_conversation(
        project_id: str,
        body: ConversationCreateIn,
        user: PanelUser = Depends(current_user),
    ) -> dict:
        await require_project_access(rt, project_id, user)
        if body.agent_name not in rt.routes:
            raise HTTPException(
                status_code=422,
                detail=f"unknown agent: {body.agent_name}",
            )
        conv = await rt.panel_store.create_conversation(
            project_id, user.id, body.agent_name, title=body.title
        )
        return {"conversation": conv.model_dump()}

    @router.patch("/conversations/{conv_id}")
    async def rename_conversation(
        conv_id: str,
        body: ConversationPatchIn,
        user: PanelUser = Depends(current_user),
    ) -> dict:
        await require_conversation_access(rt, conv_id, user)
        conv = await rt.panel_store.update_conversation(conv_id, title=body.title)
        if conv is None:
            raise HTTPException(status_code=404, detail="unknown conversation")
        return {"conversation": conv.model_dump()}

    @router.delete("/conversations/{conv_id}", status_code=204)
    async def delete_conversation(
        conv_id: str, user: PanelUser = Depends(current_user)
    ) -> Response:
        await require_conversation_access(rt, conv_id, user)
        await rt.panel_store.delete_conversation(conv_id)
        return Response(status_code=204)

    @router.get("/conversations/{conv_id}/messages")
    async def list_messages(
        conv_id: str, user: PanelUser = Depends(current_user)
    ) -> dict:
        await require_conversation_access(rt, conv_id, user)
        msgs = await rt.panel_store.list_messages(conv_id)
        return {"messages": [m.model_dump() for m in msgs]}

    return router
