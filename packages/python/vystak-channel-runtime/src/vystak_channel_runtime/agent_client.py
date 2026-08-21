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

    async def resume_turn(
        self, thread_id: str, resume: dict[str, Any], agent_url: str | None = None
    ) -> AgentReply: ...


class A2AAgentClient:
    """A2A JSON-RPC client. Default for `agent_protocol in {a2a-turn, a2a-stream}`."""

    def __init__(
        self,
        timeout_s: float = 30.0,
        max_retries: int = 3,
        base_backoff: float = 0.5,
        resume_timeout_s: float = 300.0,
    ) -> None:
        self._timeout = timeout_s
        self._max_retries = max_retries
        self._base_backoff = base_backoff
        # A gated tool can run real work before the graph parks again, so
        # the resume endpoint's read bound is generous (mirrors the
        # nats_bridge's `_resume_and_collect_text` ~300s timeout) —
        # unrelated to `_timeout`, which governs the short send_turn calls.
        self._resume_timeout = resume_timeout_s
        # thread_id -> agent HTTP root (no trailing /a2a), learned from the
        # most recent send_turn/stream_turn call for that thread. resume_turn
        # has no agent_url parameter (Task 11 contract — the Slack runtime
        # only carries thread_id + tool through the Block Kit button value),
        # so it looks the base URL up here rather than being told it again.
        self._known_bases: dict[str, str] = {}

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
        root = stripped.removesuffix("/a2a")
        self._known_bases[thread_id] = root
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
                        reply = self._reply_from_jsonrpc(resp.json())
                        # The `approval_pending` marker's thread_id is the
                        # LangGraph checkpoint key (executor.py uses
                        # `context.task_id`, NOT the `contextId` the channel
                        # sent as *thread_id* above) — that's the key
                        # resume_turn is later called with, so alias it to
                        # the same base URL here or resume_turn can never
                        # find it.
                        pa_tid = (reply.pending_approval or {}).get("thread_id")
                        if pa_tid:
                            self._known_bases[pa_tid] = root
                        return reply
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
        root = stripped.removesuffix("/a2a")
        self._known_bases[thread_id] = root
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
                                    if chunk.type == "approval_pending":
                                        # Same aliasing send_turn does: the
                                        # marker's thread_id (executor.py's
                                        # task_id) differs from the contextId
                                        # this call sent as *thread_id*, and
                                        # resume_turn is later called with
                                        # the marker's id.
                                        pa_tid = (chunk.data or {}).get("thread_id")
                                        if pa_tid:
                                            self._known_bases[pa_tid] = root
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

    async def resume_turn(
        self, thread_id: str, resume: dict[str, Any], agent_url: str | None = None
    ) -> AgentReply:
        """POST `{base}/v1/_vystak/resume` and collect the resumed run's text.

        Deviation from the original brief (`-> str`): to support chaining —
        a resumed run can park AGAIN on a second gated tool — this returns
        an `AgentReply` with `pending_approval` set instead of a bare
        string, so a caller (the Slack runtime) can uniformly branch on
        `reply.pending_approval` after both `send_turn`/`call_agent` and
        `resume_turn` without a second return shape.

        Mirrors `vystak_channel_panel.routes_approvals._run_resume_http`
        and the nats_bridge's `_handle_resume_thread`: when the SSE ends
        with a terminal `response.completed`/`response.failed`/`[DONE]`-only
        event, the turn is done. When it ends with none of those, a GET
        to `/v1/_vystak/checkpoint` disambiguates a genuine truncation from
        a second park.

        `agent_url`, if given, both overrides and refreshes the cached base
        URL for *thread_id* — the `_known_bases` cache is process-local, so
        after a channel restart it's empty even though the agent-side park
        is durable. Callers that persisted the agent route alongside the
        button (the Slack runtime folds it into the button `value`) pass it
        back here rather than relying on the cache alone.
        """
        if agent_url:
            base_url = agent_url.rstrip("/").removesuffix("/a2a")
            self._known_bases[thread_id] = base_url
        else:
            base_url = self._known_bases.get(thread_id)
        if base_url is None:
            raise RuntimeError(
                f"resume_turn: no known base URL for thread {thread_id} "
                "(send_turn/stream_turn must be called for this thread first, "
                "or pass agent_url explicitly)"
            )
        chunks: list[str] = []
        saw_terminal = False
        async with httpx.AsyncClient() as client:
            try:
                async with client.stream(
                    "POST",
                    f"{base_url}/v1/_vystak/resume",
                    json={"thread_id": thread_id, "resume": resume},
                    timeout=self._resume_timeout,
                ) as resp:
                    if resp.status_code != 200:
                        raise RuntimeError(
                            f"resume {thread_id} returned {resp.status_code}"
                        )
                    async for line in resp.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        data = line[len("data:") :].strip()
                        if data == "[DONE]":
                            saw_terminal = True
                            break
                        try:
                            event = json.loads(data)
                        except json.JSONDecodeError:
                            continue
                        ev_type = event.get("type")
                        if ev_type == "response.output_text.delta":
                            chunks.append(event.get("delta", ""))
                        elif ev_type in ("response.completed", "response.failed"):
                            saw_terminal = True
            except httpx.HTTPError as exc:
                # Broader than send_turn/stream_turn's ConnectError/ReadTimeout
                # pair on purpose (Important-3 fix-round): resume_turn has no
                # retry loop, so any transport failure here — including
                # RemoteProtocolError, PoolTimeout, etc — must still surface
                # as a RuntimeError the Slack handler's `except Exception`
                # can turn into an ephemeral message, never an unhandled
                # crash that leaves the approval button dead with no
                # feedback.
                raise RuntimeError(f"resume {thread_id} failed: {exc}") from exc

            text = "".join(chunks)
            if saw_terminal:
                return AgentReply(text=text, finish_reason="completed")

            # Stream ended without a terminal event — disambiguate a
            # genuine truncation from a second park via checkpoint state.
            try:
                cp_resp = await client.get(
                    f"{base_url}/v1/_vystak/checkpoint",
                    params={"thread_id": thread_id},
                    timeout=self._resume_timeout,
                )
                cp_resp.raise_for_status()
                checkpoint = cp_resp.json()
            except Exception:  # noqa: BLE001 — best-effort probe
                checkpoint = None

        if checkpoint and checkpoint.get("interrupted") and checkpoint.get("interrupts"):
            return AgentReply(
                text=text,
                finish_reason="approval_pending",
                pending_approval={
                    "payload": checkpoint["interrupts"][0],
                    "thread_id": thread_id,
                },
            )
        raise RuntimeError(f"resume {thread_id} failed: stream ended without a terminal event")

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
            state_value = status.get("state")

            # A LangGraphExecutor interrupt (human-in-the-loop tool approval)
            # ends the task in input-required state with a single text part
            # carrying a JSON marker instead of the normal reply text. Detect
            # it before falling through to the plain-text AgentReply below.
            if state_value in ("input-required", "input_required") and text:
                try:
                    marker = json.loads(text)
                except (ValueError, TypeError):
                    marker = None
                if isinstance(marker, dict) and marker.get("kind") == "approval_pending":
                    return AgentReply(
                        text="",
                        finish_reason="approval_pending",
                        pending_approval={
                            "payload": marker.get("payload"),
                            "thread_id": marker.get("thread_id"),
                        },
                        raw=payload,
                    )

            return AgentReply(
                text=text,
                tool_calls=result.get("tool_calls", []),
                finish_reason=state_value or result.get("finish_reason"),
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

            # HITL tool-approval park (see executor.py's interrupt() handling
            # for message/stream): a TASK_STATE_INPUT_REQUIRED status update
            # whose message text is the `{"kind": "approval_pending", ...}`
            # marker JSON — same marker `_reply_from_jsonrpc` detects on the
            # non-streaming path. Must be surfaced as a typed chunk, never as
            # plain status text (the raw marker JSON must never reach a
            # channel as reply text).
            if state in ("input-required", "input_required") and text:
                try:
                    marker = json.loads(text)
                except (ValueError, TypeError):
                    marker = None
                if isinstance(marker, dict) and marker.get("kind") == "approval_pending":
                    return AgentChunk(
                        type="approval_pending",
                        delta="",
                        data={
                            "payload": marker.get("payload"),
                            "thread_id": marker.get("thread_id"),
                        },
                        finish_reason="approval_pending",
                        final=True,
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
        resume_timeout_s: float = 300.0,
    ) -> None:
        self._nats_url = nats_url
        self._timeout = timeout_s
        # responses/resumeThread can run real gated-tool work inside the RPC
        # before the graph parks/completes again — the bridge's own read
        # bound is ~300s, so the request timeout here must match rather
        # than reuse the short `_timeout` used for message/send.
        self._resume_timeout = resume_timeout_s
        # Lazy-initialised on first call. Re-used across requests so we
        # don't pay reconnect cost per turn.
        self._nc: Any = None
        self._connect_lock: asyncio.Lock | None = None
        # thread_id -> NATS subject, learned from the most recent send_turn
        # call for that thread. resume_turn has no agent_url parameter (see
        # A2AAgentClient.resume_turn docstring for the same contract), so
        # it looks the subject up here.
        self._known_subjects: dict[str, str] = {}

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
        self._known_subjects[thread_id] = subject
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
        result = A2AAgentClient._reply_from_jsonrpc(data)
        # See A2AAgentClient.send_turn's matching comment: the
        # approval_pending marker's thread_id is the agent's LangGraph
        # checkpoint key, not the contextId this call sent — alias it to
        # the same subject so resume_turn can find it.
        pa_tid = (result.pending_approval or {}).get("thread_id")
        if pa_tid:
            self._known_subjects[pa_tid] = subject
        return result

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
        if reply.pending_approval:
            # HITL tool-approval park: send_turn already produced a typed
            # AgentReply.pending_approval (and already aliased the marker's
            # thread_id to this subject) -- carry it through as a typed
            # chunk rather than a "final" chunk whose delta would otherwise
            # be empty and silently drop the marker (Task 11 streaming fix).
            yield AgentChunk(
                type="approval_pending",
                delta="",
                data=reply.pending_approval,
                finish_reason="approval_pending",
                final=True,
                raw=reply.raw,
            )
            return
        yield AgentChunk(
            type="final",
            delta=reply.text,
            finish_reason=reply.finish_reason or "completed",
            final=True,
            raw=reply.raw,
        )

    async def resume_turn(
        self, thread_id: str, resume: dict[str, Any], agent_url: str | None = None
    ) -> AgentReply:
        """Send `responses/resumeThread {thread_id, resume}` and map the
        bridge's reply — `{"text": str, "pending_approval": null | {...}}`
        (see `nats_bridge._handle_resume_thread`) — onto an `AgentReply`.

        Deviation from the original brief (`-> str`): same rationale as
        `A2AAgentClient.resume_turn` — chaining requires surfacing a
        possible re-park uniformly. `-32000` from the bridge (a genuine
        failure, including "stream ended without a terminal event" that
        checkpoint state couldn't explain) raises `RuntimeError`, mirroring
        the brief's pseudocode exactly (not `AgentCallError` — the Slack
        action handler's "already resolved" branch is keyed on
        `RuntimeError`).

        `agent_url` here is the NATS subject hint (same parameter name as
        `A2AAgentClient.resume_turn` for a uniform `AgentClient` protocol) —
        overrides and refreshes `_known_subjects[thread_id]`, which is
        process-local and empty after a channel restart even though the
        agent-side park is durable.
        """
        if agent_url:
            subject = agent_url
            self._known_subjects[thread_id] = subject
        else:
            subject = self._known_subjects.get(thread_id)
        if subject is None:
            raise RuntimeError(
                f"resume_turn: no known subject for thread {thread_id} "
                "(send_turn must be called for this thread first, or pass "
                "agent_url explicitly)"
            )
        request_id = str(uuid.uuid4())
        body = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "responses/resumeThread",
            "params": {"thread_id": thread_id, "resume": resume},
        }
        try:
            nc = await self._connect()
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"nats connect to {self._nats_url} failed: {exc}") from exc

        payload = json.dumps(body).encode()
        try:
            reply = await nc.request(subject, payload, timeout=self._resume_timeout)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"nats resume request to {subject} failed: {exc}") from exc

        try:
            data = json.loads(reply.data)
        except (json.JSONDecodeError, ValueError) as exc:
            raise RuntimeError(
                f"nats resume reply from {subject} not valid JSON: {exc}",
            ) from exc

        if "error" in data:
            raise RuntimeError(data["error"].get("message", "resume failed"))

        result = data.get("result") or {}
        pending_approval = result.get("pending_approval")
        return AgentReply(
            text=result.get("text", ""),
            finish_reason="approval_pending" if pending_approval else "completed",
            pending_approval=pending_approval,
        )
