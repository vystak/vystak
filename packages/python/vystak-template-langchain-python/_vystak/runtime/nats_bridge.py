"""NATS↔HTTP bridge for agents on the NATS transport.

When ``VYSTAK_TRANSPORT_TYPE=nats``, agents listen on a NATS subject
instead of (in addition to) HTTP. This module is the thin proxy that:

1. Subscribes to the agent's own subject (``VYSTAK_NATS_SUBJECT``) in a
   queue group so multiple replicas of the same agent share work.
2. For each inbound JSON-RPC envelope, POSTs the bytes to the local
   FastAPI app at ``http://localhost:<own-port>/a2a`` — the same path
   the a2a-sdk's ``DefaultRequestHandlerV2`` is mounted on.
3. Publishes the HTTP response body back as the NATS reply.

This keeps all of the SDK's request-handler plumbing
(DefaultRequestHandlerV2, executor, task store, agent card) intact and
unduplicated. The cost is one extra in-container HTTP hop per request
on a localhost loopback — microseconds.

Design choice: the bridge is a thin proxy, not a parallel
JSON-RPC dispatcher. The alternative (rebuild a2a-sdk request routing
inside the bridge) would double-implement the SDK's full method
surface. With this design, adding a new SDK-handled method works for
both transports automatically.

Streaming (``message/stream``) is NOT implemented over NATS in v1.
The bridge handles single-shot ``message/send`` (and any other
single-reply JSON-RPC methods the SDK exposes on /a2a). Multi-message
streaming over NATS would need an inbox-subscription pattern; deferred
until a real use case lands.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
from typing import TYPE_CHECKING, Any

import httpx

if TYPE_CHECKING:
    from _vystak.runtime.turn_journal import TurnJournal, TurnRecord

logger = logging.getLogger("vystak.runtime.nats_bridge")

# Caps how many times a single turn will be re-driven after a restart before
# it's given up on and marked failed. Bounds a permanently-broken turn (e.g.
# one whose resume endpoint always errors) from being retried forever.
MAX_REDRIVE_ATTEMPTS = 3

_DATA_DIR = "/data"


def resolve_turns_path() -> str:
    """Resolve the durable turn-journal's SQLite path.

    The journal is always SQLite (independent of whichever engine the
    session checkpointer uses) at `/data/turns.db` in a deployed container.
    Chain: `VYSTAK_TURNS_PATH` -> `/data/turns.db` (when `/data` exists and
    is writable) -> a temp-dir path (unit tests, dev machines, and any
    platform that mounts no volume). Mirrors `resolve_sessions_path` in
    `store.py`.
    """
    override = os.environ.get("VYSTAK_TURNS_PATH")
    if override:
        return override
    if os.path.isdir(_DATA_DIR) and os.access(_DATA_DIR, os.W_OK):
        return os.path.join(_DATA_DIR, "turns.db")
    return os.path.join(tempfile.gettempdir(), "vystak-turns.db")


class NatsHttpBridge:
    """Subscribes to a NATS subject and proxies to the local /a2a endpoint."""

    def __init__(
        self,
        *,
        nats_url: str,
        subject: str,
        queue_group: str,
        local_url: str,
        local_base: str = "",
        journal: TurnJournal | None = None,
    ) -> None:
        self._nats_url = nats_url
        self._subject = subject
        self._queue_group = queue_group
        self._local_url = local_url
        self._journal = journal
        # Base URL of the local FastAPI app (no path), used for the
        # Responses-API proxy routes below. Falls back to deriving it from
        # local_url (the /a2a URL) so existing callers that only pass
        # local_url keep working.
        self._local_base = local_base or local_url.removesuffix("/a2a")
        self._nc: Any = None
        self._sub: Any = None
        self._http: httpx.AsyncClient | None = None
        # Tracks in-flight forward-and-reply tasks so shutdown can drain.
        self._inflight: set[asyncio.Task] = set()
        # The startup re-drive sweep's background task, tracked separately
        # from `_inflight`: it can legitimately be waiting on
        # `_wait_until_ready` for up to its own timeout, and shutdown
        # should cancel it outright rather than making every stop() pay
        # that wait (see `stop()`).
        self._redrive_task: asyncio.Task | None = None
        # Snapshot of turn_ids the journal considered `running` *before*
        # this process subscribed — i.e. leftovers from a prior process,
        # nothing this process is handling live. Taken in `start()` right
        # before `subscribe()`. The (delayed, readiness-gated) sweep only
        # ever re-drives turn_ids in this set, so a `responses/createDetached`
        # that arrives after subscribe — and is handled live by
        # `_run_detached` concurrently with the sweep — can never also be
        # picked up by the sweep. `None` (the default, used by every caller
        # that invokes `redrive_unfinished()` directly without going through
        # `start()`, e.g. tests) means "no restriction" — every `running`
        # turn is eligible.
        self._orphaned_turn_ids: set[str] | None = None

    async def start(self) -> None:
        """Connect to NATS, subscribe, and return. Subscription callbacks
        run forever in the nats-py client task; the caller is expected
        to keep the FastAPI app alive."""
        import nats

        logger.info(
            "nats_bridge.start url=%s subject=%s queue=%s local=%s",
            self._nats_url,
            self._subject,
            self._queue_group,
            self._local_url,
        )
        self._nc = await nats.connect(self._nats_url)
        # Localhost loopback HTTP client. Re-used across requests to
        # avoid per-message connection setup. Bridge timeout exceeds
        # typical agent latency (LLM round-trips + tool calls).
        self._http = httpx.AsyncClient(timeout=httpx.Timeout(120.0))
        # Snapshot the orphan set *before* subscribing: every row the
        # journal considers `running` at this instant predates this
        # process — nothing here can be handling it yet, since we haven't
        # subscribed (and therefore can't have received a message) yet.
        # This is the invariant the sweep relies on: it only ever touches
        # turns that predate this process's subscribe, so it can never
        # race a live `_run_detached` handling a turn that arrives after.
        if self._journal is not None:
            self._orphaned_turn_ids = {r.turn_id for r in await self._journal.list_running()}
        else:
            self._orphaned_turn_ids = set()
        self._sub = await self._nc.subscribe(
            self._subject,
            queue=self._queue_group,
            cb=self._on_message,
        )
        logger.info("nats_bridge.subscribed subject=%s", self._subject)
        # Re-drive any turns a prior process left mid-flight (crash/restart).
        # This can't run synchronously here: the sweep needs the local agent's
        # own HTTP server (GET /v1/_vystak/checkpoint, POST /v1/_vystak/resume)
        # to be accepting connections, and uvicorn only starts accepting
        # connections *after* FastAPI's lifespan startup — this coroutine —
        # returns. Run it as a background task that waits for /healthz first.
        self._redrive_task = asyncio.create_task(self._redrive_after_ready())

    async def _wait_until_ready(self, *, timeout: float = 30.0, interval: float = 0.25) -> bool:
        """Poll the local agent's own `/healthz` until it answers 200, or
        `timeout` seconds elapse. See `start()` for why this can't be
        skipped: the socket isn't open yet when `start()` runs."""
        assert self._http is not None
        loop = asyncio.get_event_loop()
        deadline = loop.time() + timeout
        while True:
            try:
                resp = await self._http.get(
                    f"{self._local_base}/healthz", timeout=httpx.Timeout(2.0)
                )
                if resp.status_code == 200:
                    return True
            except Exception:  # noqa: BLE001 — server not up yet, keep polling
                pass
            if loop.time() >= deadline:
                return False
            await asyncio.sleep(interval)

    async def _redrive_after_ready(self) -> None:
        """Background task launched from `start()`: wait for the local
        server, then sweep. Startup must never crash on this — a redrive
        failure is recoverable on the next restart, an unhandled exception
        here is not (it would just be a silently-dead background task
        either way, but the try/except makes that explicit)."""
        if not await self._wait_until_ready():
            logger.warning("nats_bridge.redrive_skipped_server_not_ready")
            return
        try:
            redriven = await self.redrive_unfinished()
            if redriven:
                logger.info("nats_bridge.redrove_unfinished count=%d", redriven)
        except Exception:  # noqa: BLE001
            logger.exception("nats_bridge.redrive_unfinished_failed")

    async def _on_message(self, msg: Any) -> None:
        """Forward one inbound NATS message → local /a2a → reply on inbox.

        We launch each forwarding as a task so concurrent inbound
        messages don't serialize. The task is tracked so shutdown
        can await drain.
        """
        task = asyncio.create_task(self._forward(msg))
        self._inflight.add(task)
        task.add_done_callback(self._inflight.discard)

    async def _forward(self, msg: Any) -> None:
        reply_subject = getattr(msg, "reply", "") or ""
        try:
            body = msg.data
            if not body:
                await self._publish_error_async(
                    reply_subject,
                    code=-32700,
                    message="empty payload",
                )
                return
            try:
                envelope = json.loads(body)
            except json.JSONDecodeError as e:
                await self._publish_error_async(
                    reply_subject,
                    code=-32700,
                    message=f"parse error: {e}",
                )
                return
            request_id = envelope.get("id")
            method = envelope.get("method", "?")
            logger.debug(
                "nats_bridge.inbound method=%s id=%s bytes=%d",
                method,
                request_id,
                len(body),
            )

            if method == "responses/create":
                await self._handle_responses_create(envelope, reply_subject)
                return
            if method == "responses/get":
                await self._handle_responses_get(envelope, reply_subject)
                return
            if method == "responses/createDetached":
                await self._handle_responses_create_detached(envelope, reply_subject)
                return
            if method == "responses/turnStatus":
                await self._handle_turn_status(envelope, reply_subject)
                return
            if method == "responses/resumeDetached":
                await self._handle_resume_detached(envelope, reply_subject)
                return
            if method == "responses/resumeThread":
                await self._handle_resume_thread(envelope, reply_subject)
                return

            # Extract the upstream W3C traceparent (if any) so the local
            # /a2a call continues the same trace. The publisher
            # (subagents._make_nats_tool / NatsAgentClient.send_turn)
            # writes traceparent into params.message.metadata; we
            # re-attach it as an HTTP Authorization-equivalent header so
            # the FastAPIInstrumentor on the receiving end picks it up.
            metadata = (envelope.get("params") or {}).get("message", {}).get("metadata") or {}
            await self._forward_with_trace_context(
                envelope=envelope,
                body=body,
                metadata=metadata,
                reply_subject=reply_subject,
                request_id=request_id,
                msg_subject=getattr(msg, "subject", "") or "",
            )
        except Exception:
            logger.exception("nats_bridge.unhandled")
            # Last-ditch: best-effort error publish without re-raising.
            await self._publish_error_async(
                reply_subject,
                code=-32603,
                message="bridge internal error",
            )

    async def _forward_with_trace_context(
        self,
        *,
        envelope: dict[str, Any],
        body: bytes,
        metadata: dict[str, Any],
        reply_subject: str,
        request_id: Any,
        msg_subject: str,
    ) -> None:
        """Forward to local /a2a inside the (optional) extracted span context.

        Two OTel touchpoints:

        1. ``otel_context.attach(extract(metadata))`` — restores the
           upstream trace context so the local httpx + FastAPI
           auto-instrumentation creates spans under the same root.
        2. A ``nats.receive`` span around the forward so the broker
           hop is visible in the trace.

        When OTel isn't initialized, both are no-ops.
        """
        try:
            from opentelemetry import context as otel_context
            from opentelemetry import trace as otel_trace
            from opentelemetry.propagate import extract

            ctx = extract(metadata)
            token = otel_context.attach(ctx)
            tracer = otel_trace.get_tracer("vystak.runtime.nats_bridge")
        except Exception:  # noqa: BLE001
            ctx = None
            token = None
            tracer = None  # type: ignore[assignment]

        try:
            if tracer is not None:
                span_cm = tracer.start_as_current_span(
                    f"nats.receive {msg_subject or '?'}",
                    attributes={
                        "messaging.system": "nats",
                        "messaging.destination": msg_subject,
                        "messaging.operation": "receive",
                    },
                )
            else:
                from contextlib import nullcontext

                span_cm = nullcontext()
            with span_cm:
                # Pass traceparent to the local httpx call as a header so
                # FastAPIInstrumentor on the receiving FastAPI app picks
                # it up. HTTPXClientInstrumentor will also inject from
                # the active context, but explicit header passing is a
                # belt-and-braces guarantee.
                trace_headers: dict[str, str] = {}
                try:
                    from opentelemetry.propagate import inject

                    inject(trace_headers)
                except Exception:  # noqa: BLE001
                    pass
                headers = {"Content-Type": "application/json", **trace_headers}
                assert self._http is not None  # set by start()
                try:
                    resp = await self._http.post(
                        self._local_url,
                        content=body,
                        headers=headers,
                    )
                except (
                    httpx.ConnectError,
                    httpx.ReadTimeout,
                    httpx.HTTPError,
                ) as e:
                    logger.exception("nats_bridge.local_http_error")
                    await self._publish_error_async(
                        reply_subject,
                        code=-32603,
                        message=f"local /a2a request failed: {e}",
                        request_id=request_id,
                    )
                    return

                payload = (
                    resp.content
                    if resp.status_code == 200
                    else self._error_envelope_bytes(
                        request_id=request_id,
                        code=-32603,
                        message=f"local /a2a returned {resp.status_code}",
                    )
                )
                if reply_subject:
                    await self._nc.publish(reply_subject, payload)
        finally:
            if token is not None:
                try:
                    from opentelemetry import context as otel_context

                    otel_context.detach(token)
                except Exception:  # noqa: BLE001
                    pass

    async def _handle_responses_create(self, envelope: dict[str, Any], reply_subject: str) -> None:
        """Proxy responses/create to the local /v1/responses (non-stream).

        Streaming is not supported over the NATS bridge (single-reply
        JSON-RPC only), so the outbound request is forced to
        ``stream: False`` regardless of what the caller asked for.
        """
        request = dict((envelope.get("params") or {}).get("request") or {})
        request["stream"] = False
        assert self._http is not None  # set by start()
        try:
            resp = await self._http.post(f"{self._local_base}/v1/responses", json=request)
            resp.raise_for_status()
            result = resp.json()
        except Exception as e:  # noqa: BLE001 — reply with JSON-RPC error, never raise
            await self._publish_error_async(
                reply_subject,
                code=-32603,
                message=f"responses/create failed: {e}",
                request_id=envelope.get("id"),
            )
            return
        reply = {"jsonrpc": "2.0", "id": envelope.get("id"), "result": result}
        if reply_subject:
            await self._nc.publish(reply_subject, json.dumps(reply).encode())

    async def _handle_responses_get(self, envelope: dict[str, Any], reply_subject: str) -> None:
        """Proxy responses/get to the local GET /v1/responses/{id}.

        A 404 from the local endpoint (unknown response id) maps to a
        successful JSON-RPC reply with ``result: null`` rather than an
        error — "not found" is a valid answer for this lookup.
        """
        response_id = (envelope.get("params") or {}).get("response_id") or ""
        assert self._http is not None  # set by start()
        result: Any = None
        try:
            resp = await self._http.get(f"{self._local_base}/v1/responses/{response_id}")
            if resp.status_code == 200:
                result = resp.json()
            elif resp.status_code != 404:
                resp.raise_for_status()
        except Exception as e:  # noqa: BLE001
            await self._publish_error_async(
                reply_subject,
                code=-32603,
                message=f"responses/get failed: {e}",
                request_id=envelope.get("id"),
            )
            return
        reply = {"jsonrpc": "2.0", "id": envelope.get("id"), "result": result}
        if reply_subject:
            await self._nc.publish(reply_subject, json.dumps(reply).encode())

    async def _handle_responses_create_detached(
        self, envelope: dict[str, Any], reply_subject: str
    ) -> None:
        """Ack immediately, then run the turn to completion publishing every
        Responses SSE event durably to JetStream — the turn's lifetime is
        decoupled from the requester (and from any browser)."""
        params = envelope.get("params") or {}
        request = params.get("request")
        turn_id = params.get("turn_id")
        stream_subject = params.get("stream_subject")
        if not request or not turn_id or not stream_subject:
            await self._publish_error_async(
                reply_subject,
                code=-32602,
                message="responses/createDetached requires request, turn_id, stream_subject",
                request_id=envelope.get("id"),
            )
            return
        # Journal row created BEFORE the ack is published: the crash
        # window (bridge dies after ack but before the row exists) is
        # then one INSERT wide instead of spanning the whole detached run.
        if self._journal is not None:
            await self._journal.create(turn_id, stream_subject, request)
        ack = {
            "jsonrpc": "2.0",
            "id": envelope.get("id"),
            "result": {"turn_id": turn_id, "stream_subject": stream_subject},
        }
        if reply_subject:
            await self._nc.publish(reply_subject, json.dumps(ack).encode())
        task = asyncio.create_task(self._run_detached(dict(request), stream_subject, turn_id))
        self._inflight.add(task)
        task.add_done_callback(self._inflight.discard)

    async def _handle_turn_status(self, envelope: dict[str, Any], reply_subject: str) -> None:
        """`responses/turnStatus {turn_id}` — a journal lookup; `unknown`
        covers both a never-seen turn_id and a journal-less bridge (HTTP
        transport doesn't build one). When the row is `parked`, also makes
        one HTTP hop to `GET /v1/_vystak/checkpoint` (via
        `_agent_checkpoint_state`) to surface the first pending interrupt
        payload — `self._http` is always set by this point (assigned in
        `start()` before the NATS subscription that can deliver this
        envelope)."""
        params = envelope.get("params") or {}
        rec = await self._journal.get(params.get("turn_id", "")) if self._journal else None
        interrupt_payload = None
        if rec is not None and rec.status == "parked":
            state = await self._agent_checkpoint_state(rec.thread_id)
            if state and state.get("interrupts"):
                interrupt_payload = state["interrupts"][0]
        await self._publish_result(
            reply_subject, envelope.get("id"),
            {"status": rec.status if rec else "unknown", "interrupt": interrupt_payload},
        )

    async def _handle_resume_detached(
        self, envelope: dict[str, Any], reply_subject: str
    ) -> None:
        """`responses/resumeDetached {turn_id, resume}` — ack immediately,
        then continue a parked turn from where it left off. Unlike a
        crash re-drive, nothing was lost here (the graph is sitting at an
        `interrupt()`, checkpointed by LangGraph itself), so there is no
        rewind marker to publish and no seq to discard — just append from
        `rec.last_seq + 1` onward."""
        params = envelope.get("params") or {}
        turn_id = params.get("turn_id", "")
        rec = await self._journal.get(turn_id) if self._journal is not None else None
        if rec is None:
            await self._publish_error_async(
                reply_subject,
                code=-32602,
                message=f"unknown turn_id: {turn_id}",
                request_id=envelope.get("id"),
            )
            return
        if rec.status != "parked":
            await self._publish_error_async(
                reply_subject,
                code=-32602,
                message="turn is not parked",
                request_id=envelope.get("id"),
            )
            return
        if self._journal is not None:
            await self._journal.set_status(turn_id, "running")
        await self._publish_result(
            reply_subject, envelope.get("id"), {"turn_id": turn_id}
        )
        task = asyncio.create_task(
            self._stream_from_resume_endpoint(
                rec,
                start_seq=rec.last_seq + 1,
                # No rewind happened, so the original `response.created`
                # published before the park is still what every consumer
                # retains. `resume_stream` always re-emits one — it's a
                # duplicate here (unlike a post-rewind redrive where it can
                # be the only surviving copy) — so pass any `to_seq >= 0`
                # to keep `_consume_response_stream` suppressing it. `0` is
                # a pure boolean sentinel here, not a real rewind target
                # (resumeDetached never publishes a `vystak.turn.rewind`).
                to_seq=0,
                resume=params.get("resume"),
            )
        )
        self._inflight.add(task)
        task.add_done_callback(self._inflight.discard)

    async def _handle_resume_thread(self, envelope: dict, reply_subject: str) -> None:
        """`responses/resumeThread {thread_id, resume}` — resume a parked
        A2A-originated thread and reply with the final assistant text.

        A2A turns have no detached-journal row (no `turn_id`, no
        `stream_subject`), so this is keyed by `thread_id` alone. The
        caller (a channel runtime, e.g. Slack) blocks on the JSON-RPC
        reply the same way it blocks on `message/send` — no ack/park
        split, no JetStream publish, just POST-and-collect. Because a
        gated tool can run real work before the graph parks again, this
        RPC can take as long as the resume endpoint's read bound (see
        `_resume_and_collect_text`'s ~300s timeout) — NATS callers must
        set a request timeout comparable to that, not the short timeout
        used for `message/send`.

        Task-11 chaining contract: the reply always carries
        `pending_approval`, `null` on normal completion. When the resumed
        run parks AGAIN on a second gated tool, the SSE ends with no
        terminal event (`response.completed`/`response.failed`) — that by
        itself is indistinguishable from a genuine failure, so this
        consults `_agent_checkpoint_state(thread_id)` (the same tri-state
        helper `_consume_response_stream` uses for the detached path) to
        tell the two apart:
          - stream ended with a terminal event: normal completion,
            `pending_approval: null`.
          - stream ended without one, and the checkpoint state says the
            graph is durably parked with a pending interrupt: reply
            success with the partial text collected so far and
            `pending_approval: {"payload": <interrupt value>, "thread_id":
            ...}` — the Slack handler (Task 11) posts a NEW approval
            message for this rather than treating it as done.
          - stream ended without one, and the checkpoint state says
            otherwise (not interrupted, or couldn't be consulted): a
            genuine failure — reply `-32000`, never fake a success with a
            silently-dropped partial message.
        """
        params = envelope.get("params") or {}
        thread_id = params.get("thread_id")
        if not thread_id:
            await self._publish_error_async(
                reply_subject,
                code=-32602,
                message="thread_id required",
                request_id=envelope.get("id"),
            )
            return
        try:
            text, saw_terminal = await self._resume_and_collect_text(
                thread_id, params.get("resume")
            )
        except Exception as e:  # noqa: BLE001 — surface as JSON-RPC error, never raise
            await self._publish_error_async(
                reply_subject,
                code=-32000,
                message=f"resume failed: {e}",
                request_id=envelope.get("id"),
            )
            return
        if saw_terminal:
            await self._publish_result(
                reply_subject, envelope.get("id"), {"text": text, "pending_approval": None}
            )
            return
        state = await self._agent_checkpoint_state(thread_id)
        if state is not None and state.get("interrupted") and state.get("interrupts"):
            await self._publish_result(
                reply_subject,
                envelope.get("id"),
                {
                    "text": text,
                    "pending_approval": {
                        "payload": state["interrupts"][0],
                        "thread_id": thread_id,
                    },
                },
            )
            return
        await self._publish_error_async(
            reply_subject,
            code=-32000,
            message="resume failed: stream ended without a terminal event",
            request_id=envelope.get("id"),
        )

    async def _resume_and_collect_text(self, thread_id: str, resume: Any) -> tuple[str, bool]:
        """POST `/v1/_vystak/resume` and concatenate every
        `response.output_text.delta` into the final assistant text.

        Reuses the bridge's shared `self._http` client and `self._local_base`
        URL derivation (same as `_stream_from_resume_endpoint`) rather than
        constructing a new client. The read timeout is the same generous
        bound the detached resume path uses — real tool work can run during
        the parked step before it completes.

        Returns `(text, saw_terminal)` — `saw_terminal` is `True` only if a
        `response.completed`/`response.failed` event or `[DONE]` was
        observed; the caller (`_handle_resume_thread`) uses `False` as the
        signal to go consult checkpoint state, mirroring how
        `_consume_response_stream` disambiguates a park from a truncation."""
        assert self._http is not None
        chunks: list[str] = []
        saw_terminal = False
        async with self._http.stream(
            "POST",
            f"{self._local_base}/v1/_vystak/resume",
            json={"thread_id": thread_id, "resume": resume},
            timeout=httpx.Timeout(None, connect=10.0, read=300.0),
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[len("data:") :].strip()
                if data == "[DONE]":
                    saw_terminal = True
                    break
                event = json.loads(data)
                event_type = event.get("type")
                if event_type == "response.output_text.delta":
                    chunks.append(event.get("delta", ""))
                elif event_type in ("response.completed", "response.failed"):
                    saw_terminal = True
        return "".join(chunks), saw_terminal

    async def _publish_result(
        self, reply_subject: str, request_id: Any, result: Any
    ) -> None:
        """Publish a successful JSON-RPC reply. No-op when the inbound
        message had no reply subject (fire-and-forget)."""
        if not reply_subject or self._nc is None:
            return
        reply = {"jsonrpc": "2.0", "id": request_id, "result": result}
        await self._nc.publish(reply_subject, json.dumps(reply).encode())

    @staticmethod
    def _make_publisher(js: Any, stream_subject: str, start_seq: int = 0) -> Any:
        """Build an async `publish(event) -> int` closure over a JetStream
        publish sequence, starting at `start_seq`. Returns the seq the event
        was assigned (i.e. "post-increments": the counter advances after
        each call, but the return value is the seq just used) so callers can
        journal `last_seq` and checkpoint boundaries against it.
        """
        seq = start_seq

        async def publish(event: dict) -> int:
            nonlocal seq
            assigned = seq
            await js.publish(stream_subject, json.dumps({"seq": seq, "event": event}).encode())
            seq += 1
            return assigned

        return publish

    async def _consume_response_stream(
        self,
        resp: httpx.Response,
        turn_id: str,
        publish: Any,
        *,
        suppress_created: bool = False,
    ) -> None:
        """Shared SSE-consumption loop for both a live detached run
        (`_run_detached`) and a re-driven resume (`_stream_from_resume_endpoint`).

        Handles `vystak.checkpoint` markers (record boundary, never
        published), captures `thread_id` from `response.created`, publishes
        every other event to JetStream, and journals `last_seq` / terminal
        status after each publish. A stream that ends without `[DONE]` or a
        terminal event is ambiguous: it could be a graph that just parked on
        `interrupt()` (nothing wrong — the turn is waiting on
        `responses/resumeDetached`), a genuine crash/truncation, or simply
        a window where the agent can't be asked yet/anymore (see below).
        This is resolved by asking the agent's own checkpoint state
        (`GET /v1/_vystak/checkpoint`) — a tri-state answer:
          - Got an answer, `interrupted: True` (`next` is non-empty on the
            LangGraph state): the graph is durably parked. Row stamped
            `parked`, *no* terminal event is published (the panel's
            `turnStatus`/`resumeDetached` poll is what keeps consumers
            waiting, not a stream event).
          - Got an answer, `interrupted: False`: a genuine failure. Row
            stamped `failed`, synthetic `response.failed` published so
            consumers terminate.
          - Couldn't ask at all (no `thread_id` yet, or the GET itself
            failed — e.g. mid-restart) — `_agent_checkpoint_state` returns
            `None`: status is left untouched (stays `running`), same as
            every other transient/infra failure in this file, so
            `redrive_unfinished()` can retry the turn; no synthetic failure
            is published either. Not stamped `failed` — that would remove
            it from `list_running()`'s re-drive sweep for good.
        This only runs when a journal is configured — an HTTP-only bridge
        has neither a journal nor anything to park.

        `suppress_created`: `resume_stream` always re-emits a
        `response.created` for the resumed thread. On a live detached run
        that's the original, first-ever event and must publish. On a
        re-drive it's a *duplicate* of the one already published before the
        crash — publish it again only when the rewind discarded the
        original (`to_seq < 0`); otherwise the caller passes
        `suppress_created=True` and this drops it, same as a checkpoint
        marker (thread_id capture still happens; it's a no-op re-write of
        the same id).
        """
        last_seq: int | None = None
        saw_terminal_event = False
        async for line in resp.aiter_lines():
            if not line.startswith("data: "):
                continue
            data_str = line[6:]
            if data_str == "[DONE]":
                return
            try:
                event = json.loads(data_str)
            except json.JSONDecodeError:
                continue

            if event.get("type") == "vystak.checkpoint":
                if self._journal is not None and last_seq is not None:
                    await self._journal.record_boundary(
                        turn_id, event.get("checkpoint_id", ""), last_seq
                    )
                continue  # internal: never published to JetStream

            if event.get("type") == "response.created":
                response_id = event.get("response", {}).get("id", "")
                if response_id and self._journal is not None:
                    await self._journal.set_thread_id(turn_id, response_id)
                if suppress_created:
                    continue  # duplicate of the pre-crash original; drop it

            last_seq = await publish(event)
            event_type = event.get("type")
            if event_type in ("response.completed", "response.failed"):
                # Tracked regardless of journal presence — an HTTP-only
                # bridge (no journal) must not fall into the truncated-
                # stream tail below just because it has nowhere to record
                # status.
                saw_terminal_event = True
            if self._journal is not None:
                await self._journal.set_last_seq(turn_id, last_seq)
                if event_type == "response.completed":
                    await self._journal.set_status(turn_id, "done")
                elif event_type == "response.failed":
                    await self._journal.set_status(turn_id, "failed")

        if saw_terminal_event:
            # Stream ended right after a terminal event without a trailing
            # `[DONE]` — status already recorded above; nothing left to do.
            return

        if self._journal is not None:
            rec = await self._journal.get(turn_id)
            state = await self._agent_checkpoint_state(rec.thread_id if rec else None)
            if state is None:
                # Couldn't ask — no thread_id yet (truncated before
                # `response.created`), or the checkpoint GET itself failed
                # (e.g. the agent process is mid-restart: clean EOF on the
                # response stream, then the follow-up GET is refused). Both
                # are healthy-turn windows, not evidence of a genuine
                # failure. Leave status untouched (it stays `running`, same
                # transient/infra-failure convention as every other error
                # path in this file) so `redrive_unfinished()` can retry —
                # and skip the synthetic `response.failed` below too: a
                # redrive will rewind/replay or eventually cap out at
                # `MAX_REDRIVE_ATTEMPTS` and publish its own failure.
                return
            if state.get("interrupted"):
                await self._journal.set_status(turn_id, "parked")
                interrupts = state.get("interrupts") or []
                if interrupts:
                    # Non-terminal seq'd event so a polling/subscribed
                    # consumer learns a tool call is awaiting approval.
                    # Mirrors the truncated-tail publish below: publish via
                    # the same seq-counter closure, then advance the
                    # journal's last_seq so a later resume continues after
                    # this event.
                    seq = await publish(
                        {"type": "vystak.approval.requested", "payload": interrupts[0]}
                    )
                    await self._journal.set_last_seq(turn_id, seq)
                return  # graph is durably parked; no terminal event to publish
            await self._journal.set_status(turn_id, "failed")

        # Truncated stream (no [DONE], no terminal event, not a park, and
        # not a "couldn't ask" window): make sure consumers still terminate.
        final_seq = await publish(_failed_event("agent stream ended without a terminal event"))
        if self._journal is not None:
            await self._journal.set_last_seq(turn_id, final_seq)

    async def _run_detached(
        self, request: dict[str, Any], stream_subject: str, turn_id: str
    ) -> None:
        try:
            js = self._nc.jetstream()
        except Exception:
            # No JetStream context means no one can publish OR consume —
            # there's no subject to carry a failure event to.
            logger.exception("nats_bridge.detached_jetstream_failed")
            return
        publish = self._make_publisher(js, stream_subject)

        try:
            await _ensure_turn_stream(js, _stream_base_of_turn_subject(stream_subject))
        except Exception as e:
            logger.exception("nats_bridge.detached_ensure_stream_failed")
            # The stream may still exist and be publishable (e.g. add_stream
            # hit a config conflict, then update_stream also failed) — make
            # a best-effort attempt so the consumer doesn't hang until its
            # idle timeout.
            try:
                seq = await publish(_failed_event(str(e)))
                if self._journal is not None:
                    # Not stamped `failed` here: Task 7 owns re-drive
                    # semantics via list_running(), and this is exactly
                    # the kind of transient/infra failure re-drive exists
                    # to recover — leaving status `running` keeps the
                    # turn eligible for that sweep.
                    await self._journal.set_last_seq(turn_id, seq)
            except Exception:  # noqa: BLE001 — nothing left to do
                logger.exception("nats_bridge.detached_ensure_stream_publish_failed")
            return
        request["stream"] = True
        assert self._http is not None
        try:
            async with self._http.stream(
                "POST",
                f"{self._local_base}/v1/responses",
                json=request,
                # Long-lived LLM stream: the client-level 120s total timeout
                # would kill slow turns; only bound connect + inter-chunk read.
                timeout=httpx.Timeout(None, connect=10.0, read=300.0),
            ) as resp:
                if resp.status_code != 200:
                    seq = await publish(
                        _failed_event(f"local /v1/responses returned {resp.status_code}")
                    )
                    # Left `running` — see the ensure-stream failure comment
                    # above; this is a re-drive candidate, not a terminal
                    # failure.
                    if self._journal is not None:
                        await self._journal.set_last_seq(turn_id, seq)
                    return
                await self._consume_response_stream(resp, turn_id, publish)
        except Exception as e:  # noqa: BLE001 — the failure must reach consumers
            logger.exception("nats_bridge.detached_failed")
            try:
                seq = await publish(_failed_event(str(e)))
                # Left `running` — transient/infra failure, re-drive
                # candidate (see above).
                if self._journal is not None:
                    await self._journal.set_last_seq(turn_id, seq)
            except Exception:  # noqa: BLE001 — nothing left to do
                logger.exception("nats_bridge.detached_failed_publish")

    async def _agent_checkpoint_state(self, thread_id: str | None) -> dict[str, Any] | None:
        """Ask the local agent about a thread's checkpoint state via
        `GET /v1/_vystak/checkpoint` — `{"checkpoint_id": ..., "interrupted": ...}`.

        Two-state contract callers must not conflate: returns `None` when
        there's no thread to ask about yet, or the call itself failed
        (network error, non-2xx) — "couldn't ask", not an answer. Returns
        the parsed dict on a successful call — a real answer, even if
        `interrupted` is `False` within it. See `_consume_response_stream`'s
        tri-state handling of this for why the distinction matters: `None`
        must not be treated the same as "asked and confirmed not
        interrupted"."""
        if not thread_id:
            return None
        assert self._http is not None
        try:
            resp = await self._http.get(
                f"{self._local_base}/v1/_vystak/checkpoint",
                params={"thread_id": thread_id},
            )
            resp.raise_for_status()
            return resp.json()
        except Exception:  # noqa: BLE001
            logger.exception("nats_bridge.checkpoint_state_lookup_failed")
            return None

    async def _current_checkpoint_id(self, thread_id: str | None) -> str | None:
        """Ask the local agent for the checkpoint LangGraph would resume
        from for this thread — via `GET /v1/_vystak/checkpoint`."""
        state = await self._agent_checkpoint_state(thread_id)
        return state.get("checkpoint_id") if state is not None else None

    async def _publish_seq(self, stream_subject: str, seq: int, event: dict) -> None:
        js = self._nc.jetstream()
        await js.publish(stream_subject, json.dumps({"seq": seq, "event": event}).encode())

    async def _publish_synthetic_failure(self, rec: TurnRecord, message: str) -> None:
        await self._publish_seq(rec.stream_subject, rec.last_seq + 1, _failed_event(message))

    async def _stream_from_resume_endpoint(
        self, rec: TurnRecord, *, start_seq: int, to_seq: int, resume: Any = None
    ) -> None:
        """POST `/v1/_vystak/resume` and consume the SSE stream through the
        same loop `_run_detached` uses, publishing at `start_seq` onward.

        `to_seq` is the rewind target just published for this turn: when
        `>= 0`, the original pre-crash `response.created` survived the
        rewind and the one `resume_stream` re-emits is a duplicate to drop;
        when `< 0` the rewind discarded everything and the re-emitted one
        is the only copy consumers will retain, so it must publish. A
        `responses/resumeDetached` call (see `_handle_resume_detached`)
        publishes no rewind at all — it passes a `to_seq >= 0` purely to
        select the "duplicate, drop it" branch, since the original
        `response.created` was never discarded on a park.

        `resume`: `None` replays the pending step from its last checkpoint
        (a crash re-drive); any other value drives a pending `interrupt()`
        via `langgraph.types.Command(resume=...)` on the agent side. Only
        included in the POST body when not `None`, so a plain re-drive's
        request is unchanged from before this parameter existed.
        """
        try:
            js = self._nc.jetstream()
        except Exception:
            logger.exception("nats_bridge.redrive_jetstream_failed")
            return
        publish = self._make_publisher(js, rec.stream_subject, start_seq)
        assert self._http is not None
        body: dict[str, Any] = {"thread_id": rec.thread_id}
        if resume is not None:
            body["resume"] = resume
        try:
            async with self._http.stream(
                "POST",
                f"{self._local_base}/v1/_vystak/resume",
                json=body,
                timeout=httpx.Timeout(None, connect=10.0, read=300.0),
            ) as resp:
                if resp.status_code != 200:
                    seq = await publish(
                        _failed_event(f"local /v1/_vystak/resume returned {resp.status_code}")
                    )
                    if self._journal is not None:
                        await self._journal.set_last_seq(rec.turn_id, seq)
                    return
                await self._consume_response_stream(
                    resp, rec.turn_id, publish, suppress_created=to_seq >= 0
                )
        except Exception as e:  # noqa: BLE001 — the failure must reach consumers
            logger.exception("nats_bridge.redrive_stream_failed")
            try:
                seq = await publish(_failed_event(str(e)))
                if self._journal is not None:
                    await self._journal.set_last_seq(rec.turn_id, seq)
            except Exception:  # noqa: BLE001 — nothing left to do
                logger.exception("nats_bridge.redrive_stream_failed_publish")

    async def _redrive_one(self, rec: TurnRecord) -> None:
        if not rec.thread_id:
            # response.created never arrived before the crash: there's no
            # thread the resume endpoint can drive, and never will be (a
            # fresh run would mint a new thread_id, not reuse this turn_id).
            # Give up immediately rather than publish a rewind marker for a
            # resume that's guaranteed to 400.
            await self._publish_synthetic_failure(
                rec, "turn crashed before a thread_id was captured; cannot resume"
            )
            if self._journal is not None:
                await self._journal.set_status(rec.turn_id, "failed")
            return
        checkpoint_id = await self._current_checkpoint_id(rec.thread_id)
        to_seq = None
        if self._journal is not None and checkpoint_id is not None:
            to_seq = await self._journal.seq_for_checkpoint(rec.turn_id, checkpoint_id)
        if to_seq is None:
            to_seq = rec.boundary_seq
        # Defensive clamp: a boundary write is always paired with an
        # already-committed last_seq for the same event (see
        # _consume_response_stream — record_boundary uses the `last_seq`
        # a prior set_last_seq call already persisted), so to_seq should
        # never exceed rec.last_seq in practice. Clamping anyway means a
        # stale/inconsistent journal row can't make the rewind marker's own
        # seq land at or below its own to_seq — which a consumer applying
        # "discard everything after to_seq" would otherwise misread as
        # discarding the rewind marker itself.
        to_seq = min(to_seq, rec.last_seq)
        # Same stream the live detached run publishes into — ensure it
        # exists before publishing the rewind marker, same as _run_detached
        # does for its first publish.
        js = self._nc.jetstream()
        await _ensure_turn_stream(js, _stream_base_of_turn_subject(rec.stream_subject))
        seq = rec.last_seq + 1
        await self._publish_seq(
            rec.stream_subject, seq, {"type": "vystak.turn.rewind", "to_seq": to_seq}
        )
        await self._stream_from_resume_endpoint(rec, start_seq=seq + 1, to_seq=to_seq)

    async def redrive_unfinished(self) -> int:
        """Re-drive turns the journal still considers `running` — a
        crash/restart mid-turn is the expected way to land here. Turns that
        have already exhausted `MAX_REDRIVE_ATTEMPTS` are given up on and
        marked failed instead of retried forever. Returns the number of
        turns actually re-driven (not counting turns that hit the cap or
        that raised mid-redrive — one broken turn must not abort the sweep
        of the rest).

        Only touches turns whose turn_id is in `self._orphaned_turn_ids` —
        the pre-subscribe snapshot `start()` takes — when that snapshot is
        set. This is what stops the sweep from racing a `_run_detached` that
        picks up a fresh `responses/createDetached` after subscribe: that
        turn's `running` row postdates the snapshot, so it's invisible here
        no matter how long the (readiness-gated) sweep is delayed. `None`
        (never called through `start()`, e.g. most tests) means every
        `running` turn is eligible.
        """
        if self._journal is None:
            return 0
        orphans = self._orphaned_turn_ids
        count = 0
        for rec in await self._journal.list_running():
            if orphans is not None and rec.turn_id not in orphans:
                continue  # created after this process subscribed — not ours
            try:
                if rec.attempts >= MAX_REDRIVE_ATTEMPTS:
                    await self._publish_synthetic_failure(
                        rec, "turn abandoned after repeated restarts"
                    )
                    await self._journal.set_status(rec.turn_id, "failed")
                    continue
                await self._journal.bump_attempts(rec.turn_id)
                await self._redrive_one(rec)
                count += 1
            except Exception:  # noqa: BLE001 — one broken turn must not abort the sweep
                logger.exception("nats_bridge.redrive_turn_failed turn_id=%s", rec.turn_id)
        return count

    async def _publish_error_async(
        self,
        reply_subject: str,
        *,
        code: int,
        message: str,
        request_id: Any = None,
    ) -> None:
        """Synchronously publish a JSON-RPC error envelope. No-op when the
        inbound message had no reply subject (fire-and-forget)."""
        if not reply_subject or self._nc is None:
            return
        payload = self._error_envelope_bytes(
            request_id=request_id,
            code=code,
            message=message,
        )
        try:
            await self._nc.publish(reply_subject, payload)
        except Exception:
            logger.exception("nats_bridge.publish_error")

    @staticmethod
    def _error_envelope_bytes(*, request_id: Any, code: int, message: str) -> bytes:
        return json.dumps(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": code, "message": message},
            }
        ).encode()

    async def stop(self) -> None:
        """Drain in-flight requests, unsubscribe, close NATS + HTTP."""
        logger.info("nats_bridge.stop")
        if self._sub is not None:
            try:
                await self._sub.unsubscribe()
            except Exception:
                logger.exception("nats_bridge.unsubscribe_error")
        # The re-drive sweep may still be polling /healthz (up to its own
        # 30s timeout) or mid-sweep — cancel it outright rather than making
        # every shutdown pay that wait; a re-drive interrupted by shutdown
        # just runs again on the next restart's sweep.
        if self._redrive_task is not None and not self._redrive_task.done():
            self._redrive_task.cancel()
            # gather(..., return_exceptions=True) swallows only the *child*
            # task's CancelledError/exception; if this stop() coroutine
            # itself is cancelled (e.g. a timed-out shutdown), the await
            # still raises that outer cancellation through normally.
            await asyncio.gather(self._redrive_task, return_exceptions=True)
            self._redrive_task = None
        # Drain in-flight forward tasks (best-effort, bounded).
        if self._inflight:
            try:
                await asyncio.wait(
                    self._inflight,
                    timeout=5.0,
                    return_when=asyncio.ALL_COMPLETED,
                )
            except Exception:
                logger.exception("nats_bridge.drain_error")
        if self._nc is not None:
            try:
                await self._nc.close()
            except Exception:
                logger.exception("nats_bridge.close_error")
            self._nc = None
        if self._http is not None:
            try:
                await self._http.aclose()
            except Exception:
                logger.exception("nats_bridge.http_close_error")
            self._http = None
        if self._journal is not None:
            try:
                await self._journal.close()
            except Exception:
                logger.exception("nats_bridge.journal_close_error")


