"""Tests for the Transport ABC contract."""

from __future__ import annotations

import pytest
from vystak.transport import (
    A2AEvent,
    A2AMessage,
    A2AResult,
    AgentRef,
    Transport,
)
from vystak.transport.base import (
    A2AHandlerProtocol,
)


class FakeTransport(Transport):
    """Minimal concrete Transport for testing ABC behaviour."""

    type = "fake"
    supports_streaming = False

    def __init__(self) -> None:
        self.sent: list[tuple[AgentRef, A2AMessage]] = []
        self.served: list[str] = []

    def resolve_address(self, canonical_name: str) -> str:
        return f"fake://{canonical_name}"

    async def send_task(
        self,
        agent: AgentRef,
        message: A2AMessage,
        metadata: dict,
        *,
        timeout: float,
    ) -> A2AResult:
        self.sent.append((agent, message))
        return A2AResult(text="ack", correlation_id=message.correlation_id)

    async def serve(self, canonical_name: str, handler: A2AHandlerProtocol) -> None:
        self.served.append(canonical_name)


class TestTransport:
    def test_cannot_instantiate_abstract(self):
        with pytest.raises(TypeError):
            Transport()

    def test_concrete_subclass(self):
        t = FakeTransport()
        assert t.type == "fake"
        assert t.supports_streaming is False

    @pytest.mark.asyncio
    async def test_send_task(self):
        t = FakeTransport()
        ref = AgentRef(canonical_name="x.agents.default")
        msg = A2AMessage.from_text("hi", correlation_id="c-1")
        result = await t.send_task(ref, msg, {}, timeout=5)
        assert result.text == "ack"
        assert result.correlation_id == "c-1"

    @pytest.mark.asyncio
    async def test_default_stream_task_degrades(self):
        """A non-streaming transport's stream_task() yields one terminal event."""
        t = FakeTransport()
        ref = AgentRef(canonical_name="x.agents.default")
        msg = A2AMessage.from_text("hi")
        events: list[A2AEvent] = []
        async for ev in t.stream_task(ref, msg, {}, timeout=5):
            events.append(ev)
        assert len(events) == 1
        assert events[0].final is True
        assert events[0].type == "final"
        assert events[0].text == "ack"

    def test_resolve_address(self):
        t = FakeTransport()
        assert t.resolve_address("x.agents.prod") == "fake://x.agents.prod"
