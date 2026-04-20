"""Transport-agnostic A2A request dispatcher.

A2AHandler is the *callee-side* counterpart of Transport. It wraps the
agent's underlying callable (LangGraph agent, static function, whatever)
behind a uniform async interface that accepts A2A envelope types.

FastAPI routes, NATS listeners, and Service Bus receivers all hand raw
incoming messages to A2AHandler.dispatch() or dispatch_stream() and forward
the result back over their medium.

Optional idempotency: if an `IdempotencyCache` is passed at construction
time and the incoming message's metadata carries an `idempotency_key`,
the handler short-circuits on cache hits — returning the previously
computed `A2AResult` without invoking the agent again. Streaming skips
the cache (too much state to replay).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from vystak.transport.idempotency import (
    IdempotencyCache,
    extract_idempotency_key,
)
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
        idempotency_cache: IdempotencyCache[A2AResult] | None = None,
    ) -> None:
        self._one_shot = one_shot
        self._streaming = streaming
        self._idempotency = idempotency_cache

    async def dispatch(self, message: A2AMessage, metadata: dict[str, Any]) -> A2AResult:
        """Run the one-shot path and wrap the returned text as `A2AResult`.

        Idempotency: if the handler has an attached cache AND the message's
        metadata carries `idempotency_key`, cache hits return the prior
        result without invoking the agent. Cache misses run the agent and
        cache the result before returning.

        The agent callable's exceptions propagate (and are NOT cached; a
        failed run doesn't dedup a future retry).
        """
        key = None
        if self._idempotency is not None:
            key = extract_idempotency_key(message.metadata)
            if key is None:
                key = extract_idempotency_key(metadata)
            if key is not None:
                cached = self._idempotency.get(key)
                if cached is not None:
                    return cached

        text = await self._one_shot(message, metadata)
        result = A2AResult(
            text=text,
            correlation_id=message.correlation_id,
            metadata={},
        )
        if self._idempotency is not None and key is not None:
            self._idempotency.put(key, result)
        return result

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
