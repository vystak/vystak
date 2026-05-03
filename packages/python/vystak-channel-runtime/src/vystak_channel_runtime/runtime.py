"""ChannelRuntime — template-method base for all channel containers."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

from vystak_channel_runtime.agent_client import (
    A2AAgentClient,
    AgentClient,
)
from vystak_channel_runtime.store import ChannelStore
from vystak_channel_runtime.types import (
    AgentCallError,
    AgentReply,
    InboundEvent,
    Message,
    SkipEvent,
)

logger = logging.getLogger("vystak.channel.runtime")


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

    def _default_agent_client(self) -> AgentClient:
        if self.agent_protocol in ("a2a-turn", "a2a-stream"):
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

    async def call_agent(
        self,
        event: InboundEvent,
        route: str,
        history: list[Message],
    ) -> AgentReply:
        route_entry = self.routes.get(route)
        if route_entry is None:
            raise AgentCallError(f"unknown route: {route}")
        agent_url = (
            route_entry.get("address") if isinstance(route_entry, dict) else route_entry
        )
        if not agent_url:
            raise AgentCallError(f"route {route} has no address")
        return await self._agent_client.send_turn(
            agent_url,
            text=event.text,
            thread_id=event.thread_id or event.scope_id,
            history=history,
            metadata=event.metadata,
        )

    async def handle_event(self, raw_event: Any) -> None:
        try:
            event = self.parse_event(raw_event)
        except SkipEvent:
            return
        if not await self.authorize(event):
            return
        route = await self.resolve_route(event)
        if route is None:
            await self.on_no_route(event)
            return
        history = await self.fetch_history(event)
        await self.before_call(event, route)
        try:
            reply = await self.call_agent(event, route, history)
        except AgentCallError as exc:
            await self.on_agent_error(event, route, exc)
            return
        await self.post_reply(event, route, reply)
        await self.after_reply(event, route, reply)
