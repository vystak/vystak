"""ChatChannelRuntime — OpenAI-compatible synchronous routing into ChannelRuntime."""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from vystak.schema.common import ChannelType
from vystak_channel_runtime.runtime import ChannelRuntime
from vystak_channel_runtime.types import (
    AgentReply,
    InboundEvent,
    SkipEvent,
)

logger = logging.getLogger("vystak.channel.chat")


class _ChatMessage(BaseModel):
    role: str
    content: str


class _ChatRequest(BaseModel):
    model: str
    messages: list[_ChatMessage]
    user: str | None = None


class ChatChannelRuntime(ChannelRuntime):
    """OpenAI-compatible chat endpoint backed by ChannelRuntime."""

    def __init__(self, **kw: Any) -> None:
        super().__init__(**kw)
        self._app: FastAPI | None = None
        self._server: uvicorn.Server | None = None
        # Held by post_reply to bridge the sync HTTP response.
        self._pending_reply: dict[str, AgentReply] = {}

    def parse_event(self, raw_event: Any) -> InboundEvent:
        req: _ChatRequest = raw_event["request"]
        request_id = raw_event["request_id"]
        if not req.messages:
            raise SkipEvent("empty messages")
        last = req.messages[-1]
        agent = req.model.removeprefix("vystak/") or self.config.get("default_agent") or ""
        return InboundEvent(
            channel_type=ChannelType.CHAT,
            scope_id=req.user or "anon",
            thread_id=request_id,
            user_id=req.user or "anon",
            text=last.content,
            is_dm=True,
            mentions_bot=True,
            metadata={"requested_agent": agent, "request_id": request_id},
            raw=req,
        )

    async def resolve_route(self, event: InboundEvent) -> str | None:
        explicit = event.metadata.get("requested_agent")
        if explicit:
            return explicit
        return await super().resolve_route(event)

    async def post_reply(
        self, event: InboundEvent, route: str, reply: AgentReply
    ) -> None:
        rid = event.metadata["request_id"]
        self._pending_reply[rid] = reply

    async def start(self) -> None:
        self._app = build_app(self)
        port = int(self.config.get("port", 8080))
        cfg = uvicorn.Config(self._app, host="0.0.0.0", port=port, log_level="info")
        self._server = uvicorn.Server(cfg)
        await self._server.serve()

    async def stop(self) -> None:
        if self._server is not None:
            self._server.should_exit = True


def build_app(rt: ChatChannelRuntime) -> FastAPI:
    app = FastAPI(title="vystak-channel-chat")

    @app.post("/v1/chat/completions")
    async def completions(req: _ChatRequest) -> dict:
        rid = str(uuid.uuid4())
        await rt.handle_event({"request": req, "request_id": rid})
        reply = rt._pending_reply.pop(rid, None)
        if reply is None:
            raise HTTPException(status_code=502, detail="no reply (route missing or agent error)")
        return {
            "id": rid,
            "object": "chat.completion",
            "created": int(time.time()),
            "model": req.model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": reply.text},
                    "finish_reason": reply.finish_reason or "stop",
                }
            ],
        }

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    return app
