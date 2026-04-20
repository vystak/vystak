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
from typing import Any, Protocol, runtime_checkable

from vystak.transport.types import (
    A2AEvent,
    A2AMessage,
    A2AResult,
    AgentRef,
)


@runtime_checkable
class A2AHandlerProtocol(Protocol):
    """Narrow pre-Plan-C protocol for A2A-only handlers.

    Retained for backward compatibility with callers that operate exclusively
    against A2A dispatch. Plan C's transport listener uses
    :class:`ServerDispatcherProtocol`, which exposes both A2A and Responses API
    dispatch methods under distinct names.
    """

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


@runtime_checkable
class ServerDispatcherProtocol(Protocol):
    """Full server-side dispatcher covering both A2A and Responses API methods.

    Concrete transport listeners receive an instance of this protocol (typically
    a ServerDispatcher from the adapter) and route incoming JSON-RPC messages
    to the appropriate method.
    """

    async def dispatch_a2a(self, message: A2AMessage, metadata: dict[str, Any]) -> A2AResult: ...

    async def dispatch_a2a_stream(
        self, message: A2AMessage, metadata: dict[str, Any]
    ) -> AsyncIterator[A2AEvent]: ...

    async def dispatch_responses_create(
        self, request: dict[str, Any], metadata: dict[str, Any]
    ) -> dict[str, Any]: ...

    async def dispatch_responses_create_stream(
        self, request: dict[str, Any], metadata: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]: ...

    async def dispatch_responses_get(self, response_id: str) -> dict[str, Any] | None: ...


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
    async def serve(self, canonical_name: str, handler: ServerDispatcherProtocol) -> None:
        """Join the load-balanced group for this agent and feed incoming
        messages into `handler`.

        `canonical_name` is the full `{name}.agents.{ns}` identifier; the
        transport derives its own subject / queue / URL routing from it.

        `handler` implements :class:`ServerDispatcherProtocol` and fans
        incoming JSON-RPC methods out to the appropriate handler (A2A vs
        Responses API).

        For the HTTP transport this is typically a no-op (FastAPI's /a2a
        route is already running).
        """

    async def create_response(
        self,
        agent: AgentRef,
        request: dict[str, Any],
        metadata: dict[str, Any],
        *,
        timeout: float,
    ) -> dict[str, Any]:
        """One-shot OpenAI Responses API create. Returns the ResponseObject dict.

        Transports with native Responses API support must override this.
        Default raises NotImplementedError.
        """
        raise NotImplementedError(f"{type(self).__name__} does not implement create_response")

    async def create_response_stream(
        self,
        agent: AgentRef,
        request: dict[str, Any],
        metadata: dict[str, Any],
        *,
        timeout: float,
    ) -> AsyncIterator[dict[str, Any]]:
        """Streamed Responses API create. Default: degrade to one-shot + terminal chunk.

        Transports with native streaming support override.
        """
        result = await self.create_response(agent, request, metadata, timeout=timeout)
        yield {"type": "response.completed", "response": result}

    async def get_response(
        self,
        agent: AgentRef,
        response_id: str,
        *,
        timeout: float,
    ) -> dict[str, Any] | None:
        """Fetch a stored ResponseObject by id. Returns None if not found.

        Transports with native Responses API support must override this.
        Default raises NotImplementedError.
        """
        raise NotImplementedError(f"{type(self).__name__} does not implement get_response")
