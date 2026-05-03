"""DiscordChannelRuntime — gateway-mode bot dispatching into ChannelRuntime."""

from __future__ import annotations

import logging
import os
from typing import Any

import discord
from vystak_channel_runtime.runtime import ChannelRuntime
from vystak_channel_runtime.types import (
    AgentReply,
    InboundEvent,
    SkipEvent,
)

logger = logging.getLogger("vystak.channel.discord")

MAX_DISCORD_MESSAGE_CHARS = 2000


class DiscordChannelRuntime(ChannelRuntime):
    """Discord gateway runtime."""

    def __init__(self, **kw: Any) -> None:
        super().__init__(**kw)
        self._client: discord.Client | None = None
        self._token: str | None = None

    async def start(self) -> None:
        self._token = os.environ["DISCORD_BOT_TOKEN"]
        intents = discord.Intents.none()
        intents.guilds = True
        intents.guild_messages = True
        intents.dm_messages = True
        intents.message_content = True
        self._client = discord.Client(intents=intents)

        @self._client.event
        async def on_ready():  # noqa: ARG001
            logger.info("discord client connected as %s", self._client.user)

        @self._client.event
        async def on_message(message: discord.Message):
            await self.handle_event({"kind": "message", "message": message})

        @self._client.event
        async def on_interaction(interaction: discord.Interaction):
            await self.handle_event({"kind": "interaction", "interaction": interaction})

        await self._client.start(self._token)

    async def stop(self) -> None:
        if self._client is not None:
            await self._client.close()

    def parse_event(self, raw_event: Any) -> InboundEvent:
        # Real impl in Task 4.3
        raise SkipEvent("not implemented yet")

    async def post_reply(
        self, event: InboundEvent, route: str, reply: AgentReply
    ) -> None:
        # Real impl in Task 4.4
        raise NotImplementedError
