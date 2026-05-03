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
        url = agent_url.rstrip("/") + "/a2a"
        request_id = str(uuid.uuid4())
        params: dict[str, Any] = {
            "id": thread_id,
            "message": {"role": "user", "content": text},
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
        url = agent_url.rstrip("/") + "/a2a"
        request_id = str(uuid.uuid4())
        params: dict[str, Any] = {
            "id": thread_id,
            "message": {"role": "user", "content": text},
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
        if "error" in payload:
            raise AgentCallError(f"agent error: {payload['error']}")
        result = payload.get("result", {})
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
        import json

        try:
            payload = json.loads(data)
        except json.JSONDecodeError:
            return None
        result = payload.get("result", {})
        delta = result.get("delta", "")
        if not delta and not result.get("finish_reason"):
            return None
        return AgentChunk(
            delta=delta,
            tool_call_delta=result.get("tool_call_delta"),
            finish_reason=result.get("finish_reason"),
            raw=payload,
        )