def maybe_build_bridge(agent: Any, port: int) -> NatsHttpBridge | None:
    """Return a configured bridge if NATS transport is enabled, else None.

    Reads the agent's own subject from ``VYSTAK_NATS_SUBJECT`` (set by
    the provider's transport_wiring) with a fallback to deriving it from
    the agent's name + ``VYSTAK_NATS_NAMESPACE`` + ``VYSTAK_NATS_SUBJECT_PREFIX``.
    Returns ``None`` when ``VYSTAK_TRANSPORT_TYPE != "nats"`` so the
    lifespan path is a clean no-op for HTTP deployments.
    """
    if os.environ.get("VYSTAK_TRANSPORT_TYPE", "http") != "nats":
        return None
    nats_url = os.environ.get("VYSTAK_NATS_URL")
    if not nats_url:
        logger.warning("VYSTAK_TRANSPORT_TYPE=nats but VYSTAK_NATS_URL unset; bridge skipped")
        return None
    subject = os.environ.get("VYSTAK_NATS_SUBJECT") or _derive_subject(agent)
    if not subject:
        logger.warning("could not determine VYSTAK_NATS_SUBJECT; bridge skipped")
        return None
    queue_group = f"agents.{_slug(getattr(agent, 'name', 'agent'))}"
    local_url = f"http://localhost:{port}/a2a"
    from _vystak.runtime.turn_journal import SqliteTurnJournal

    journal = SqliteTurnJournal(resolve_turns_path())
    return NatsHttpBridge(
        nats_url=nats_url,
        subject=subject,
        queue_group=queue_group,
        local_url=local_url,
        local_base=f"http://localhost:{port}",
        journal=journal,
    )


