"""SlackChannelRuntime — runs a slack-bolt Socket Mode handler dispatching to ChannelRuntime."""

from __future__ import annotations

import logging
import os
from typing import Any

from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from slack_bolt.async_app import AsyncApp
from vystak.schema.common import ChannelType
from vystak_channel_runtime.runtime import ChannelRuntime
from vystak_channel_runtime.types import (
    AgentReply,
    InboundEvent,
    SkipEvent,
)

logger = logging.getLogger("vystak.channel.slack")


class SlackChannelRuntime(ChannelRuntime):
    """Slack Socket Mode runtime."""

    def __init__(self, **kw: Any) -> None:
        super().__init__(**kw)
        self._bot_token: str | None = None
        self._app_token: str | None = None
        self._app: AsyncApp | None = None
        self._handler: AsyncSocketModeHandler | None = None

    async def start(self) -> None:
        self._bot_token = os.environ["SLACK_BOT_TOKEN"]
        self._app_token = os.environ["SLACK_APP_TOKEN"]
        self._app = AsyncApp(token=self._bot_token)

        @self._app.event("message")
        async def _on_message(event, say):  # noqa: ARG001
            await self.handle_event({"type": "message", "event": event, "say": say})

        @self._app.event("app_mention")
        async def _on_mention(event, say):  # noqa: ARG001
            await self.handle_event({"type": "app_mention", "event": event, "say": say})

        self._handler = AsyncSocketModeHandler(self._app, self._app_token)
        await self._handler.start_async()

    async def stop(self) -> None:
        if self._handler is not None:
            await self._handler.close_async()

    def parse_event(self, raw_event: Any) -> InboundEvent:
        kind = raw_event.get("type")
        ev = raw_event["event"]
        say = raw_event.get("say")

        # Skip our own messages and subtype-noisy events.
        if ev.get("user") == getattr(self, "_bot_user_id", None):
            raise SkipEvent("own message")
        subtype = ev.get("subtype")
        if subtype in {"message_changed", "message_deleted", "channel_join"}:
            raise SkipEvent(f"subtype {subtype}")

        team_id = ev.get("team") or ""
        channel_id = ev.get("channel", "")
        thread_ts = ev.get("thread_ts") or ev.get("ts") or ""
        is_dm = ev.get("channel_type") == "im"
        mentions_bot = (
            kind == "app_mention"
            or f"<@{getattr(self, '_bot_user_id', '')}>" in (ev.get("text") or "")
        )
        is_bot = bool(ev.get("bot_id"))

        metadata = {
            "channel_id": channel_id,
            "channel_name": ev.get("channel_name"),
            "ts": ev.get("ts"),
            "thread_ts": ev.get("thread_ts"),
            "is_bot": is_bot,
            "say": say,
            "kind": kind,
        }

        return InboundEvent(
            channel_type=ChannelType.SLACK,
            scope_id=team_id,
            thread_id=f"{channel_id}:{thread_ts}",
            user_id=ev.get("user", ""),
            text=ev.get("text", ""),
            is_dm=is_dm,
            mentions_bot=mentions_bot,
            metadata=metadata,
            raw=raw_event,
        )

    async def post_reply(
        self, event: InboundEvent, route: str, reply: AgentReply
    ) -> None:
        # Real implementation in Task 2.4
        raise NotImplementedError
