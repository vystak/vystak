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
        from vystak_channel_slack import commands, welcome
        from vystak_channel_slack.inviters import InviterStore

        self._bot_token = os.environ["SLACK_BOT_TOKEN"]
        self._app_token = os.environ["SLACK_APP_TOKEN"]
        self._app = AsyncApp(token=self._bot_token)

        inviter_path = self.config.get("state", {}).get("path", "/data/channel.db")
        self._inviters = InviterStore(inviter_path)

        welcome.register(self._app, self.config, self.store, self._inviters)
        commands.register(self._app, self.config, self.store, self._inviters)
        # Thread routing is handled by ChannelRuntime.resolve_route + authorize;
        # the deleted threads.route_thread_message helper is now redundant.

        # Wrap each Slack event in a manual OTel span. Slack uses Socket Mode
        # (WebSocket via slack_bolt), not FastAPI HTTP, so FastAPIInstrumentor
        # never creates a root span for incoming events. Without a parent span,
        # `inject()` in NatsAgentClient writes an empty traceparent and
        # downstream agent traces become disconnected. Manual wrap fixes that —
        # the slack.* span is the trace root, traceparent propagates from there.
        try:
            from opentelemetry import trace as _otel_trace

            _tracer = _otel_trace.get_tracer("vystak.channel.slack")
            _OTEL_AVAILABLE = True
        except ImportError:  # pragma: no cover
            _tracer = None
            _OTEL_AVAILABLE = False

        @self._app.event("message")
        async def _on_message(event, say):  # noqa: ARG001
            if _OTEL_AVAILABLE:
                with _tracer.start_as_current_span(
                    "slack.message", kind=_otel_trace.SpanKind.SERVER
                ) as span:
                    span.set_attribute("messaging.system", "slack")
                    span.set_attribute("messaging.operation", "receive")
                    span.set_attribute("slack.event_type", "message")
                    await self.handle_event({"type": "message", "event": event, "say": say})
            else:
                await self.handle_event({"type": "message", "event": event, "say": say})

        @self._app.event("app_mention")
        async def _on_mention(event, say):  # noqa: ARG001
            if _OTEL_AVAILABLE:
                with _tracer.start_as_current_span(
                    "slack.app_mention", kind=_otel_trace.SpanKind.SERVER
                ) as span:
                    span.set_attribute("messaging.system", "slack")
                    span.set_attribute("messaging.operation", "receive")
                    span.set_attribute("slack.event_type", "app_mention")
                    await self.handle_event(
                        {"type": "app_mention", "event": event, "say": say}
                    )
            else:
                await self.handle_event(
                    {"type": "app_mention", "event": event, "say": say}
                )

        self._handler = AsyncSocketModeHandler(self._app, self._app_token)
        await self._start_heartbeats()
        await self._handler.start_async()

    async def stop(self) -> None:
        await self._stop_heartbeats()
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

    async def authorize(self, event: InboundEvent) -> bool:
        """Slack-specific authorize.

        Rules:
          * Bots / dm_policy=disabled / allowlist filter — base behavior.
          * DMs always pass.
          * Explicit @-mentions always pass.
          * Thread replies: pass only when the bot was previously involved
            (i.e. a thread_binding row exists for this thread). Without
            prior involvement, the user must @-mention to start the
            conversation. Honors `thread.require_explicit_mention=True`
            as an additional opt-in to require mention on every reply.
          * Top-level guild messages without mention — gated by require_mention.
        """
        is_bot = bool(event.metadata.get("is_bot"))
        if is_bot and not self.config.get("allow_bots", False):
            return False
        policy = (
            self.config.get("dm_policy") if event.is_dm
            else self.config.get("group_policy")
        )
        if policy == "disabled":
            return False
        if policy == "allowlist" and event.user_id not in self.config.get(
            "allow_from", [],
        ):
            return False

        if event.is_dm or event.mentions_bot:
            return True

        if event.metadata.get("thread_ts"):
            if self.config.get("thread", {}).get("require_explicit_mention", False):
                return False
            # Bot must have been mentioned (responded to) earlier in this
            # thread for follow-up messages to qualify. Use the persisted
            # thread_binding as evidence of prior involvement.
            if event.thread_id is None:
                return False
            bound = await self.store.get_thread_binding(
                self.channel_type, event.scope_id, event.thread_id,
            )
            if bound:
                return True
            # Fall back to the channel-pinned binding (`/vystak route`).
            channel_tid = await self.channel_binding_thread_id(event)
            if channel_tid is not None and channel_tid != event.thread_id:
                bound = await self.store.get_thread_binding(
                    self.channel_type, event.scope_id, channel_tid,
                )
                if bound:
                    return True
            return False

        return not self.config.get("require_mention", True)

    async def _set_assistant_status(
        self,
        channel_id: str,
        thread_ts: str,
        status: str,
    ) -> None:
        """Show the live status indicator under the bot's avatar.

        Uses `assistant.threads.setStatus` — Slack's official method for the
        "AI is typing…" UX. Requires:
          * The app has "Agents & AI Apps" enabled in app config.
          * The bot has the `assistant.threads:write` OAuth scope.

        Calls fail silently if the app isn't configured as an Assistant app
        (the API returns a `not_an_assistant_thread` / similar error). The
        warning is logged once per runtime to avoid log spam.
        """
        if self._app is None:
            return
        try:
            await self._app.client.api_call(
                "assistant.threads.setStatus",
                params={
                    "channel_id": channel_id,
                    "thread_ts": thread_ts,
                    "status": status,
                },
            )
        except Exception as exc:  # noqa: BLE001
            if not getattr(self, "_assistant_status_unsupported", False):
                logger.warning(
                    "assistant.threads.setStatus failed (enable 'Agents & AI Apps' "
                    "+ assistant.threads:write scope on the Slack app): %s",
                    exc,
                )
                # Throttle — only warn once.
                self._assistant_status_unsupported = True

    @staticmethod
    def _resolve_assistant_thread_ts(event: InboundEvent) -> str | None:
        """Status applies to a thread; root message ts works as the thread root."""
        return (
            event.metadata.get("thread_ts")
            or event.metadata.get("ts")
        )

    async def before_call(self, event: InboundEvent, route: str) -> None:
        """Show 'Thinking…' as the assistant typing indicator."""
        if self.agent_protocol != "a2a-stream":
            return
        channel_id = event.metadata.get("channel_id")
        thread_ts = self._resolve_assistant_thread_ts(event)
        if not channel_id or not thread_ts:
            return
        await self._set_assistant_status(channel_id, thread_ts, "is thinking…")

    async def on_chunk(self, event: InboundEvent, route: str, chunk) -> None:  # noqa: ANN001
        """Surface tool activity by updating the assistant typing status."""
        channel_id = event.metadata.get("channel_id")
        thread_ts = self._resolve_assistant_thread_ts(event)
        if not channel_id or not thread_ts:
            return
        if chunk.type == "tool_call":
            tool = chunk.tool_name or "tool"
            await self._set_assistant_status(
                channel_id, thread_ts, f"is calling `{tool}`…",
            )
        elif chunk.type == "tool_result":
            await self._set_assistant_status(channel_id, thread_ts, "is thinking…")

    async def post_reply(
        self, event: InboundEvent, route: str, reply: AgentReply
    ) -> None:
        # Heartbeat-synthesized events have no Slack `say` callable in
        # metadata. Use the bot's web client directly: post to the channel
        # named in `event.scope_id` (the `target_thread` from heartbeat
        # config — a Slack channel id). No threading.
        if event.metadata.get("heartbeat") and self._app is not None:
            await self._app.client.chat_postMessage(
                channel=event.scope_id,
                text=reply.text,
            )
            return

        # Clear the assistant typing status once the reply is ready.
        channel_id = event.metadata.get("channel_id")
        thread_ts = self._resolve_assistant_thread_ts(event)
        if channel_id and thread_ts:
            await self._set_assistant_status(channel_id, thread_ts, "")

        say = event.metadata.get("say")
        if say is None:
            logger.warning("no `say` callable in event metadata; cannot post reply")
            return
        post_thread_ts = event.metadata.get("thread_ts") or event.metadata.get("ts")
        kwargs: dict[str, Any] = {"text": reply.text}
        if post_thread_ts:
            kwargs["thread_ts"] = post_thread_ts
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
