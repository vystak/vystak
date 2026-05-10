"""DiscordChannelRuntime — gateway-mode bot dispatching into ChannelRuntime."""

from __future__ import annotations

import logging
import os
from typing import Any

import discord
from vystak_channel_runtime.runtime import ChannelRuntime
from vystak_channel_runtime.types import (
    AgentCallError,
    AgentReply,
    InboundEvent,
    Message,
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
        from discord import app_commands

        from vystak_channel_discord import commands as cmd
        from vystak_channel_discord.welcome import (
            auto_bind_single_agent,
            render_welcome,
        )

        self._token = os.environ["DISCORD_BOT_TOKEN"]
        intents = discord.Intents.none()
        intents.guilds = True
        intents.guild_messages = True
        intents.dm_messages = True
        intents.message_content = True

        runtime = self
        register_slash = bool(self.config.get("register_slash_commands", True))

        class _VystakClient(discord.Client):
            """discord.Client subclass; setup_hook runs after login but before
            the gateway connection completes. This is the canonical place to
            call CommandTree.sync() — the bot must be authenticated."""

            async def setup_hook(self_inner) -> None:  # noqa: N805
                if not register_slash:
                    return
                tree = app_commands.CommandTree(self_inner)
                self_inner.tree = tree

                @tree.command(
                    name="vystak-route",
                    description="Bind this channel to an agent",
                )
                async def _route(interaction, agent: str):  # noqa: ANN001
                    scope_id = runtime._scope_id_from_interaction(interaction)
                    thread_id = f"{scope_id}:"
                    msg = await cmd.handle_route(
                        runtime.store, scope_id, thread_id, agent,
                    )
                    await interaction.response.send_message(msg, ephemeral=True)

                @tree.command(
                    name="vystak-unroute", description="Remove channel routing",
                )
                async def _unroute(interaction):  # noqa: ANN001
                    scope_id = runtime._scope_id_from_interaction(interaction)
                    thread_id = f"{scope_id}:"
                    msg = await cmd.handle_unroute(
                        runtime.store, scope_id, thread_id,
                    )
                    await interaction.response.send_message(msg, ephemeral=True)

                @tree.command(
                    name="vystak-prefer",
                    description="Set DM/per-scope preference",
                )
                async def _prefer(interaction, agent: str):  # noqa: ANN001
                    scope_id = runtime._scope_id_from_interaction(interaction)
                    msg = await cmd.handle_prefer(runtime.store, scope_id, agent)
                    await interaction.response.send_message(msg, ephemeral=True)

                @tree.command(
                    name="vystak-unprefer", description="Remove preference",
                )
                async def _unprefer(interaction):  # noqa: ANN001
                    scope_id = runtime._scope_id_from_interaction(interaction)
                    msg = await cmd.handle_unprefer(runtime.store, scope_id)
                    await interaction.response.send_message(msg, ephemeral=True)

                @tree.command(
                    name="vystak-status", description="Show current routing",
                )
                async def _status(interaction):  # noqa: ANN001
                    scope_id = runtime._scope_id_from_interaction(interaction)
                    msg = await cmd.handle_status(runtime.store, scope_id)
                    await interaction.response.send_message(msg, ephemeral=True)

                await tree.sync()

        self._client = _VystakClient(intents=intents)

        @self._client.event
        async def on_ready():  # noqa: ARG001
            logger.info("discord client connected as %s", self._client.user)

        @self._client.event
        async def on_message(message: discord.Message):
            await self.handle_event({"kind": "message", "message": message})

        @self._client.event
        async def on_interaction(interaction: discord.Interaction):
            await self.handle_event(
                {"kind": "interaction", "interaction": interaction},
            )

        @self._client.event
        async def on_guild_join(guild):  # noqa: ANN001
            scope_id = (
                f"{guild.id}/"
                f"{getattr(getattr(guild, 'system_channel', None), 'id', '0')}"
            )
            await auto_bind_single_agent(
                self.store, scope_id, self.config.get("agents", []),
            )
            text = render_welcome(
                self.config.get("welcome_message"),
                self.config.get("agents", []),
            )
            sys_chan = getattr(guild, "system_channel", None)
            if sys_chan is not None:
                try:
                    await sys_chan.send(text)
                except Exception:  # noqa: BLE001
                    logger.warning("welcome send failed", exc_info=True)

        await self._start_delivery_receiver()
        await self._start_heartbeats()
        await self._client.start(self._token)

    async def stop(self) -> None:
        await self._stop_delivery_receiver()
        await self._stop_heartbeats()
        if self._client is not None:
            await self._client.close()

    def parse_event(self, raw_event: Any) -> InboundEvent:
        from vystak.schema.common import ChannelType

        from vystak_channel_discord.threads import (
            is_forum_channel,
            is_thread_channel,
        )

        if raw_event.get("kind") != "message":
            raise SkipEvent("not a message")
        msg = raw_event["message"]

        bot_user = getattr(self, "_bot_user", None) or (
            self._client.user if self._client is not None else None
        )
        if bot_user is not None and msg.author.id == bot_user.id:
            raise SkipEvent("own message")

        chan_type = getattr(msg.channel, "type", None)
        # DM detection: accept the discord.ChannelType enum (production) and
        # the "dm"/"private" string literals (test stubs).
        is_dm = chan_type in {"dm", "private"} or (
            getattr(chan_type, "name", None) in {"private", "group"}
        )
        if is_dm:
            scope_id = f"dm/{msg.author.id}"
        else:
            guild_id = getattr(getattr(msg, "guild", None), "id", "?")
            scope_id = f"{guild_id}/{msg.channel.id}"

        if getattr(msg, "thread", None) is not None:
            thread_id = str(msg.thread.id)
        elif is_thread_channel(chan_type) or is_forum_channel(chan_type):
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

    async def authorize(self, event: InboundEvent) -> bool:
        from vystak_channel_discord.threads import (
            is_forum_channel,
            is_thread_channel,
            should_respond_in_thread,
        )
        if not await super().authorize(event):
            return False
        chan_type = event.metadata.get("channel_type")
        is_in_thread = is_thread_channel(chan_type) or is_forum_channel(chan_type) or (
            event.metadata.get("raw_message") is not None
            and getattr(event.metadata["raw_message"], "thread", None) is not None
        )
        require_mention = (
            self.config.get("thread", {}).get("require_explicit_mention", False)
        )
        return should_respond_in_thread(
            require_explicit_mention=require_mention,
            mentions_bot=event.mentions_bot,
            is_in_thread=is_in_thread,
        )

    async def before_call(self, event: InboundEvent, route: str) -> None:
        """Start Discord's typing indicator for streaming turns.

        `channel.typing()` is an async context manager that sends an initial
        typing event and refreshes it every ~5s for the manager's lifetime.
        We hold the manager open across the streaming turn and exit it in
        post_reply.
        """
        if self.agent_protocol != "a2a-stream":
            return
        msg = event.metadata.get("raw_message")
        if msg is None:
            return
        try:
            typing_ctx = msg.channel.typing()
            await typing_ctx.__aenter__()
            event.metadata["_typing_ctx"] = typing_ctx
        except Exception as exc:  # noqa: BLE001
            logger.warning("failed to start typing indicator: %s", exc)

    async def post_reply(
        self, event: InboundEvent, route: str, reply: AgentReply
    ) -> None:
        # Heartbeat-synthesized events have no raw discord.Message in
        # metadata. Resolve the channel by id (`event.scope_id` carries
        # the Discord channel id from the heartbeat's `target_thread`)
        # and send via the client directly.
        if event.metadata.get("heartbeat") and self._client is not None:
            try:
                channel = self._client.get_channel(int(event.scope_id))
                if channel is None:
                    channel = await self._client.fetch_channel(int(event.scope_id))
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "heartbeat: could not resolve discord channel %s: %s",
                    event.scope_id, exc,
                )
                return
            text = reply.text or ""
            for chunk in _chunk(text, MAX_DISCORD_MESSAGE_CHARS):
                await channel.send(chunk)
            return

        # Stop the typing indicator before posting the reply.
        typing_ctx = event.metadata.pop("_typing_ctx", None)
        if typing_ctx is not None:
            import contextlib

            with contextlib.suppress(Exception):
                await typing_ctx.__aexit__(None, None, None)

        msg = event.metadata.get("raw_message")
        if msg is None:
            logger.warning("no raw_message; cannot post reply")
            return
        text = reply.text or ""
        for chunk in _chunk(text, MAX_DISCORD_MESSAGE_CHARS):
            await msg.channel.send(chunk)

    async def deliver_message(self, thread_id: str, text: str, metadata: dict) -> None:
        if self._client is None:
            logger.warning("discord delivery: client not initialized")
            return
        channel = self._client.get_channel(int(thread_id))
        if channel is None:
            channel = await self._client.fetch_channel(int(thread_id))
        # _chunk and MAX_DISCORD_MESSAGE_CHARS are existing module-level helpers
        for chunk in _chunk(text or "", MAX_DISCORD_MESSAGE_CHARS):
            await channel.send(chunk)

    async def fetch_history(self, event: InboundEvent) -> list[Message]:
        from vystak_channel_discord.threads import (
            is_forum_channel,
            is_thread_channel,
        )

        msg = event.metadata.get("raw_message")
        if msg is None:
            return []
        chan_type = getattr(msg.channel, "type", None)
        in_thread = is_thread_channel(chan_type) or is_forum_channel(chan_type)
        has_thread = getattr(msg, "thread", None) is not None
        if not in_thread and not has_thread:
            return []
        limit = self.config.get("thread", {}).get("initial_history_limit", 20)
        out: list[Message] = []
        bot_id = getattr(getattr(self, "_bot_user", None), "id", None)
        async for hist in msg.channel.history(limit=limit):
            role = "assistant" if getattr(hist.author, "id", None) == bot_id else "user"
            out.append(Message(role=role, content=hist.content or ""))
        return out

    async def on_no_route(self, event: InboundEvent) -> None:
        text = self.config.get("no_route_message")
        if not text:
            return
        msg = event.metadata.get("raw_message")
        if msg is None:
            return
        try:
            await msg.channel.send(text)
        except Exception:  # noqa: BLE001
            logger.warning("on_no_route send failed", exc_info=True)

    async def on_agent_error(
        self, event: InboundEvent, route: str, exc: AgentCallError
    ) -> None:
        msg = event.metadata.get("raw_message")
        if msg is None:
            return
        try:
            await msg.channel.send(f"Agent error ({route}): {str(exc)[:300]}")
        except Exception:  # noqa: BLE001
            logger.warning("on_agent_error send failed", exc_info=True)

    @staticmethod
    def _scope_id_from_interaction(interaction) -> str:  # noqa: ANN001
        guild_id = getattr(interaction, "guild_id", None)
        channel_id = getattr(interaction, "channel_id", None)
        if guild_id is None:
            user_id = getattr(getattr(interaction, "user", None), "id", "?")
            return f"dm/{user_id}"
        return f"{guild_id}/{channel_id}"


def _chunk(text: str, size: int) -> list[str]:
    if not text:
        return [""]
    return [text[i : i + size] for i in range(0, len(text), size)]
