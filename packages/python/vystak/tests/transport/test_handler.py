"""Tests for A2AHandler dispatch semantics."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from vystak.transport import (
    A2AEvent,
    A2AHandler,
    A2AMessage,
    A2AResult,
)


async def _echo_handler(msg: A2AMessage, metadata: dict) -> str:
    text = msg.parts[0]["text"] if msg.parts else ""
    return f"echo:{text}"


async def _streaming_echo(msg: A2AMessage, metadata: dict) -> AsyncIterator[A2AEvent]:
    text = msg.parts[0]["text"] if msg.parts else ""
    for ch in text:
        yield A2AEvent(type="token", text=ch)
    yield A2AEvent(type="final", text=f"done:{text}", final=True)


class TestA2AHandler:
    @pytest.mark.asyncio
    async def test_dispatch_one_shot(self):
        h = A2AHandler(
            one_shot=_echo_handler,
            streaming=_streaming_echo,
        )
        msg = A2AMessage.from_text("hi", correlation_id="c-1")
        result = await h.dispatch(msg, {})
        assert isinstance(result, A2AResult)
        assert result.text == "echo:hi"
        assert result.correlation_id == "c-1"

    @pytest.mark.asyncio
    async def test_dispatch_stream(self):
        h = A2AHandler(
            one_shot=_echo_handler,
            streaming=_streaming_echo,
        )
        msg = A2AMessage.from_text("ab")
        events: list[A2AEvent] = []
        async for ev in h.dispatch_stream(msg, {}):
            events.append(ev)
        assert [e.text for e in events[:2]] == ["a", "b"]
        assert events[-1].final is True
        assert events[-1].text == "done:ab"

    @pytest.mark.asyncio
    async def test_dispatch_surfaces_errors(self):
        async def bad(msg, metadata):
            raise RuntimeError("boom")

        h = A2AHandler(one_shot=bad, streaming=_streaming_echo)
        msg = A2AMessage.from_text("hi")
        with pytest.raises(RuntimeError, match="boom"):
            await h.dispatch(msg, {})
