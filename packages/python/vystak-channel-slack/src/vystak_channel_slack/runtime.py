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
    Message,
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
        self._inviters: Any = None

    async def start(self) -> None:
        from vystak_channel_slack import commands, threads, welcome
        from vystak_channel_slack.inviters import InviterStore

        self._bot_token = os.environ["SLACK_BOT_TOKEN"]
        self._app_token = os.environ["SLACK_APP_TOKEN"]
        self._app = AsyncApp(token=self._bot_token)

        inviter_path = self.config.get("state", {}).get("path", "/data/channel.db")
        self._inviters = InviterStore(inviter_path)

        welcome.register(self._app, self.config, self.store, self._inviters)
        commands.register(self._app, self.config, self.store, self._inviters)
        threads.register(self._app, self.config, self.store)

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
        if subtype:
            raise SkipEvent(f"subtype {subtype}")

        # Dedup: Slack fires both `message` AND `app_mention` for the same
        # user @-mention in non-DM channels.  Drop the `message` copy —
        # `app_mention` is the canonical event and will be processed instead.
        # DMs never fire `app_mention`, so skip the dedup there.
        bot_uid = getattr(self, "_bot_user_id", None)
        is_dm = ev.get("channel_type") == "im"
        if (
            kind == "message"
            and bot_uid
            and not is_dm
            and f"<@{bot_uid}>" in (ev.get("text") or "")
        ):
            raise SkipEvent("mention handled by app_mention")

        team_id = ev.get("team") or ""
        channel_id = ev.get("channel", "")
        thread_ts = ev.get("thread_ts") or ev.get("ts") or ""
        user_id = ev.get("user", "")
        mentions_bot = (
            kind == "app_mention"
            or f"<@{getattr(self, '_bot_user_id', '')}>" in (ev.get("text") or "")
        )
        is_bot = bool(ev.get("bot_id"))

        # DMs include the user in scope_id so per-user prefs can be looked up
        # by the same key the runtime computes from incoming events.  Guild
        # messages keep team-only scope so channel_overrides + thread bindings
        # (which are workspace-wide) keep their meaning.
        scope_id = f"{team_id}:{user_id}" if is_dm else team_id

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
            scope_id=scope_id,
            thread_id=f"{channel_id}:{thread_ts}",
            user_id=user_id,
            text=ev.get("text", ""),
            is_dm=is_dm,
            mentions_bot=mentions_bot,
            metadata=metadata,
            raw=raw_event,
        )

    async def channel_binding_thread_id(self, event: InboundEvent) -> str | None:
        """Slack's per-channel binding convention: thread_id = `f"{channel_id}:"`.

        Written by `/vystak route` (commands._route).  Read here so per-message
        lookups fall back to the channel-pinned binding when no per-thread
        binding exists.
        """
        channel_id = event.metadata.get("channel_id")
        if not channel_id:
            return None
        return f"{channel_id}:"

    async def post_reply(
        self, event: InboundEvent, route: str, reply: AgentReply
    ) -> None:
        say = event.metadata.get("say")
        if say is None:
            logger.warning("no `say` callable in event metadata; cannot post reply")
            return
        thread_ts = event.metadata.get("thread_ts") or event.metadata.get("ts")
        kwargs: dict[str, Any] = {"text": reply.text}
        if thread_ts:
            kwargs["thread_ts"] = thread_ts
        await say(**kwargs)

    async def fetch_history(self, event: InboundEvent) -> list[Message]:
        thread_ts = event.metadata.get("thread_ts")
        channel_id = event.metadata.get("channel_id")
        if not thread_ts or not channel_id or self._app is None:
            return []
        try:
            client = self._app.client
            limit = self.config.get("thread", {}).get("initial_history_limit", 20)
            resp = await client.conversations_replies(
                channel=channel_id, ts=thread_ts, limit=limit,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("conversations.replies failed: %s", exc)
            return []
        out: list[Message] = []
        bot_user_id = getattr(self, "_bot_user_id", None)
        for msg in resp.get("messages", [])[:-1]:  # exclude the trigger msg itself
            role = "assistant" if msg.get("user") == bot_user_id else "user"
            out.append(Message(role=role, content=msg.get("text", "")))
        return out
