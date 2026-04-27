"""HttpTransport — uses httpx (client) and relies on generated FastAPI /a2a (server)."""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx
from pydantic import ValidationError
from vystak.transport import (
    A2AEvent,
    A2AMessage,
    A2AResult,
    AgentRef,
    Transport,
)
from vystak.transport.base import ServerDispatcherProtocol


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
                try:
                    yield A2AEvent.model_validate(parsed)
                except ValidationError:
                    # Skip lines that don't match the A2AEvent shape (e.g.,
                    # legacy JSON-RPC envelope frames emitted by the
                    # LangChain adapter for token/status/final events).
                    # Existing SSE consumers can still parse the envelope
                    # themselves at a higher layer.
                    continue

    async def serve(self, canonical_name: str, handler: ServerDispatcherProtocol) -> None:
        # FastAPI's /a2a route already handles inbound HTTP; nothing to do.
        return None

    def _agent_base_url(self, agent: AgentRef) -> str:
        """Derive the agent's base URL from its A2A wire address.

        Plan A's URL format is consistent: the A2A endpoint lives at `{base}/a2a`,
        so stripping the suffix gives the base. For future transports that use
        different paths, revisit.
        """
        a2a_url = self.resolve_address(agent.canonical_name)
        return a2a_url.removesuffix("/a2a")

    async def create_response(
        self,
        agent: AgentRef,
        request: dict[str, Any],
        metadata: dict[str, Any],
        *,
        timeout: float,
    ) -> dict[str, Any]:
        base = self._agent_base_url(agent)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(f"{base}/v1/responses", json=request)
            response.raise_for_status()
            return response.json()

    async def create_response_stream(
        self,
        agent: AgentRef,
        request: dict[str, Any],
        metadata: dict[str, Any],
        *,
        timeout: float,
    ) -> AsyncIterator[dict[str, Any]]:
        base = self._agent_base_url(agent)
        # Force stream=true even if caller didn't set it — this method's
        # contract is that we yield chunks.
        body = {**request, "stream": True}
        async with (
            httpx.AsyncClient(timeout=timeout) as client,
            client.stream("POST", f"{base}/v1/responses", json=body) as response,
        ):
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line or not line.startswith("data:"):
                    continue
                data = line.removeprefix("data:").strip()
                if not data or data == "[DONE]":
                    continue
                try:
                    yield json.loads(data)
                except json.JSONDecodeError:
                    continue

    async def get_response(
        self,
        agent: AgentRef,
        response_id: str,
        *,
        timeout: float,
    ) -> dict[str, Any] | None:
        base = self._agent_base_url(agent)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(f"{base}/v1/responses/{response_id}")
            if response.status_code == 404:
                return None
            response.raise_for_status()
            return response.json()

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

    def _parse_result(self, body: dict[str, Any], fallback_correlation: str) -> A2AResult:
        result = body.get("result", {}) or {}
        parts = result.get("status", {}).get("message", {}).get("parts", [])
        text = ""
        for part in parts:
            if isinstance(part, dict) and "text" in part:
                text += part["text"]
        return A2AResult(
            text=text,
            correlation_id=result.get("correlation_id") or fallback_correlation,
            metadata={},
        )
