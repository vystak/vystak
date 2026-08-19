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
        # Re-drive any turns a prior process left mid-flight (crash/restart),
        # after the NATS connection is live but *before* subscribing — so
        # nothing new can be assigned to this bridge and race the sweep's
        # own reads/writes of the same journal rows.
        try:
            redriven = await self.redrive_unfinished()
            if redriven:
                logger.info("nats_bridge.redrove_unfinished count=%d", redriven)
        except Exception:  # noqa: BLE001 — startup must not crash on this
            logger.exception("nats_bridge.redrive_unfinished_failed")
        self._sub = await self._nc.subscribe(
            self._subject,
            queue=self._queue_group,
            cb=self._on_message,
        )
        logger.info("nats_bridge.subscribed subject=%s", self._subject)

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
        self, resp: httpx.Response, turn_id: str, publish: Any
    ) -> None:
        """Shared SSE-consumption loop for both a live detached run
        (`_run_detached`) and a re-driven resume (`_stream_from_resume_endpoint`).

        Handles `vystak.checkpoint` markers (record boundary, never
        published), captures `thread_id` from `response.created`, publishes
        every other event to JetStream, and journals `last_seq` / terminal
        status after each publish. A stream that ends without `[DONE]` or a
        terminal event gets a synthetic `response.failed` so consumers still
        terminate — the turn is left in a re-drive-eligible state, not
        stamped failed, by the callers (see their comments).
        """
        last_seq: int | None = None
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

            last_seq = await publish(event)
            if self._journal is not None:
                await self._journal.set_last_seq(turn_id, last_seq)
                if event.get("type") == "response.completed":
                    await self._journal.set_status(turn_id, "done")
                elif event.get("type") == "response.failed":
                    await self._journal.set_status(turn_id, "failed")

        # Truncated stream (no [DONE], no terminal event): make sure
        # consumers still terminate.
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

    async def _current_checkpoint_id(self, thread_id: str | None) -> str | None:
        """Ask the local agent for the checkpoint LangGraph would resume
        from for this thread — via `GET /v1/_vystak/checkpoint`."""
        if not thread_id:
            return None
        assert self._http is not None
        try:
            resp = await self._http.get(
                f"{self._local_base}/v1/_vystak/checkpoint",
                params={"thread_id": thread_id},
            )
            resp.raise_for_status()
            return resp.json().get("checkpoint_id")
        except Exception:  # noqa: BLE001
            logger.exception("nats_bridge.current_checkpoint_lookup_failed")
            return None

    async def _publish_seq(self, stream_subject: str, seq: int, event: dict) -> None:
        js = self._nc.jetstream()
        await js.publish(stream_subject, json.dumps({"seq": seq, "event": event}).encode())

    async def _publish_synthetic_failure(self, rec: TurnRecord, message: str) -> None:
        await self._publish_seq(rec.stream_subject, rec.last_seq + 1, _failed_event(message))

    async def _stream_from_resume_endpoint(self, rec: TurnRecord, *, start_seq: int) -> None:
        """POST `/v1/_vystak/resume` and consume the SSE stream through the
        same loop `_run_detached` uses, publishing at `start_seq` onward."""
        try:
            js = self._nc.jetstream()
        except Exception:
            logger.exception("nats_bridge.redrive_jetstream_failed")
            return
        publish = self._make_publisher(js, rec.stream_subject, start_seq)
        assert self._http is not None
        try:
            async with self._http.stream(
                "POST",
                f"{self._local_base}/v1/_vystak/resume",
                json={"thread_id": rec.thread_id},
                timeout=httpx.Timeout(None, connect=10.0, read=300.0),
            ) as resp:
                if resp.status_code != 200:
                    seq = await publish(
                        _failed_event(f"local /v1/_vystak/resume returned {resp.status_code}")
                    )
                    if self._journal is not None:
                        await self._journal.set_last_seq(rec.turn_id, seq)
                    return
                await self._consume_response_stream(resp, rec.turn_id, publish)
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
        seq = rec.last_seq + 1
        await self._publish_seq(
            rec.stream_subject, seq, {"type": "vystak.turn.rewind", "to_seq": to_seq}
        )
        await self._stream_from_resume_endpoint(rec, start_seq=seq + 1)

    async def redrive_unfinished(self) -> int:
        """Re-drive every turn the journal still considers `running` — a
        crash/restart mid-turn is the expected way to land here. Turns that
        have already exhausted `MAX_REDRIVE_ATTEMPTS` are given up on and
        marked failed instead of retried forever. Returns the number of
        turns actually re-driven (not counting turns that hit the cap)."""
        if self._journal is None:
            return 0
        count = 0
        for rec in await self._journal.list_running():
            if rec.attempts >= MAX_REDRIVE_ATTEMPTS:
                await self._publish_synthetic_failure(
                    rec, "turn abandoned after repeated restarts"
                )
                await self._journal.set_status(rec.turn_id, "failed")
                continue
            await self._journal.bump_attempts(rec.turn_id)
            await self._redrive_one(rec)
            count += 1
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
