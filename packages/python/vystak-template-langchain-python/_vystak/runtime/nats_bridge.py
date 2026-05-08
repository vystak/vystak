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
from typing import Any

import httpx

logger = logging.getLogger("vystak.runtime.nats_bridge")


class NatsHttpBridge:
    """Subscribes to a NATS subject and proxies to the local /a2a endpoint."""

    def __init__(
        self,
        *,
        nats_url: str,
        subject: str,
        queue_group: str,
        local_url: str,
    ) -> None:
        self._nats_url = nats_url
        self._subject = subject
        self._queue_group = queue_group
        self._local_url = local_url
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
            self._nats_url, self._subject, self._queue_group, self._local_url,
        )
        self._nc = await nats.connect(self._nats_url)
        # Localhost loopback HTTP client. Re-used across requests to
        # avoid per-message connection setup. Bridge timeout exceeds
        # typical agent latency (LLM round-trips + tool calls).
        self._http = httpx.AsyncClient(timeout=httpx.Timeout(120.0))
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
                    reply_subject, code=-32700, message="empty payload",
                )
                return
            try:
                envelope = json.loads(body)
            except json.JSONDecodeError as e:
                await self._publish_error_async(
                    reply_subject, code=-32700, message=f"parse error: {e}",
                )
                return
            request_id = envelope.get("id")
            method = envelope.get("method", "?")
            logger.debug(
                "nats_bridge.inbound method=%s id=%s bytes=%d",
                method, request_id, len(body),
            )

            assert self._http is not None  # set by start()
            try:
                resp = await self._http.post(
                    self._local_url,
                    content=body,
                    headers={"Content-Type": "application/json"},
                )
            except (httpx.ConnectError, httpx.ReadTimeout, httpx.HTTPError) as e:
                logger.exception("nats_bridge.local_http_error")
                await self._publish_error_async(
                    reply_subject,
                    code=-32603,
                    message=f"local /a2a request failed: {e}",
                    request_id=request_id,
                )
                return

            # The SDK responds with a JSON-RPC body for /a2a — we just
            # forward whatever bytes came back. If the local endpoint
            # returned a non-JSON error, downstream will surface that
            # as a JSON-decode error on the client side, which is fine.
            payload = resp.content if resp.status_code == 200 else self._error_envelope_bytes(
                request_id=request_id,
                code=-32603,
                message=f"local /a2a returned {resp.status_code}",
            )
            if reply_subject:
                await self._nc.publish(reply_subject, payload)
        except Exception:
            logger.exception("nats_bridge.unhandled")
            # Last-ditch: best-effort error publish without re-raising.
            await self._publish_error_async(
                reply_subject, code=-32603, message="bridge internal error",
            )

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
            request_id=request_id, code=code, message=message,
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
    return NatsHttpBridge(
        nats_url=nats_url,
        subject=subject,
        queue_group=queue_group,
        local_url=local_url,
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
