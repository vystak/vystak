"""Streaming message route — the panel's core chat surface."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from vystak_channel_panel.models import PanelUser
from vystak_channel_panel.responses_client import agent_base_url
from vystak_channel_panel.routes_conversations import require_conversation_access

if TYPE_CHECKING:
    from vystak_channel_panel.runtime import PanelChannelRuntime

logger = logging.getLogger("vystak.channel.panel.messages")

_TITLE_MAX = 60


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


class MessageIn(BaseModel):
    text: str


def build_messages_router(rt: PanelChannelRuntime, current_user) -> APIRouter:
    router = APIRouter(prefix="/api/conversations")

    @router.post("/{conv_id}/messages")
    async def post_message(
        conv_id: str, body: MessageIn, user: PanelUser = Depends(current_user)
    ) -> StreamingResponse:
        text = body.text.strip()
        if not text:
            raise HTTPException(status_code=422, detail="text required")
        conv = await require_conversation_access(rt, conv_id, user)
        route_entry = rt.routes.get(conv.agent_name)
        if route_entry is None:
            raise HTTPException(
                status_code=503, detail=f"agent not routed: {conv.agent_name}"
            )
        base_url = agent_base_url(route_entry)

        await rt.panel_store.add_message(conv_id, "user", text)
        title = conv.title
        if not title:
            title = text[:_TITLE_MAX]
            await rt.panel_store.update_conversation(conv_id, title=title)

        async def gen():
            parts: list[str] = []
            done_seen = False
            try:
                async for ev in rt.responses_client.stream_message(
                    base_url,
                    text,
                    previous_response_id=conv.last_response_id,
                    user_id=user.id,
                    project_id=conv.project_id,
                ):
                    if ev.type == "token":
                        parts.append(ev.text)
                        yield _sse({"type": "delta", "text": ev.text})
                    elif ev.type == "done":
                        done_seen = True
                        msg = await rt.panel_store.add_message(
                            conv_id, "assistant", "".join(parts),
                            response_id=ev.response_id or None,
                        )
                        # An empty id means the agent's terminal event carried
                        # none; keep the previous one rather than clobbering it
                        # (COALESCE only guards NULL, and "" would silently
                        # start a new agent-side thread on the next turn).
                        if ev.response_id:
                            await rt.panel_store.update_conversation(
                                conv_id, last_response_id=ev.response_id
                            )
                        yield _sse({
                            "type": "done",
                            "message_id": msg.id,
                            "response_id": ev.response_id,
                            "title": title,
                        })
                    elif ev.type == "error":
                        done_seen = True
                        yield _sse({"type": "error", "message": ev.text})
                if not done_seen and parts:
                    # Truncated agent stream: `data: [DONE]` arrived with no
                    # preceding response.completed/failed, so ResponsesClient
                    # yields no terminal event. Persist what we streamed —
                    # otherwise the user watches text appear and finds it gone
                    # on reload. last_response_id is left untouched: no new
                    # agent-side response id was confirmed.
                    msg = await rt.panel_store.add_message(
                        conv_id, "assistant", "".join(parts),
                    )
                    yield _sse({
                        "type": "done",
                        "message_id": msg.id,
                        "response_id": conv.last_response_id or "",
                        "title": title,
                    })
            except Exception as exc:  # noqa: BLE001 — stream must not raise
                logger.exception("panel stream failed for conv=%s", conv_id)
                yield _sse({"type": "error", "message": str(exc)})

        return StreamingResponse(gen(), media_type="text/event-stream")

    return router
