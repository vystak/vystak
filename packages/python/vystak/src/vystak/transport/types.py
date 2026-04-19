"""A2A envelope types carried across every transport.

The wire format on every transport is the same JSON-RPC A2A envelope that
`vystak-adapter-langchain/a2a.py` emits today. These classes are the
in-process representation used by the transport ABC and the A2AHandler.
"""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, Field, field_validator

from vystak.transport.naming import parse_canonical_name


class AgentRef(BaseModel):
    """Transport-facing identity for a peer agent.

    Carries only the canonical name; the wire address is derived by the
    active transport at call time via `Transport.resolve_address()`.
    """

    canonical_name: str

    @field_validator("canonical_name")
    @classmethod
    def _validate_canonical(cls, v: str) -> str:
        # Raises ValueError if malformed, which Pydantic converts into
        # ValidationError.
        parse_canonical_name(v)
        return v


class A2AMessage(BaseModel):
    """A single A2A message (a task's input or output)."""

    role: str = "user"
    parts: list[dict[str, Any]] = Field(default_factory=list)
    correlation_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_text(
        cls,
        text: str,
        *,
        role: str = "user",
        correlation_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> A2AMessage:
        kwargs: dict[str, Any] = {
            "role": role,
            "parts": [{"text": text}],
            "metadata": metadata or {},
        }
        if correlation_id is not None:
            kwargs["correlation_id"] = correlation_id
        return cls(**kwargs)


class A2AEvent(BaseModel):
    """A single streaming event emitted by `tasks/sendSubscribe`."""

    type: str  # "token" | "status" | "tool_call" | "tool_result" | "final"
    text: str | None = None
    data: dict[str, Any] | None = None
    final: bool = False


class A2AResult(BaseModel):
    """Result of a one-shot `tasks/send` call."""

    text: str
    correlation_id: str
    metadata: dict[str, Any] = Field(default_factory=dict)
