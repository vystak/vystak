"""Tests for AgentClient + ask_agent."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from vystak.transport import (
    A2AEvent,
    A2AMessage,
    A2AResult,
    AgentClient,
    AgentRef,
    Transport,
    ask_agent,
)
from vystak.transport.base import A2AHandlerProtocol


class FakeTransport(Transport):
    type = "fake"
    supports_streaming = True

    def __init__(self) -> None:
        self.sent: list[AgentRef] = []

    def resolve_address(self, canonical_name: str) -> str:
        return f"fake://{canonical_name}"

    async def send_task(
        self, agent, message, metadata, *, timeout
    ) -> A2AResult:
        self.sent.append(agent)
        return A2AResult(
            text=f"reply:{message.parts[0]['text']}",
            correlation_id=message.correlation_id,
        )

    async def stream_task(
        self, agent, message, metadata, *, timeout
    ) -> AsyncIterator[A2AEvent]:
        for ch in message.parts[0]["text"]:
            yield A2AEvent(type="token", text=ch)
        yield A2AEvent(type="final", text=f"done:{message.parts[0]['text']}", final=True)

    async def serve(self, canonical_name: str, handler: A2AHandlerProtocol) -> None:
        return None


class TestAgentClient:
    @pytest.mark.asyncio
    async def test_send_task_resolves_short_name(self):
        t = FakeTransport()
        c = AgentClient(
            transport=t,
            routes={"time-agent": "time-agent.agents.default"},
        )
        reply = await c.send_task("time-agent", "hi")
        assert reply == "reply:hi"
        assert t.sent[0].canonical_name == "time-agent.agents.default"

    @pytest.mark.asyncio
    async def test_send_task_unknown_short_name(self):
        t = FakeTransport()
        c = AgentClient(transport=t, routes={})
        with pytest.raises(KeyError, match="unknown"):
            await c.send_task("unknown", "hi")

    @pytest.mark.asyncio
    async def test_stream_task(self):
        t = FakeTransport()
        c = AgentClient(
            transport=t,
            routes={"time-agent": "time-agent.agents.default"},
        )
        events = []
        async for ev in c.stream_task("time-agent", "ab"):
            events.append(ev)
        assert [e.text for e in events[:2]] == ["a", "b"]
        assert events[-1].final is True

    @pytest.mark.asyncio
    async def test_send_task_accepts_a2a_message(self):
        t = FakeTransport()
        c = AgentClient(
            transport=t,
            routes={"x": "x.agents.default"},
        )
        msg = A2AMessage.from_text("hi", correlation_id="fixed-id")
        reply = await c.send_task("x", msg)
        assert reply == "reply:hi"
        assert t.sent[0].canonical_name == "x.agents.default"


class TestAskAgent:
    @pytest.mark.asyncio
    async def test_uses_provided_client(self):
        t = FakeTransport()
        c = AgentClient(transport=t, routes={"x": "x.agents.default"})
        reply = await ask_agent("x", "hi", client=c)
        assert reply == "reply:hi"
