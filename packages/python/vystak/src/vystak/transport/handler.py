"""Transport-agnostic A2A request dispatcher.

A2AHandler is the *callee-side* counterpart of Transport. It wraps the
agent's underlying callable (LangGraph agent, static function, whatever)
behind a uniform async interface that accepts A2A envelope types.

FastAPI routes, NATS listeners, and Service Bus receivers all hand raw
incoming messages to A2AHandler.dispatch() or dispatch_stream() and forward
the result back over their medium.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from vystak.transport.types import (
    A2AEvent,
    A2AMessage,
    A2AResult,
)

OneShotCallable = Callable[[A2AMessage, dict[str, Any]], Awaitable[str]]
StreamingCallable = Callable[[A2AMessage, dict[str, Any]], AsyncIterator[A2AEvent]]


class A2AHandler:
    """Dispatches A2A messages to an underlying agent callable."""

    def __init__(
        self,
        *,
        one_shot: OneShotCallable,
        streaming: StreamingCallable,
    ) -> None:
        self._one_shot = one_shot
        self._streaming = streaming

    async def dispatch(self, message: A2AMessage, metadata: dict[str, Any]) -> A2AResult:
        """Run the one-shot path and wrap the returned text as `A2AResult`.

        The agent callable's exceptions propagate. The transport caller is
        responsible for turning them into wire-level error responses.
        """
        text = await self._one_shot(message, metadata)
        return A2AResult(
            text=text,
            correlation_id=message.correlation_id,
            metadata={},
        )

    async def dispatch_stream(
        self, message: A2AMessage, metadata: dict[str, Any]
    ) -> AsyncIterator[A2AEvent]:
        """Yield streaming events from the agent callable.

        Events flow through unchanged. Callers receiving a transport without
        native streaming should use `Transport.stream_task()` which degrades
        automatically.
        """
        async for event in self._streaming(message, metadata):
            yield event
