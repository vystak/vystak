"""HttpTransport — uses httpx (client) and relies on generated FastAPI /a2a (server)."""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx
from vystak.transport import (
    A2AEvent,
    A2AMessage,
    A2AResult,
    AgentRef,
    Transport,
)
from vystak.transport.base import A2AHandlerProtocol


class HttpTransport(Transport):
    """HTTP implementation of the Transport ABC.

    Client side: httpx POST to `{agent_url}/a2a` with JSON-RPC A2A envelope.
    Server side: the generated agent already exposes `/a2a` via FastAPI;
    `serve()` is a no-op.

    Routes are supplied at construction time (typically built from
    `VYSTAK_ROUTES_JSON` + the platform's canonical-to-URL mapping).
    """

    type = "http"
    supports_streaming = True

    def __init__(self, routes: dict[str, str]) -> None:
        """`routes` maps canonical_name -> absolute URL ending in `/a2a`."""
        self._routes = dict(routes)

    def resolve_address(self, canonical_name: str) -> str:
        try:
            return self._routes[canonical_name]
        except KeyError:
            raise KeyError(
                f"HttpTransport has no route for canonical name "
                f"{canonical_name!r}; known: {sorted(self._routes)}"
            ) from None

    async def send_task(
        self,
        agent: AgentRef,
        message: A2AMessage,
        metadata: dict[str, Any],
        *,
        timeout: float,
    ) -> A2AResult:
        url = self.resolve_address(agent.canonical_name)
        payload = self._build_payload("tasks/send", message, metadata)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                body = response.json()
        except httpx.TimeoutException as exc:
            raise TimeoutError(str(exc)) from exc
        return self._parse_result(body, message.correlation_id)

    async def stream_task(
        self,
        agent: AgentRef,
        message: A2AMessage,
        metadata: dict[str, Any],
        *,
        timeout: float,
    ) -> AsyncIterator[A2AEvent]:
        url = self.resolve_address(agent.canonical_name)
        payload = self._build_payload("tasks/sendSubscribe", message, metadata)
        async with (
            httpx.AsyncClient(timeout=timeout) as client,
            client.stream("POST", url, json=payload) as response,
        ):
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line or not line.startswith("data:"):
                    continue
                data = line.removeprefix("data:").strip()
                if not data:
                    continue
                try:
                    parsed = json.loads(data)
                except json.JSONDecodeError:
                    continue
                # A2AEvent model_validate tolerates missing optional fields.
                yield A2AEvent.model_validate(parsed)

    async def serve(
        self, canonical_name: str, handler: A2AHandlerProtocol
    ) -> None:
        # FastAPI's /a2a route already handles inbound HTTP; nothing to do.
        return None

    def _build_payload(
        self, method: str, message: A2AMessage, metadata: dict[str, Any]
    ) -> dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": method,
            "params": {
                "id": message.correlation_id,
                "message": {
                    "role": message.role,
                    "parts": message.parts,
                },
                "metadata": {**message.metadata, **metadata},
            },
        }

    def _parse_result(
        self, body: dict[str, Any], fallback_correlation: str
    ) -> A2AResult:
        result = body.get("result", {}) or {}
        parts = (
            result.get("status", {})
            .get("message", {})
            .get("parts", [])
        )
        text = ""
        for part in parts:
            if isinstance(part, dict) and "text" in part:
                text += part["text"]
        return A2AResult(
            text=text,
            correlation_id=result.get("correlation_id") or fallback_correlation,
            metadata={},
        )
