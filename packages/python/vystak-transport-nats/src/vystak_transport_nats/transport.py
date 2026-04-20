from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections.abc import AsyncIterator, Callable
from typing import Any

import nats
import nats.errors as _nats_errors
from nats.aio.client import Client as NATSClient
from vystak.transport import (
    A2AEvent,
    A2AMessage,
    A2AResult,
    AgentRef,
    Transport,
)
from vystak.transport.base import ServerDispatcherProtocol
from vystak.transport.naming import parse_canonical_name, slug

logger = logging.getLogger("vystak.transport.nats")


class NatsTransport(Transport):
    type = "nats"
    supports_streaming = True

    def __init__(
        self,
        url: str,
        *,
        subject_prefix: str = "vystak",
        jetstream: bool = True,
    ) -> None:
        self._url = url
        self._subject_prefix = subject_prefix
        self._jetstream = jetstream
        self._nc: NATSClient | None = None
        self._lock = asyncio.Lock()

    async def _connect(self) -> NATSClient:
        async with self._lock:
            if self._nc is None or self._nc.is_closed:
                logger.info("nats.connect url=%s", self._url)
                self._nc = await nats.connect(self._url)
                logger.info("nats.connected url=%s", self._url)
            return self._nc

    def resolve_address(self, canonical_name: str) -> str:
        name, kind, ns = parse_canonical_name(canonical_name)
        return f"{self._subject_prefix}.{slug(ns)}.{kind}.{slug(name)}.tasks"

    def _build_envelope(self, method: str, message: A2AMessage, metadata: dict) -> bytes:
        payload = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": method,
            "params": {
                "id": message.correlation_id,
                "message": {"role": message.role, "parts": message.parts},
                "metadata": {**message.metadata, **metadata},
            },
        }
        return json.dumps(payload).encode()

    def _build_envelope_for_method(
        self,
        method: str,
        params: dict[str, Any],
        metadata: dict[str, Any],
    ) -> bytes:
        """Build a JSON-RPC envelope with arbitrary params. Used by
        Responses API methods; A2A methods use the typed _build_envelope."""
        return json.dumps({
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": method,
            "params": params,
            "metadata": metadata,
        }).encode()

    @staticmethod
    def _is_a2a_terminal(chunk: dict[str, Any]) -> bool:
        return bool(chunk.get("final"))

    @staticmethod
    def _is_responses_terminal(chunk: dict[str, Any]) -> bool:
        return chunk.get("type") == "response.completed"

    async def _stream_via_inbox(
        self,
        subject: str,
        payload: bytes,
        timeout: float,
        *,
        terminal: Callable[[dict[str, Any]], bool],
    ) -> AsyncIterator[dict[str, Any]]:
        """Shared implementation for streaming over a NATS reply inbox.

        Generates a unique `_INBOX.{uuid}` subject, subscribes BEFORE
        publishing to avoid missing early messages, iterates messages as
        JSON dicts, and stops when `terminal(chunk)` returns True or the
        deadline elapses.
        """
        nc = await self._connect()
        inbox = f"_INBOX.{uuid.uuid4().hex}"
        sub = await nc.subscribe(inbox)
        try:
            await nc.publish(subject, payload, reply=inbox)
            deadline = asyncio.get_running_loop().time() + timeout
            while True:
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    raise TimeoutError(f"NATS stream from {subject} timed out")
                # nats-py's next_msg default timeout is 1s. Pass the full
                # remaining budget so slow LLM-streaming replies don't trip
                # it between chunks.
                try:
                    msg = await sub.next_msg(timeout=remaining)
                except _nats_errors.TimeoutError as e:
                    raise TimeoutError(
                        f"NATS stream from {subject} timed out mid-stream"
                    ) from e
                chunk = json.loads(msg.data)
                yield chunk
                if terminal(chunk):
                    return
        finally:
            await sub.unsubscribe()

    async def send_task(
        self, agent: AgentRef, message: A2AMessage, metadata: dict, *, timeout: float,
    ) -> A2AResult:
        nc = await self._connect()
        subject = self.resolve_address(agent.canonical_name)
        payload = self._build_envelope("tasks/send", message, metadata)
        t0 = time.monotonic()
        logger.info(
            "tx tasks/send subject=%s cid=%s",
            subject, message.correlation_id,
        )
        try:
            reply = await nc.request(subject, payload, timeout=timeout)
        except TimeoutError as e:
            logger.warning(
                "tx tasks/send TIMEOUT subject=%s cid=%s after=%.2fs",
                subject, message.correlation_id, timeout,
            )
            raise TimeoutError(f"NATS request to {subject} timed out after {timeout}s") from e
        body = json.loads(reply.data)
        latency_ms = (time.monotonic() - t0) * 1000
        logger.info(
            "rx tasks/send subject=%s cid=%s latency_ms=%.0f bytes=%d",
            subject, message.correlation_id, latency_ms, len(reply.data),
        )
        return self._parse_result(body, message.correlation_id)

    async def stream_task(
        self, agent: AgentRef, message: A2AMessage, metadata: dict, *, timeout: float,
    ) -> AsyncIterator[A2AEvent]:
        subject = self.resolve_address(agent.canonical_name)
        payload = self._build_envelope("tasks/sendSubscribe", message, metadata)
        async for chunk in self._stream_via_inbox(
            subject, payload, timeout, terminal=self._is_a2a_terminal,
        ):
            event = A2AEvent.model_validate(chunk)
            yield event

    async def create_response(
        self,
        agent: AgentRef,
        request: dict[str, Any],
        metadata: dict[str, Any],
        *,
        timeout: float,
    ) -> dict[str, Any]:
        nc = await self._connect()
        subject = self.resolve_address(agent.canonical_name)
        cid = metadata.get("correlation_id") or str(uuid.uuid4())
        payload = self._build_envelope_for_method(
            "responses/create", {"request": request}, metadata,
        )
        t0 = time.monotonic()
        logger.info("tx responses/create subject=%s cid=%s", subject, cid)
        try:
            reply = await nc.request(subject, payload, timeout=timeout)
        except TimeoutError as e:
            logger.warning(
                "tx responses/create TIMEOUT subject=%s cid=%s after=%.2fs",
                subject, cid, timeout,
            )
            raise TimeoutError(
                f"NATS request to {subject} (responses/create) timed out "
                f"after {timeout}s"
            ) from e
        body = json.loads(reply.data)
        latency_ms = (time.monotonic() - t0) * 1000
        logger.info(
            "rx responses/create subject=%s cid=%s latency_ms=%.0f bytes=%d",
            subject, cid, latency_ms, len(reply.data),
        )
        return body.get("result", {})

    async def get_response(
        self,
        agent: AgentRef,
        response_id: str,
        *,
        timeout: float,
    ) -> dict[str, Any] | None:
        nc = await self._connect()
        subject = self.resolve_address(agent.canonical_name)
        payload = self._build_envelope_for_method(
            "responses/get", {"response_id": response_id}, {},
        )
        try:
            reply = await nc.request(subject, payload, timeout=timeout)
        except TimeoutError as e:
            raise TimeoutError(
                f"NATS request to {subject} (responses/get) timed out "
                f"after {timeout}s"
            ) from e
        body = json.loads(reply.data)
        result = body.get("result")
        return result if result else None

    async def create_response_stream(
        self,
        agent: AgentRef,
        request: dict[str, Any],
        metadata: dict[str, Any],
        *,
        timeout: float,
    ) -> AsyncIterator[dict[str, Any]]:
        subject = self.resolve_address(agent.canonical_name)
        cid = metadata.get("correlation_id") or str(uuid.uuid4())
        payload = self._build_envelope_for_method(
            "responses/createStream", {"request": request}, metadata,
        )
        t0 = time.monotonic()
        logger.info("tx responses/createStream subject=%s cid=%s", subject, cid)
        chunks = 0
        async for chunk in self._stream_via_inbox(
            subject, payload, timeout, terminal=self._is_responses_terminal,
        ):
            chunks += 1
            yield chunk
        latency_ms = (time.monotonic() - t0) * 1000
        logger.info(
            "rx responses/createStream subject=%s cid=%s chunks=%d latency_ms=%.0f",
            subject, cid, chunks, latency_ms,
        )

    async def _handle_inbound(
        self,
        body: dict[str, Any],
        msg: Any,
        handler: ServerDispatcherProtocol,
        nc: NATSClient,
    ) -> None:
        """Route a single inbound JSON-RPC message to the right dispatcher method.

        Extracted from ``serve`` so the routing logic is directly unit-testable
        without a live NATS connection.
        """
        t0 = time.monotonic()
        try:
            method = body.get("method", "tasks/send")
            params = body.get("params", {})
            cid = params.get("id") or body.get("id") or "?"
            _data = getattr(msg, "data", b"")
            logger.info(
                "inbound method=%s subject=%s cid=%s bytes=%d",
                method, getattr(msg, "subject", "?"), cid, len(_data),
            )

            if method in ("tasks/send", "tasks/sendSubscribe"):
                m = A2AMessage(
                    role=params.get("message", {}).get("role", "user"),
                    parts=params.get("message", {}).get("parts", []),
                    correlation_id=params.get("id", str(uuid.uuid4())),
                    metadata=params.get("metadata", {}),
                )
                metadata = params.get("metadata", {})

                if method == "tasks/sendSubscribe":
                    async for event in handler.dispatch_a2a_stream(m, metadata):
                        await nc.publish(msg.reply, event.model_dump_json().encode())
                else:
                    result = await handler.dispatch_a2a(m, metadata)
                    reply_body = {
                        "jsonrpc": "2.0",
                        "id": body.get("id"),
                        "result": {
                            "status": {"message": {"parts": [{"text": result.text}]}},
                            "correlation_id": result.correlation_id,
                        },
                    }
                    await nc.publish(msg.reply, json.dumps(reply_body).encode())
            elif method == "responses/create":
                request = params.get("request", {})
                metadata_r = body.get("metadata", {})
                result = await handler.dispatch_responses_create(request, metadata_r)
                reply_body = {
                    "jsonrpc": "2.0",
                    "id": body.get("id"),
                    "result": result,
                }
                await nc.publish(msg.reply, json.dumps(reply_body).encode())
            elif method == "responses/createStream":
                request = params.get("request", {})
                metadata_r = body.get("metadata", {})
                async for chunk in handler.dispatch_responses_create_stream(
                    request, metadata_r
                ):
                    await nc.publish(msg.reply, json.dumps(chunk).encode())
            elif method == "responses/get":
                response_id = params.get("response_id", "")
                result = await handler.dispatch_responses_get(response_id)
                reply_body = {
                    "jsonrpc": "2.0",
                    "id": body.get("id"),
                    "result": result,
                }
                await nc.publish(msg.reply, json.dumps(reply_body).encode())
            else:
                if msg.reply:
                    err = {
                        "jsonrpc": "2.0",
                        "id": body.get("id"),
                        "error": {
                            "code": -32601,
                            "message": f"Unknown method: {method}",
                        },
                    }
                    await nc.publish(msg.reply, json.dumps(err).encode())
            latency_ms = (time.monotonic() - t0) * 1000
            logger.info(
                "outbound method=%s cid=%s latency_ms=%.0f",
                method, cid, latency_ms,
            )
        except Exception as e:
            latency_ms = (time.monotonic() - t0) * 1000
            logger.exception(
                "inbound-error method=%s cid=%s latency_ms=%.0f error=%s",
                body.get("method", "?"), body.get("id", "?"), latency_ms, e,
            )
            if msg.reply:
                err = {"jsonrpc": "2.0", "error": {"code": -32603, "message": str(e)}}
                await nc.publish(msg.reply, json.dumps(err).encode())

    async def serve(
        self, canonical_name: str, handler: ServerDispatcherProtocol
    ) -> None:
        nc = await self._connect()
        subject = self.resolve_address(canonical_name)
        name, _, _ = parse_canonical_name(canonical_name)
        queue_group = f"agents.{slug(name)}"

        async def on_message(msg: Any) -> None:
            try:
                body = json.loads(msg.data)
            except Exception as e:
                if msg.reply:
                    err = {"jsonrpc": "2.0", "error": {"code": -32700, "message": str(e)}}
                    await nc.publish(msg.reply, json.dumps(err).encode())
                return
            await self._handle_inbound(body, msg, handler, nc)

        await nc.subscribe(subject, queue=queue_group, cb=on_message)
        # Block forever; caller runs this under asyncio.create_task
        while True:
            await asyncio.sleep(3600)

    def _parse_result(self, body: dict, fallback_cid: str) -> A2AResult:
        result = body.get("result", {}) or {}
        parts = result.get("status", {}).get("message", {}).get("parts", [])
        text = "".join(p.get("text", "") for p in parts if isinstance(p, dict))
        return A2AResult(
            text=text,
            correlation_id=result.get("correlation_id") or fallback_cid,
            metadata={},
        )
