"""SlackChannelRuntime — runs a slack-bolt Socket Mode handler dispatching to ChannelRuntime."""

from __future__ import annotations

import logging
import os
from typing import Any

from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from slack_bolt.async_app import AsyncApp
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
        # Real implementation in Task 2.3
        raise SkipEvent("not implemented yet")

    async def post_reply(
        self, event: InboundEvent, route: str, reply: AgentReply
    ) -> None:
        # Real implementation in Task 2.4
        raise NotImplementedError
