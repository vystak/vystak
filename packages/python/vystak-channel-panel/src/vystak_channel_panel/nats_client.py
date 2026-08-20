"""NATS-transport client for the panel: detached turn start + JetStream replay."""

from __future__ import annotations

import json
import logging
import uuid
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
        status_timeout_s: float = 5.0,
    ) -> None:
        self._transport = NatsTransport(nats_url)
        self._timeout = timeout_s
        self.idle_timeout_s = idle_timeout_s
        self._status_timeout = status_timeout_s

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

    async def turn_status(self, agent_name: str, turn_id: str) -> str:
        """`responses/turnStatus {turn_id}` on the agent's tasks subject.

        Used when a turn's JetStream subject goes idle: idle no longer means
        the turn concluded, it means we ask the agent whether it's still
        `running`/`parked` (keep waiting), `done`/`failed` (conclude), or
        `unknown` (conclude — nothing to resume). *agent_name* is the
        canonical name (`resolve_address` builds the tasks subject from it,
        same as `create_response_detached`); the panel-side conversation
        lookup that produces it lives in `turn_worker`, not here.
        """
        nc = await self._transport.nats_connection()
        subject = self._transport.resolve_address(agent_name)
        payload = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": str(uuid.uuid4()),
                "method": "responses/turnStatus",
                "params": {"turn_id": turn_id},
            }
        ).encode()
        try:
            reply = await nc.request(subject, payload, timeout=self._status_timeout)
        except TimeoutError as e:
            raise TimeoutError(
                f"NATS request to {subject} (responses/turnStatus) "
                f"timed out after {self._status_timeout}s"
            ) from e
        body = json.loads(reply.data)
        result = body.get("result") or {}
        return result.get("status", "unknown")

    async def resume_detached(self, agent_name: str, turn_id: str, resume: dict) -> None:
        """`responses/resumeDetached {turn_id, resume}` on the agent's tasks
        subject — the bridge rejects this unless the turn is currently
        parked (JSON-RPC error -32602 "turn is not parked"), which surfaces
        here as a `RuntimeError` carrying the bridge's message so the
        approval route can turn it into a 409."""
        nc = await self._transport.nats_connection()
        subject = self._transport.resolve_address(agent_name)
        payload = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": str(uuid.uuid4()),
                "method": "responses/resumeDetached",
                "params": {"turn_id": turn_id, "resume": resume},
            }
        ).encode()
        reply = await nc.request(subject, payload, timeout=self._status_timeout)
        body = json.loads(reply.data)
        if body.get("error"):
            raise RuntimeError(body["error"].get("message", "resume failed"))

    async def stream_turn_events(self, subject: str) -> AsyncIterator[tuple[int, PanelStreamEvent]]:
        nc = await self._transport.nats_connection()
        pending_calls: dict[str, dict] = {}
        async for payload in read_turn_events(nc, subject, idle_timeout_s=self.idle_timeout_s):
            ev = translate_responses_event(payload.get("event") or {}, pending_calls)
            if ev is not None:
                yield int(payload.get("seq", 0)), ev