def _derive_subject(agent: Any) -> str | None:
    """Compute the subject from name + namespace + prefix env vars.

    Mirrors NatsTransportPlugin.resolve_address_for so HTTP-side and
    bridge-side subjects stay in sync if the provider forgets to set
    VYSTAK_NATS_SUBJECT.
    """
    name = getattr(agent, "name", None)
    if not name:
        return None
    prefix = os.environ.get("VYSTAK_NATS_SUBJECT_PREFIX", "vystak")
    namespace = os.environ.get("VYSTAK_NATS_NAMESPACE", "default")
    return f"{prefix}.{_slug(namespace)}.agents.{_slug(name)}.tasks"


def _slug(s: str) -> str:
    """Lowercase and dot-safe — keeps subject parsing simple downstream."""
    return s.replace(" ", "-").lower()


# KEEP IN SYNC with vystak_transport_nats/streams.py — the template cannot
# import that package (agent images install vystak from PyPI only). Same
# convention: turn subject "{base}.streams.{conv}.{turn}", stream name
# "{base with . -> -}-streams", subject filter "{base}.streams.>".
def _stream_base_of_turn_subject(stream_subject: str) -> str:
    base, sep, _ = stream_subject.partition(".streams.")
    if not sep:
        raise ValueError(f"not a turn subject: {stream_subject!r}")
    return base


async def _ensure_turn_stream(js: Any, base: str) -> None:
    from nats.js.api import RetentionPolicy, StorageType, StreamConfig

    cfg = StreamConfig(
        name=base.replace(".", "-") + "-streams",
        subjects=[f"{base}.streams.>"],
        retention=RetentionPolicy.LIMITS,
        max_age=3600.0,
        storage=StorageType.FILE,
    )
    try:
        await js.add_stream(cfg)
    except Exception:  # noqa: BLE001 — exists; converge
        await js.update_stream(cfg)


def _failed_event(message: str) -> dict:
    return {
        "type": "response.failed",
        "response": {"status": "failed", "error": {"message": message}},
    }
