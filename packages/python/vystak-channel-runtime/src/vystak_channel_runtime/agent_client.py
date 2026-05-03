"""Pluggable agent client port + A2A default impl."""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import AsyncIterator
from typing import Any, Protocol, runtime_checkable

import httpx

from vystak_channel_runtime.types import (
    AgentCallError,
    AgentChunk,
    AgentReply,
    Message,
)

logger = logging.getLogger("vystak.channel.runtime.agent_client")


@runtime_checkable
class AgentClient(Protocol):
    """Port for talking to an agent. Subclassed by A2A, future media-bridge, etc."""

    async def send_turn(
        self,
        agent_url: str,
        text: str,
        thread_id: str,
        history: list[Message] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AgentReply: ...

    async def stream_turn(
        self,
        agent_url: str,
        text: str,
        thread_id: str,
        history: list[Message] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AsyncIterator[AgentChunk]: ...


class A2AAgentClient:
    """A2A JSON-RPC client. Default for `agent_protocol in {a2a-turn, a2a-stream}`."""

    def __init__(
        self,
        timeout_s: float = 30.0,
        max_retries: int = 3,
        base_backoff: float = 0.5,
    ) -> None:
        self._timeout = timeout_s
        self._max_retries = max_retries
        self._base_backoff = base_backoff

    async def send_turn(
        self,
        agent_url: str,
        text: str,
        thread_id: str,
        history: list[Message] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AgentReply:
        # Address may already include /a2a (current routes.json shape) or
        # be the bare HTTP root (older shape) — append only when needed.
        stripped = agent_url.rstrip("/")
        url = stripped if stripped.endswith("/a2a") else stripped + "/a2a"
        request_id = str(uuid.uuid4())
        params: dict[str, Any] = {
            "id": thread_id,
            # Google A2A canonical message shape — parts list, not bare content.
            # vystak-adapter-langchain reads raw_message["parts"]; sending
            # `content` here would surface as an empty message to the agent.
            "message": {"role": "user", "parts": [{"text": text}]},
        }
        if history:
            params["history"] = [m.model_dump() for m in history]
        if metadata:
            params["metadata"] = metadata
        body = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tasks/send",
            "params": params,
        }
        async with httpx.AsyncClient() as client:
            for attempt in range(1, self._max_retries + 1):
                try:
                    resp = await client.post(url, json=body, timeout=self._timeout)
                    if resp.status_code == 200:
                        return self._reply_from_jsonrpc(resp.json())
                    if 500 <= resp.status_code < 600 and attempt < self._max_retries:
                        await asyncio.sleep(self._base_backoff * (2 ** (attempt - 1)))
                        continue
                    raise AgentCallError(
                        f"agent {agent_url} returned {resp.status_code}: {resp.text[:200]}"
                    )
                except (httpx.ConnectError, httpx.ReadTimeout) as exc:
                    if attempt < self._max_retries:
                        await asyncio.sleep(self._base_backoff * (2 ** (attempt - 1)))
                        continue
                    raise AgentCallError(f"agent {agent_url} connect failed: {exc}") from exc
            raise AgentCallError(f"agent {agent_url} exhausted retries")

    async def stream_turn(
        self,
        agent_url: str,
        text: str,
        thread_id: str,
        history: list[Message] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AsyncIterator[AgentChunk]:
        # Address may already include /a2a (current routes.json shape) or
        # be the bare HTTP root (older shape) — append only when needed.
        stripped = agent_url.rstrip("/")
        url = stripped if stripped.endswith("/a2a") else stripped + "/a2a"
        request_id = str(uuid.uuid4())
        params: dict[str, Any] = {
            "id": thread_id,
            # Google A2A canonical message shape — parts list, not bare content.
            # vystak-adapter-langchain reads raw_message["parts"]; sending
            # `content` here would surface as an empty message to the agent.
            "message": {"role": "user", "parts": [{"text": text}]},
        }
        if history:
            params["history"] = [m.model_dump() for m in history]
        if metadata:
            params["metadata"] = metadata
        body = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tasks/sendSubscribe",
            "params": params,
        }
        # Retry only the pre-stream phase (connect + initial response).
        # Once we start yielding chunks the stream is committed; errors
        # propagate as AgentCallError without retry to avoid duplicate
        # token deliveries.
        async with httpx.AsyncClient() as client:
            for attempt in range(1, self._max_retries + 1):
                try:
                    async with client.stream(
                        "POST", url, json=body, timeout=self._timeout
                    ) as resp:
                        if 500 <= resp.status_code < 600 and attempt < self._max_retries:
                            await asyncio.sleep(
                                self._base_backoff * (2 ** (attempt - 1))
                            )
                            continue
                        if resp.status_code != 200:
                            raise AgentCallError(
                                f"agent {agent_url} returned {resp.status_code}"
                            )
                        # Stream committed — no more retries from here.
                        try:
                            async for line in resp.aiter_lines():
                                if not line or not line.startswith("data:"):
                                    continue
                                chunk = self._chunk_from_sse(
                                    line.removeprefix("data:").strip()
                                )
                                if chunk is not None:
                                    yield chunk
                        except (httpx.ConnectError, httpx.ReadTimeout) as exc:
                            raise AgentCallError(
                                f"agent {agent_url} stream interrupted: {exc}"
                            ) from exc
                        return
                except (httpx.ConnectError, httpx.ReadTimeout) as exc:
                    if attempt < self._max_retries:
                        await asyncio.sleep(
                            self._base_backoff * (2 ** (attempt - 1))
                        )
                        continue
                    raise AgentCallError(
                        f"agent {agent_url} stream failed: {exc}"
                    ) from exc
            raise AgentCallError(f"agent {agent_url} stream exhausted retries")

    @staticmethod
    def _reply_from_jsonrpc(payload: dict[str, Any]) -> AgentReply:
        """Extract assistant text from an A2A JSON-RPC response.

        Supports two response shapes:
          1. Google A2A canonical (current vystak-adapter-langchain emission):
             {result: {status: {message: {parts: [{text: ...}]}}}}
          2. Simplified messages-list shape (kept for back-compat with
             older adapters / mocks):
             {result: {messages: [{role: assistant, content: ...}]}}
        """
        if "error" in payload:
            raise AgentCallError(f"agent error: {payload['error']}")
        result = payload.get("result", {})

        # Shape 1: A2A status.message.parts[].text
        status = result.get("status") or {}
        status_msg = status.get("message") or {}
        parts = status_msg.get("parts") or []
        if parts:
            text = "".join(p.get("text", "") for p in parts if isinstance(p, dict))
            return AgentReply(
                text=text,
                tool_calls=result.get("tool_calls", []),
                finish_reason=status.get("state") or result.get("finish_reason"),
                raw=payload,
            )

        # Shape 2: simple messages list
        messages = result.get("messages", [])
        text = ""
        for m in messages:
            if m.get("role") == "assistant":
                text = m.get("content", "")
                break
        return AgentReply(
            text=text,
            tool_calls=result.get("tool_calls", []),
            finish_reason=result.get("finish_reason"),
            raw=payload,
        )

    @staticmethod
    def _chunk_from_sse(data: str) -> AgentChunk | None:
        """Parse one SSE `data:` line into a typed AgentChunk.

        Maps the four shapes vystak-adapter-langchain emits over A2A SSE:

          1. token      — JSON-RPC envelope with `result.artifact.parts[0].text`,
                          accumulated by the agent (`append: True`).
          2. status     — JSON-RPC envelope with `result.status.message.parts[].text`
                          plus a `state`. `final=True` ends the turn.
          3. final      — JSON-RPC envelope with `result.status.state="completed"`,
                          `final=True`. Followed by a bare A2AEvent dump (#4).
          4. tool_call /
             tool_result/
             final      — bare A2AEvent: `{type, text, data, final}`.
        """
        import json

        try:
            payload = json.loads(data)
        except json.JSONDecodeError:
            return None

        # Shape 4: bare A2AEvent dump (no jsonrpc wrapper).
        ev_type = payload.get("type")
        if ev_type in {"tool_call", "tool_call_start", "tool_call_end",
                       "tool_result", "final", "status"}:
            tool_name = (payload.get("data") or {}).get("tool_name")
            normalized = ev_type
            if ev_type == "tool_call_start":
                normalized = "tool_call"
            elif ev_type == "tool_call_end":
                normalized = "tool_result"
            return AgentChunk(
                type=normalized,
                delta=payload.get("text") or "",
                tool_name=tool_name,
                data=payload.get("data"),
                final=bool(payload.get("final")),
                raw=payload,
            )

        # Shapes 1-3: JSON-RPC envelopes.
        result = payload.get("result")
        if not isinstance(result, dict):
            return None

        # Shape 1: token (artifact)
        artifact = result.get("artifact")
        if isinstance(artifact, dict):
            parts = artifact.get("parts") or []
            text = "".join(p.get("text", "") for p in parts if isinstance(p, dict))
            return AgentChunk(type="token", delta=text, raw=payload)

        # Shape 2/3: status
        status = result.get("status")
        if isinstance(status, dict):
            state = status.get("state")
            msg = status.get("message") or {}
            parts = msg.get("parts") or []
            text = "".join(p.get("text", "") for p in parts if isinstance(p, dict))
            is_final = bool(result.get("final")) or state == "completed"
            return AgentChunk(
                type="final" if is_final else "status",
                delta=text,
                finish_reason=state,
                final=is_final,
                raw=payload,
            )

        return None
