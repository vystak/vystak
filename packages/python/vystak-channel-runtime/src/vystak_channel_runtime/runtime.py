"""ChannelRuntime — template-method base for all channel containers."""

from __future__ import annotations

import json
import logging
import os
from abc import ABC, abstractmethod
from typing import Any

from vystak.schema.heartbeat import Heartbeat

from vystak_channel_runtime.agent_client import (
    A2AAgentClient,
    AgentClient,
    NatsAgentClient,
)
from vystak_channel_runtime.heartbeat import HeartbeatScheduler, is_heartbeat_ok
from vystak_channel_runtime.store import ChannelStore
from vystak_channel_runtime.types import (
    AgentCallError,
    AgentChunk,
    AgentReply,
    InboundEvent,
    Message,
    SkipEvent,
)

logger = logging.getLogger("vystak.channel.runtime")


def _json_safe(metadata: dict[str, Any]) -> dict[str, Any]:
    """Drop non-JSON-serializable entries from event metadata.

    InboundEvent.metadata can carry platform-specific objects (slack-bolt's
    AsyncSay, discord.Message, etc.) that subclasses' hooks need locally
    but can't be sent over the wire to the agent.
    """
    out: dict[str, Any] = {}
    for k, v in metadata.items():
        try:
            json.dumps(v)
        except (TypeError, ValueError):
            continue
        out[k] = v
    return out


