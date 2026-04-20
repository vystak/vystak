from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

import nats
from nats.aio.client import Client as NATSClient
from vystak.transport import (
    A2AEvent,
    A2AMessage,
    A2AResult,
    AgentRef,
    Transport,
)
from vystak.transport.base import A2AHandlerProtocol
from vystak.transport.naming import parse_canonical_name, slug


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
                self._nc = await nats.connect(self._url)
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

    async def send_task(
        self, agent: AgentRef, message: A2AMessage, metadata: dict, *, timeout: float,
    ) -> A2AResult:
        nc = await self._connect()
        subject = self.resolve_address(agent.canonical_name)
        payload = self._build_envelope("tasks/send", message, metadata)
        try:
            reply = await nc.request(subject, payload, timeout=timeout)
        except TimeoutError as e:
            raise TimeoutError(f"NATS request to {subject} timed out after {timeout}s") from e
        body = json.loads(reply.data)
        return self._parse_result(body, message.correlation_id)

    async def stream_task(
        self, agent: AgentRef, message: A2AMessage, metadata: dict, *, timeout: float,
    ) -> AsyncIterator[A2AEvent]:
        nc = await self._connect()
        subject = self.resolve_address(agent.canonical_name)
        inbox = f"_INBOX.{uuid.uuid4().hex}"
        sub = await nc.subscribe(inbox)
        try:
            payload = self._build_envelope("tasks/sendSubscribe", message, metadata)
            await nc.publish(subject, payload, reply=inbox)
            loop = asyncio.get_running_loop()
            deadline = loop.time() + timeout
            while True:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    raise TimeoutError(f"NATS stream from {subject} timed out")
                msg = await asyncio.wait_for(sub.next_msg(), timeout=remaining)
                event = A2AEvent.model_validate(json.loads(msg.data))
                yield event
                if event.final:
                    return
        finally:
            await sub.unsubscribe()

    async def serve(self, canonical_name: str, handler: A2AHandlerProtocol) -> None:
        nc = await self._connect()
        subject = self.resolve_address(canonical_name)
        name, _, _ = parse_canonical_name(canonical_name)
        queue_group = f"agents.{slug(name)}"

        async def on_message(msg: Any) -> None:
            try:
                body = json.loads(msg.data)
                method = body.get("method", "tasks/send")
                params = body.get("params", {})
                m = A2AMessage(
                    role=params.get("message", {}).get("role", "user"),
                    parts=params.get("message", {}).get("parts", []),
                    correlation_id=params.get("id", str(uuid.uuid4())),
                    metadata=params.get("metadata", {}),
                )
                metadata = params.get("metadata", {})
                if method == "tasks/sendSubscribe":
                    async for event in handler.dispatch_stream(m, metadata):
                        await nc.publish(msg.reply, event.model_dump_json().encode())
                else:
                    result = await handler.dispatch(m, metadata)
                    reply_body = {
                        "jsonrpc": "2.0",
                        "id": body.get("id"),
                        "result": {
                            "status": {"message": {"parts": [{"text": result.text}]}},
                            "correlation_id": result.correlation_id,
                        },
                    }
                    await nc.publish(msg.reply, json.dumps(reply_body).encode())
            except Exception as e:
                if msg.reply:
                    err = {"jsonrpc": "2.0", "error": {"code": -32603, "message": str(e)}}
                    await nc.publish(msg.reply, json.dumps(err).encode())

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
