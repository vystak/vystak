"""Approval-decision route — resolves a parked HITL tool-approval turn.

Split out of routes_messages.py: the resume path (NATS `resume_detached` vs
the HTTP checkpoint/resume dance) is a separate concern from the streaming
POST/GET routes there, and keeping it here matches those files' size.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from vystak_channel_panel.models import PanelUser
from vystak_channel_panel.responses_client import agent_base_url
from vystak_channel_panel.routes_conversations import require_conversation_access
from vystak_channel_panel.turn_stream import TurnAccumulator

if TYPE_CHECKING:
    from vystak_channel_panel.models import Conversation
    from vystak_channel_panel.runtime import PanelChannelRuntime

logger = logging.getLogger("vystak.channel.panel.approvals")


class ApprovalIn(BaseModel):
    turn_id: str
    approved: bool
    note: str | None = None


def build_approvals_router(rt: PanelChannelRuntime, current_user) -> APIRouter:
    router = APIRouter(prefix="/api/conversations")

    @router.post("/{conv_id}/approval")
    async def post_approval(
        conv_id: str, body: ApprovalIn, user: PanelUser = Depends(current_user)
    ) -> dict:
        conv = await require_conversation_access(rt, conv_id, user)
        if conv.active_turn_id != body.turn_id:
            raise HTTPException(
                status_code=422,
                detail="turn is not this conversation's active turn",
            )
        decision = {
            "approved": body.approved,
            "decided_by": user.email,
            "note": body.note,
        }
        if rt.nats_client is not None:
            try:
                await rt.nats_client.resume_detached(
                    conv.agent_name, body.turn_id, decision
                )
            except RuntimeError as e:
                raise HTTPException(status_code=409, detail=str(e)) from e
        else:
            route_entry = rt.routes.get(conv.agent_name)
            if route_entry is None:
                raise HTTPException(
                    status_code=503, detail=f"agent not routed: {conv.agent_name}"
                )
            base_url = agent_base_url(route_entry)
            _spawn_resume_http(rt, conv, conv_id, base_url, decision)
        return {"ok": True}

    return router


def _spawn_resume_http(
    rt: PanelChannelRuntime,
    conv: Conversation,
    conv_id: str,
    base_url: str,
    decision: dict,
) -> asyncio.Task:
    """HTTP-transport resume: POST /v1/_vystak/resume and consume its SSE
    stream through a fresh accumulator, persisting the continuation the same
    way `post_message` does. Fire-and-forget — the browser learns about the
    continuation on its next `GET .../messages` poll or reconnect, same as
    any other background persister in this codebase.

    Registered in `rt.turn_tasks` (same dict `spawn_persister` uses, keyed
    by turn_id — no collision, HTTP transport has no NATS persisters) so the
    event loop's weak reference to bare `asyncio.create_task()` results
    can't garbage-collect this mid-flight and silently drop the
    continuation."""
    thread_id = conv.last_response_id or ""
    turn_id = conv.active_turn_id

    async def _run() -> None:
        acc = TurnAccumulator()
        done_seen = False

        async def persist(response_id: str | None):
            return await rt.panel_store.add_message(
                conv_id, "assistant", acc.content,
                response_id=response_id,
                parts=acc.parts(),
            )

        try:
            async for ev in rt.responses_client.resume_stream(
                base_url, thread_id, decision
            ):
                if ev.type in ("token", "tool_call", "tool_result"):
                    acc.feed(ev)
                elif ev.type == "done":
                    done_seen = True
                    await persist(ev.response_id or None)
                    if ev.response_id:
                        await rt.panel_store.update_conversation(
                            conv_id, last_response_id=ev.response_id
                        )
                elif ev.type == "error":
                    done_seen = True
                    if acc.has_output:
                        await persist(None)
            if not done_seen and acc.has_output:
                await persist(None)
        except Exception:  # noqa: BLE001 — background task must not raise
            logger.exception("resume_http failed conv=%s", conv_id)
            if acc.has_output:
                try:
                    await persist(None)
                except Exception:  # noqa: BLE001 — last line of defence
                    logger.exception(
                        "failed to persist partial resume text for conv=%s",
                        conv_id,
                    )
        finally:
            if turn_id is not None:
                await rt.panel_store.clear_active_turn(conv_id, turn_id)
                rt.turn_tasks.pop(turn_id, None)

    task = asyncio.create_task(_run())
    if turn_id is not None:
        rt.turn_tasks[turn_id] = task
    return task
