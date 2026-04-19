"""Caller-side client for agent-to-agent and channel-to-agent traffic.

AgentClient wraps a Transport with a short-name → canonical-name route map.
The helper `ask_agent()` is a one-shot convenience.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from vystak.transport.base import Transport
from vystak.transport.types import (
    A2AEvent,
    A2AMessage,
    AgentRef,
)

DEFAULT_TIMEOUT = 60.0


class AgentClient:
    """Transport-agnostic client for calling peer agents.

    Users call `send_task("short-name", text)` — the client looks up the
    canonical name in its route map and delegates to the transport.
    """

    def __init__(
        self,
        *,
        transport: Transport,
        routes: dict[str, str],
    ) -> None:
        self._transport = transport
        self._routes = dict(routes)

    @property
    def transport(self) -> Transport:
        return self._transport

    async def send_task(
        self,
        agent: str,
        text: str | A2AMessage,
        *,
        metadata: dict[str, Any] | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> str:
        ref = self._resolve(agent)
        message = (
            text
            if isinstance(text, A2AMessage)
            else A2AMessage.from_text(text, metadata=metadata)
        )
        result = await self._transport.send_task(
            ref, message, metadata or {}, timeout=timeout
        )
        return result.text

    async def stream_task(
        self,
        agent: str,
        text: str | A2AMessage,
        *,
        metadata: dict[str, Any] | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> AsyncIterator[A2AEvent]:
        ref = self._resolve(agent)
        message = (
            text
            if isinstance(text, A2AMessage)
            else A2AMessage.from_text(text, metadata=metadata)
        )
        async for event in self._transport.stream_task(
            ref, message, metadata or {}, timeout=timeout
        ):
            yield event

    def _resolve(self, short_name: str) -> AgentRef:
        try:
            canonical = self._routes[short_name]
        except KeyError:
            raise KeyError(
                f"unknown agent {short_name!r}; known: {sorted(self._routes)}"
            ) from None
        return AgentRef(canonical_name=canonical)


# --- one-shot helper ---

_DEFAULT_CLIENT: AgentClient | None = None


def _default_client() -> AgentClient:
    """Build (once) and return the process-level AgentClient from env vars.

    The env contract is populated at deploy time by the provider + transport
    plugin. Stub behaviour here: raise if not configured — `ask_agent`
    callers during tests should pass `client=` explicitly.
    """
    global _DEFAULT_CLIENT
    if _DEFAULT_CLIENT is not None:
        return _DEFAULT_CLIENT
    raise RuntimeError(
        "ask_agent() default client not configured; pass client= explicitly "
        "or install a transport via AgentClient.install_default_from_env()"
    )


async def ask_agent(
    agent: str,
    question: str,
    *,
    metadata: dict[str, Any] | None = None,
    client: AgentClient | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> str:
    """Short helper for one-shot agent calls.

    Example:
        from vystak.transport import ask_agent
        reply = await ask_agent("time-agent", "what time is it?")
    """
    c = client or _default_client()
    return await c.send_task(
        agent, question, metadata=metadata, timeout=timeout
    )
