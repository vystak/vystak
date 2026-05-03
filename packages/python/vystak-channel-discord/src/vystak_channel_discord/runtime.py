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
        from vystak.schema.common import ChannelType

        if raw_event.get("kind") != "message":
            raise SkipEvent("not a message")
        msg = raw_event["message"]

        bot_user = getattr(self, "_bot_user", None) or (
            self._client.user if self._client is not None else None
        )
        if bot_user is not None and msg.author.id == bot_user.id:
            raise SkipEvent("own message")

        is_dm = getattr(msg.channel, "type", None) in {"dm", "private", discord.ChannelType.private}
        if is_dm:
            scope_id = f"dm/{msg.author.id}"
        else:
            guild_id = getattr(getattr(msg, "guild", None), "id", "?")
            scope_id = f"{guild_id}/{msg.channel.id}"

        if getattr(msg, "thread", None) is not None:
            thread_id = str(msg.thread.id)
        elif getattr(msg.channel, "type", None) in {"thread", "forum"}:
            thread_id = str(msg.channel.id)
        else:
            thread_id = str(msg.id)

        mentions_bot = False
        if bot_user is not None:
            mentions_bot = any(m.id == bot_user.id for m in (msg.mentions or []))

        is_bot = bool(getattr(msg.author, "bot", False))

        metadata = {
            "channel_id": str(msg.channel.id),
            "guild_id": str(getattr(getattr(msg, "guild", None), "id", "")),
            "message_id": str(msg.id),
            "channel_type": getattr(msg.channel, "type", None),
            "is_bot": is_bot,
            "raw_message": msg,
        }

        return InboundEvent(
            channel_type=ChannelType.DISCORD,
            scope_id=scope_id,
            thread_id=thread_id,
            user_id=str(msg.author.id),
            text=msg.content or "",
            is_dm=is_dm,
            mentions_bot=mentions_bot,
            metadata=metadata,
            raw=raw_event,
        )

    async def post_reply(
        self, event: InboundEvent, route: str, reply: AgentReply
    ) -> None:
        msg = event.metadata.get("raw_message")
        if msg is None:
            logger.warning("no raw_message; cannot post reply")
            return
        text = reply.text or ""
        for chunk in _chunk(text, MAX_DISCORD_MESSAGE_CHARS):
            await msg.channel.send(chunk)


def _chunk(text: str, size: int) -> list[str]:
    if not text:
        return [""]
    return [text[i : i + size] for i in range(0, len(text), size)]
