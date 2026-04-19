"""Transport abstract base class.

A Transport carries A2A traffic between agents and channels. Every Platform
selects exactly one Transport; all east-west A2A calls flow over it.

Implementations must provide:

- `resolve_address(canonical_name)` — turn a canonical name into the wire
  address format native to this transport.
- `send_task()` — one-shot request/reply.
- `serve()` — listener side; join the load-balanced group for the agent
  and dispatch incoming messages to the provided handler.

Streaming is optional (see `supports_streaming`). The default `stream_task()`
implementation degrades to `send_task()` and emits a single terminal event.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable

from vystak.transport.types import (
    A2AEvent,
    A2AMessage,
    A2AResult,
    AgentRef,
)


@runtime_checkable
class A2AHandlerProtocol(Protocol):
    """Structural type for A2AHandler — avoids a circular import."""

    async def dispatch(
        self,
        message: A2AMessage,
        metadata: dict,
    ) -> A2AResult: ...

    async def dispatch_stream(
        self,
        message: A2AMessage,
        metadata: dict,
    ) -> AsyncIterator[A2AEvent]: ...


class Transport(ABC):
    """Base class for all transports."""

    type: str = ""
    supports_streaming: bool = False

    @abstractmethod
    def resolve_address(self, canonical_name: str) -> str:
        """Derive the wire address for an agent on this transport."""

    @abstractmethod
    async def send_task(
        self,
        agent: AgentRef,
        message: A2AMessage,
        metadata: dict,
        *,
        timeout: float,
    ) -> A2AResult:
        """One-shot request/reply."""

    async def stream_task(
        self,
        agent: AgentRef,
        message: A2AMessage,
        metadata: dict,
        *,
        timeout: float,
    ) -> AsyncIterator[A2AEvent]:
        """Stream events back. Default: call send_task and emit one final event.

        Concrete transports that support native streaming must override this.
        """
        result = await self.send_task(agent, message, metadata, timeout=timeout)
        yield A2AEvent(type="final", text=result.text, final=True)

    @abstractmethod
    async def serve(self, canonical_name: str, handler: A2AHandlerProtocol) -> None:
        """Join the load-balanced group for this agent and feed incoming
        messages into `handler`.

        `canonical_name` is the full `{name}.agents.{ns}` identifier; the
        transport derives its own subject / queue / URL routing from it.

        For the HTTP transport this is typically a no-op (FastAPI's /a2a
        route is already running).
        """