class ChannelRuntime(ABC):
    """Template-method base — owns the message lifecycle.

    Subclasses implement: start, stop, parse_event, post_reply.
    Subclasses may override: fetch_history, before_call, after_reply,
    on_no_route, on_agent_error.
    """

    def __init__(
        self,
        config: dict,
        routes: dict,
        store: ChannelStore,
        agent_client: AgentClient | None = None,
    ) -> None:
        self.config = config
        self.routes = routes
        self.store = store
        self.channel_type: str = config.get("channel_type", "")
        self.agent_protocol: str = config.get("agent_protocol", "a2a-turn")
        self._agent_client = agent_client or self._default_agent_client()
        self._heartbeats: list[HeartbeatScheduler] = []

    def _default_agent_client(self) -> AgentClient:
        if self.agent_protocol in ("a2a-turn", "a2a-stream"):
            transport_type = os.environ.get("VYSTAK_TRANSPORT_TYPE", "http")
            if transport_type == "nats":
                nats_url = os.environ.get("VYSTAK_NATS_URL")
                if not nats_url:
                    raise RuntimeError(
                        "VYSTAK_TRANSPORT_TYPE=nats but VYSTAK_NATS_URL is unset",
                    )
                return NatsAgentClient(nats_url)
            return A2AAgentClient()
        if self.agent_protocol == "media-bridge":
            raise NotImplementedError("media-bridge requires a custom AgentClient")
        raise ValueError(f"unknown agent_protocol: {self.agent_protocol}")

    # --- Lifecycle (subclass implements) ----------------------------------

    @abstractmethod
    async def start(self) -> None: ...

    @abstractmethod
    async def stop(self) -> None: ...

    # --- Pipeline hooks (subclass implements) -----------------------------

    @abstractmethod
    def parse_event(self, raw_event: Any) -> InboundEvent: ...

    @abstractmethod
    async def post_reply(
        self, event: InboundEvent, route: str, reply: AgentReply
    ) -> None: ...

    # --- Pipeline hooks (subclass may override; defaults below) -----------

    async def channel_binding_thread_id(self, event: InboundEvent) -> str | None:
        """Subclass hook: return a per-channel-scope thread_id for binding lookup
        when per-thread lookup misses. Default: None (no fallback)."""
        return None

    async def fetch_history(self, event: InboundEvent) -> list[Message]:
        return []

    async def before_call(self, event: InboundEvent, route: str) -> None:
        return None

    async def on_chunk(
        self, event: InboundEvent, route: str, chunk: AgentChunk,
    ) -> None:
        """Streaming hook — called for each chunk during streaming turns.

        Default: no-op. Slack/Discord override to surface tool-call statuses
        (e.g. edit a placeholder message with "Calling get_weather...").
        """
        return None

    async def after_reply(
        self, event: InboundEvent, route: str, reply: AgentReply
    ) -> None:
        if event.thread_id is not None:
            await self.store.set_thread_binding(
                self.channel_type,
                event.scope_id,
                event.thread_id,
                route,
                user_id=event.user_id,
            )

    async def on_no_route(self, event: InboundEvent) -> None:
        logger.info(
            "no route for event scope=%s thread=%s user=%s",
            event.scope_id, event.thread_id, event.user_id,
        )

    async def on_agent_error(
        self, event: InboundEvent, route: str, exc: AgentCallError
    ) -> None:
        logger.exception(
            "agent call failed for route=%s scope=%s: %s",
            route, event.scope_id, exc,
        )

    # --- Authorize (base owns) --------------------------------------------

    async def resolve_route(self, event: InboundEvent) -> str | None:
        """Order: channel_overrides -> thread_binding -> channel_binding (subclass hook)
        -> route_pref (DM) -> default_agent."""
        ov = self.config.get("channel_overrides", {}).get(event.scope_id)
        if ov is not None and isinstance(ov, dict) and ov.get("agent"):
            return ov["agent"]

        if event.thread_id is not None:
            bound = await self.store.get_thread_binding(
                self.channel_type, event.scope_id, event.thread_id,
            )
            if bound:
                return bound
            # Per-channel-scope fallback (subclass-defined; e.g. Slack's
            # `f"{channel_id}:"` convention written by `/vystak route`).
            channel_tid = await self.channel_binding_thread_id(event)
            if channel_tid is not None and channel_tid != event.thread_id:
                bound = await self.store.get_thread_binding(
                    self.channel_type, event.scope_id, channel_tid,
                )
                if bound:
                    return bound

        if event.is_dm:
            pref = await self.store.get_route_pref(
                self.channel_type, event.scope_id,
            )
            if pref:
                return pref

        return self.config.get("default_agent")

    async def authorize(self, event: InboundEvent) -> bool:
        is_bot = bool(event.metadata.get("is_bot"))
        if is_bot and not self.config.get("allow_bots", False):
            return False
        policy = (
            self.config.get("dm_policy")
            if event.is_dm
            else self.config.get("group_policy")
        )
        if policy == "disabled":
            return False
        if policy == "allowlist":
            allow_from = self.config.get("allow_from", [])
            if event.user_id not in allow_from:
                return False
        return not (
            self.config.get("require_mention", False)
            and not event.is_dm
            and not event.mentions_bot
        )

    # --- Call + pipeline (base owns) ----------------------------------------

    def _resolve_agent_url(self, route: str) -> str:
        route_entry = self.routes.get(route)
        if route_entry is None:
            raise AgentCallError(f"unknown route: {route}")
        agent_url = (
            route_entry.get("address") if isinstance(route_entry, dict) else route_entry
        )
        if not agent_url:
            raise AgentCallError(f"route {route} has no address")
        return agent_url

    async def call_agent(
        self,
        event: InboundEvent,
        route: str,
        history: list[Message],
    ) -> AgentReply:
        return await self._agent_client.send_turn(
            self._resolve_agent_url(route),
            text=event.text,
            thread_id=event.thread_id or event.scope_id,
            history=history,
            metadata=_json_safe(event.metadata),
        )

    async def stream_agent(
        self,
        event: InboundEvent,
        route: str,
        history: list[Message],
    ) -> AgentReply:
        """Stream the agent turn, dispatching each chunk to `on_chunk`.

        Returns an `AgentReply` assembled from the streamed text + tool
        calls so the post-stream `post_reply`/`after_reply` flow stays
        identical to the non-streaming path.
        """
        accumulated: list[str] = []
        final_text: str | None = None
        tool_calls: list[dict[str, Any]] = []
        finish_reason: str | None = None

        async for chunk in self._agent_client.stream_turn(
            self._resolve_agent_url(route),
            text=event.text,
            thread_id=event.thread_id or event.scope_id,
            history=history,
            metadata=_json_safe(event.metadata),
        ):
            await self.on_chunk(event, route, chunk)
            if chunk.type == "token":
                accumulated.append(chunk.delta)
            elif chunk.type == "status":
                if chunk.delta:
                    final_text = chunk.delta
            elif chunk.type == "tool_call":
                tool_calls.append({
                    "type": "start",
                    "tool_name": chunk.tool_name,
                    "data": chunk.data,
                })
            elif chunk.type == "tool_result":
                tool_calls.append({
                    "type": "end",
                    "tool_name": chunk.tool_name,
                    "data": chunk.data,
                })
            elif chunk.type == "final":
                finish_reason = chunk.finish_reason or "completed"
                if chunk.delta:
                    final_text = chunk.delta

        text = final_text if final_text is not None else "".join(accumulated)
        return AgentReply(
            text=text,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
        )

    async def _call_route_for_event(
        self, event: InboundEvent,
    ) -> tuple[str | None, AgentReply | None]:
        """Resolve route, call agent. Returns (route, reply). Either may
        be None on no-route or agent-error. Used by both `handle_event`
        and `_handle_synthetic_event`."""
        route = await self.resolve_route(event)
        if route is None:
            await self.on_no_route(event)
            return None, None
        history = await self.fetch_history(event)
        await self.before_call(event, route)
        try:
            if self.agent_protocol == "a2a-stream":
                reply = await self.stream_agent(event, route, history)
            else:
                reply = await self.call_agent(event, route, history)
        except AgentCallError as exc:
            await self.on_agent_error(event, route, exc)
            return route, None
        return route, reply

    async def handle_event(self, raw_event: Any) -> None:
        try:
            event = self.parse_event(raw_event)
        except SkipEvent:
            return
        if not await self.authorize(event):
            return
        route, reply = await self._call_route_for_event(event)
        if route is None or reply is None:
            return
        await self.post_reply(event, route, reply)
        await self.after_reply(event, route, reply)

    # --- Heartbeat lifecycle ----------------------------------------------

    @property
    def canonical_name(self) -> str:
        return self.config.get("canonical_name", "")

    def _heartbeat_for_route(self, route_entry: Any) -> Heartbeat | None:
        if not isinstance(route_entry, dict):
            return None
        raw = route_entry.get("heartbeat")
        if raw is None:
            return None
        if isinstance(raw, Heartbeat):
            return raw
        return Heartbeat.model_validate(raw)

    async def _start_heartbeats(self) -> None:
        """Start a HeartbeatScheduler for each routed agent whose heartbeat
        targets this channel. Subclasses must call this after setting up
        I/O (so `post_reply` is ready) but BEFORE entering any blocking
        serve loop. Schedulers use `asyncio.create_task` internally, so
        this call returns immediately."""
        for agent_name, route_entry in self.routes.items():
            hb = self._heartbeat_for_route(route_entry)
            if hb is None or not hb.enabled:
                continue
            if hb.target_channel != self.canonical_name:
                continue
            scheduler = HeartbeatScheduler(self, agent_name, hb)
            self._heartbeats.append(scheduler)
            await scheduler.start()

    async def _stop_heartbeats(self) -> None:
        """Cancel all running heartbeat schedulers. Subclasses must call this
        AT THE START of their `stop()` so in-flight fires don't outlive the
        I/O loop."""
        for hb in self._heartbeats:
            await hb.stop()
        self._heartbeats.clear()

    async def _handle_synthetic_event(self, event: InboundEvent) -> None:
        """Entry for heartbeat-synthesized events.

        Bypasses parse_event + authorize (synthetic events are trusted).
        After the agent call, evaluates the reply against `is_heartbeat_ok`;
        on alerts, synthesizes a *delivery* event with the real scope/thread
        and passes it to subclass `post_reply`. Always skips `after_reply`
        (synthetic scopes shouldn't pollute the binding store).
        """
        route, reply = await self._call_route_for_event(event)
        if route is None or reply is None:
            return

        ack_max = int(event.metadata.get("ack_max_chars", 300))
        if is_heartbeat_ok(reply.text, ack_max):
            logger.info(
                "heartbeat.acked agent=%s thread=%s",
                route, event.metadata.get("deliver_thread"),
            )
            return

        deliver_scope = event.metadata.get("deliver_scope")
        deliver_thread = event.metadata.get("deliver_thread")
        if not deliver_scope or not deliver_thread:
            logger.warning(
                "heartbeat reply has alert content but no delivery target — "
                "dropping. agent=%s scope=%s",
                route, event.scope_id,
            )
            return

        delivery_event = event.model_copy(update={
            "scope_id": deliver_scope,
            "thread_id": deliver_thread,
        })
        await self.post_reply(delivery_event, route, reply)
        # Intentionally skip after_reply — heartbeat fires must not write
        # ThreadBindings (synthetic scopes would pollute the store).
