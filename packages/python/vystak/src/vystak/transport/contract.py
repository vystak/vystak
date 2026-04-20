"""Shared pytest contract tests for concrete Transport implementations.

Usage: in a concrete transport's test file,

    from vystak.transport.contract import TransportContract

    class TestHttpTransport(TransportContract):
        @pytest.fixture
        def serve_agent(self):
            # Return an async context manager factory: serve_agent(name, handler)
            # must set up the listener side and `yield` a client `Transport`
            # pre-configured to reach `name`.
            @asynccontextmanager
            async def _ctx(canonical_name, handler):
                ...  # spin up whatever the transport needs
                yield HttpTransport(routes={canonical_name: f"http://.../a2a"})
            return _ctx

`serve_agent(canonical_name, handler)` is an async context manager that
binds `handler` to the canonical name on the listener side and yields a
ready-to-use client `Transport` instance. On exit it tears down the
listener.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager  # noqa: F401 — used in docstring example

import pytest

from vystak.transport.handler import A2AHandler
from vystak.transport.types import (
    A2AEvent,
    A2AMessage,
    AgentRef,
)


class _A2AOnlyDispatcher:
    """Test-only ``ServerDispatcherProtocol`` adapter around an ``A2AHandler``.

    Plan C's ``Transport.serve`` accepts a ``ServerDispatcherProtocol``.
    Contract tests only exercise A2A paths, so we fan ``dispatch_a2a*`` calls
    through to the underlying handler and stub the Responses methods.
    """

    def __init__(self, a2a: A2AHandler) -> None:
        self._a2a = a2a

    async def dispatch_a2a(self, message, metadata):
        return await self._a2a.dispatch(message, metadata)

    def dispatch_a2a_stream(self, message, metadata):
        return self._a2a.dispatch_stream(message, metadata)

    async def dispatch_responses_create(self, request, metadata):
        raise NotImplementedError("contract tests do not cover responses/create")

    def dispatch_responses_create_stream(self, request, metadata):
        async def _empty():
            if False:
                yield {}

        return _empty()

    async def dispatch_responses_get(self, response_id):
        return None


class TransportContract:
    """Pytest mixin. Subclass and provide a `serve_agent` fixture."""

    @pytest.fixture
    def serve_agent(self):
        raise NotImplementedError(
            "Concrete test class must provide a `serve_agent` fixture — an "
            "async context manager factory (canonical_name, handler) -> "
            "client Transport."
        )

    @pytest.mark.asyncio
    async def test_single_reply_per_call(self, serve_agent):
        async def one_shot(msg, metadata):
            text = msg.parts[0]["text"] if msg.parts else ""
            return f"reply:{text}"

        async def streaming(msg, metadata):
            yield A2AEvent(type="final", text="n/a", final=True)

        handler = _A2AOnlyDispatcher(A2AHandler(one_shot=one_shot, streaming=streaming))
        async with serve_agent("echo.agents.default", handler) as client:
            ref = AgentRef(canonical_name="echo.agents.default")
            msg = A2AMessage.from_text("hi")
            result = await client.send_task(ref, msg, {}, timeout=5)
            assert result.text == "reply:hi"
            assert result.correlation_id == msg.correlation_id

    @pytest.mark.asyncio
    async def test_concurrent_calls_do_not_cross(self, serve_agent):
        async def one_shot(msg, metadata):
            await asyncio.sleep(0.05)
            return msg.parts[0]["text"]

        async def streaming(msg, metadata):
            yield A2AEvent(type="final", text=msg.parts[0]["text"], final=True)

        handler = _A2AOnlyDispatcher(A2AHandler(one_shot=one_shot, streaming=streaming))
        async with serve_agent("echo.agents.default", handler) as client:
            ref = AgentRef(canonical_name="echo.agents.default")

            # Map correlation_id -> text we sent. After gather, every reply
            # must be the exact text that was sent *with its own correlation
            # id* — not merely "some text from the batch".
            sent_by_cid: dict[str, str] = {}

            async def call(text):
                msg = A2AMessage.from_text(text)
                sent_by_cid[msg.correlation_id] = text
                result = await client.send_task(ref, msg, {}, timeout=5)
                return result.correlation_id, result.text

            pairs = await asyncio.gather(*[call(f"m-{i}") for i in range(10)])

            # Each reply's body must match the body we sent under the same
            # correlation id. Catches transports that swap bodies between
            # concurrent calls even if correlation ids survive.
            for cid, text in pairs:
                assert cid in sent_by_cid, f"unknown correlation id: {cid}"
                assert text == sent_by_cid[cid], (
                    f"body mismatch for {cid}: sent={sent_by_cid[cid]!r}, got={text!r}"
                )
            assert len({cid for cid, _ in pairs}) == 10

    @pytest.mark.asyncio
    async def test_timeout_raises(self, serve_agent):
        async def one_shot(msg, metadata):
            await asyncio.sleep(2)
            return "late"

        async def streaming(msg, metadata):
            yield A2AEvent(type="final", text="late", final=True)

        handler = _A2AOnlyDispatcher(A2AHandler(one_shot=one_shot, streaming=streaming))
        async with serve_agent("slow.agents.default", handler) as client:
            ref = AgentRef(canonical_name="slow.agents.default")
            msg = A2AMessage.from_text("hi")
            with pytest.raises((asyncio.TimeoutError, TimeoutError)):
                await client.send_task(ref, msg, {}, timeout=0.2)

    @pytest.mark.asyncio
    async def test_streaming_or_degradation(self, serve_agent):
        async def one_shot(msg, metadata):
            return "full-reply"

        async def streaming(msg, metadata):
            for ch in "abc":
                yield A2AEvent(type="token", text=ch)
            yield A2AEvent(type="final", text="abc", final=True)

        handler = _A2AOnlyDispatcher(A2AHandler(one_shot=one_shot, streaming=streaming))
        async with serve_agent("s.agents.default", handler) as client:
            ref = AgentRef(canonical_name="s.agents.default")
            events = []
            async for ev in client.stream_task(ref, A2AMessage.from_text("hi"), {}, timeout=5):
                events.append(ev)
            if client.supports_streaming:
                assert any(ev.type == "token" for ev in events)
            else:
                assert len(events) == 1
                assert events[0].final is True
            assert events[-1].final is True
