"""Pluggable agent client port + A2A default impl."""

from __future__ import annotations

import asyncio
import json
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
        # A2A v0.3 message/send shape (the SDK's v0.3 compat layer accepts
        # this on /a2a). `kind: "message"` and `messageId` are required by
        # the wire schema; using thread_id as messageId keeps a stable id
        # per turn so downstream tasks dedupe correctly.
        params: dict[str, Any] = {
            "message": {
                "kind": "message",
                "messageId": str(uuid.uuid4()),
                "role": "user",
                "parts": [{"kind": "text", "text": text}],
                "contextId": thread_id,
            },
        }
        if history:
            params["history"] = [m.model_dump() for m in history]
        if metadata:
            params["metadata"] = metadata
        body = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "message/send",
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
            "message": {
                "kind": "message",
                "messageId": str(uuid.uuid4()),
                "role": "user",
                "parts": [{"kind": "text", "text": text}],
                "contextId": thread_id,
            },
        }
        if history:
            params["history"] = [m.model_dump() for m in history]
        if metadata:
            params["metadata"] = metadata
        body = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "message/stream",
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
          1. Google A2A canonical (current vystak-template-langchain-python
             emission via a2a-sdk's v0.3-compat layer):
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

        Maps the four shapes A2A peers emit over SSE. After Phase 19 the
        primary shape is #2 (status-update) emitted by a2a-sdk's v0.3-compat
        layer; shapes #1, #3, #4 are retained for back-compat with older
        agents that may still talk the legacy codegen wire format.

          1. token      — JSON-RPC envelope with `result.artifact.parts[0].text`,
                          accumulated by the agent (`append: True`).
          2. status     — JSON-RPC envelope with `result.status.message.parts[].text`
                          plus a `state`. `final=True` ends the turn. The
                          current template also stamps tool-call events here
                          via `message.metadata.vystak_event`.
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

            # Tool-call surfacing — executor tags message.metadata with
            # {vystak_event: tool_call|tool_result, tool_name: ...} so the
            # slack runtime can render typing-status hints. Map to a typed
            # AgentChunk and short-circuit before the regular status path.
            metadata = msg.get("metadata") or {}
            ev_type = metadata.get("vystak_event")
            if ev_type in ("tool_call", "tool_result"):
                return AgentChunk(
                    type=ev_type,
                    delta=text,
                    tool_name=metadata.get("tool_name"),
                    data=metadata,
                    raw=payload,
                )

            is_final = bool(result.get("final")) or state == "completed"
            return AgentChunk(
                type="final" if is_final else "status",
                delta=text,
                finish_reason=state,
                final=is_final,
                raw=payload,
            )

        return None


class NatsAgentClient:
    """A2A client that publishes JSON-RPC envelopes over NATS request/reply.

    Same wire shape as A2AAgentClient (HTTP) — only the transport differs.
    The agent_url here is the NATS subject the peer listens on (read from
    routes[<peer>].address), not an HTTP URL.

    Streaming over NATS (multi-message reply pattern) is not implemented;
    stream_turn falls back to a single-shot send_turn that yields one
    final chunk. Channel runtime's a2a-turn path doesn't call stream_turn
    for non-streaming agent_protocol values.
    """

    def __init__(
        self,
        nats_url: str,
        timeout_s: float = 60.0,
    ) -> None:
        self._nats_url = nats_url
        self._timeout = timeout_s
        # Lazy-initialised on first call. Re-used across requests so we
        # don't pay reconnect cost per turn.
        self._nc: Any = None
        self._connect_lock: asyncio.Lock | None = None

    async def _connect(self) -> Any:
        """Return a connected NATS client, creating one on first use."""
        if self._connect_lock is None:
            self._connect_lock = asyncio.Lock()
        async with self._connect_lock:
            if self._nc is None or self._nc.is_closed:
                import nats
                logger.info("nats.connect url=%s", self._nats_url)
                self._nc = await nats.connect(self._nats_url)
            return self._nc

    async def close(self) -> None:
        """Close the cached NATS connection. Safe to call multiple times."""
        nc = self._nc
        if nc is not None and not nc.is_closed:
            try:
                await nc.close()
            except Exception:
                logger.exception("nats.close failed")
        self._nc = None

    async def send_turn(
        self,
        agent_url: str,
        text: str,
        thread_id: str,
        history: list[Message] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AgentReply:
        """Publish a `message/send` envelope on the peer's subject and
        await the JSON-RPC reply on the auto-generated reply inbox.

        Injects the active OTel span's W3C traceparent into the
        message's ``metadata`` field so the receiving agent's NATS
        bridge can extract it and continue the trace under one root.
        """
        subject = agent_url
        request_id = str(uuid.uuid4())
        # Build message metadata with traceparent injected on top of any
        # caller-supplied metadata. The bridge on the receiver side
        # extracts these keys back into context.
        msg_metadata: dict[str, Any] = dict(metadata) if metadata else {}
        try:
            from opentelemetry.propagate import inject

            inject(msg_metadata)
        except Exception:  # noqa: BLE001
            # OTel not initialized — leave metadata untouched.
            pass
        params: dict[str, Any] = {
            "message": {
                "kind": "message",
                "messageId": str(uuid.uuid4()),
                "role": "user",
                "parts": [{"kind": "text", "text": text}],
                "contextId": thread_id,
                "metadata": msg_metadata,
            },
        }
        if history:
            params["history"] = [m.model_dump() for m in history]
        # Keep params.metadata for back-compat with consumers that read
        # the top-level field; populate it with the same traceparent.
        if metadata or msg_metadata:
            params["metadata"] = msg_metadata
        body = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "message/send",
            "params": params,
        }
        try:
            nc = await self._connect()
        except Exception as exc:  # noqa: BLE001
            raise AgentCallError(
                f"nats connect to {self._nats_url} failed: {exc}",
            ) from exc

        payload = json.dumps(body).encode()
        # Wrap the request in a `nats.request` span so the publish hop
        # is visible in Jaeger. When OTel isn't initialized this is a
        # no-op span — zero overhead.
        try:
            from opentelemetry import trace as otel_trace

            tracer = otel_trace.get_tracer("vystak.channel.runtime.nats_client")
            span_cm = tracer.start_as_current_span(
                f"nats.request {subject}",
                attributes={
                    "messaging.system": "nats",
                    "messaging.destination": subject,
                    "messaging.operation": "send",
                },
            )
        except Exception:  # noqa: BLE001
            from contextlib import nullcontext

            span_cm = nullcontext()
        try:
            with span_cm:
                reply = await nc.request(subject, payload, timeout=self._timeout)
        except Exception as exc:  # noqa: BLE001
            # Covers nats.errors.TimeoutError, NoRespondersError, and any
            # connection-level error. All are surfaced as AgentCallError
            # so ChannelRuntime.on_agent_error fires the same way as HTTP.
            raise AgentCallError(
                f"nats request to {subject} failed: {exc}",
            ) from exc

        try:
            data = json.loads(reply.data)
        except (json.JSONDecodeError, ValueError) as exc:
            raise AgentCallError(
                f"nats reply from {subject} not valid JSON: {exc}",
            ) from exc
        return A2AAgentClient._reply_from_jsonrpc(data)

    async def stream_turn(
        self,
        agent_url: str,
        text: str,
        thread_id: str,
        history: list[Message] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AsyncIterator[AgentChunk]:
        """No streaming support over NATS in v1 — fall back to single-shot.

        message/stream over NATS would need a multi-message reply pattern
        (subscribe to inbox, publish, drain until terminal chunk). Defer
        until a real streaming use-case lands. For now we yield one
        synthetic final chunk derived from send_turn.
        """
        reply = await self.send_turn(
            agent_url,
            text=text,
            thread_id=thread_id,
            history=history,
            metadata=metadata,
        )
        yield AgentChunk(
            type="final",
            delta=reply.text,
            finish_reason=reply.finish_reason or "completed",
            final=True,
            raw=reply.raw,
        )
