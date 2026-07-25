"""NATS-transport client for the panel: detached turn start + JetStream replay."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from vystak.transport import AgentRef
from vystak_transport_nats import NatsTransport
from vystak_transport_nats.streams import (
    ensure_stream,
    read_turn_events,
    stream_base,
    turn_subject,
)

from vystak_channel_panel.responses_client import PanelStreamEvent
from vystak_channel_panel.turn_stream import translate_responses_event

logger = logging.getLogger("vystak.channel.panel.nats")


class PanelNatsClient:
    def __init__(
        self,
        nats_url: str,
        *,
        timeout_s: float = 30.0,
        idle_timeout_s: float = 120.0,
    ) -> None:
        self._transport = NatsTransport(nats_url)
        self._timeout = timeout_s
        self.idle_timeout_s = idle_timeout_s

    @staticmethod
    def turn_subject_for(route_entry: dict, conversation_id: str, turn_id: str) -> str:
        return turn_subject(stream_base(route_entry["address"]), conversation_id, turn_id)

    async def start_turn(
        self,
        route_entry: dict,
        text: str,
        *,
        conv_id: str,
        turn_id: str,
        previous_response_id: str | None,
        user_id: str | None,
        project_id: str | None,
    ) -> str:
        base = stream_base(route_entry["address"])
        subject = turn_subject(base, conv_id, turn_id)
        nc = await self._transport.nats_connection()
        await ensure_stream(nc.jetstream(), base)
        request = {
            "model": "",
            "input": text,
            "previous_response_id": previous_response_id,
            "store": True,
            "stream": True,
            "user_id": user_id,
            "project_id": project_id,
        }
        await self._transport.create_response_detached(
            AgentRef(canonical_name=route_entry["canonical"]),
            request,
            {},
            turn_id=turn_id,
            stream_subject=subject,
            timeout=self._timeout,
        )
        return subject

    async def stream_turn_events(self, subject: str) -> AsyncIterator[tuple[int, PanelStreamEvent]]:
        nc = await self._transport.nats_connection()
        pending_calls: dict[str, dict] = {}
        async for payload in read_turn_events(nc, subject, idle_timeout_s=self.idle_timeout_s):
            ev = translate_responses_event(payload.get("event") or {}, pending_calls)
            if ev is not None:
                yield int(payload.get("seq", 0)), ev
