"""Core types shared across the channel runtime."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from vystak.schema.common import ChannelType


class Message(BaseModel):
    """A single turn in conversation history (matches A2A history shape)."""

    role: Literal["user", "assistant", "system", "tool"]
    content: str
    name: str | None = None


class AgentReply(BaseModel):
    """Result of a non-streaming agent turn."""

    text: str
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    finish_reason: str | None = None
    raw: dict[str, Any] | None = None
    pending_approval: dict[str, Any] | None = None


class AgentChunk(BaseModel):
    """One streaming event from an agent.

    Maps to the agent's emitted A2A wire shapes:
      * "token"      — delta text from on_chat_model_stream
      * "tool_call"  — agent invoked a tool (tool_name in data)
      * "tool_result"— tool finished (tool_name + duration in data)
      * "status"     — interim status update (text in delta)
      * "final"      — turn finished (final=True)
    """

    type: Literal["token", "tool_call", "tool_result", "status", "final"] = "token"
    delta: str = ""
    tool_name: str | None = None
    data: dict[str, Any] | None = None
    finish_reason: str | None = None
    final: bool = False
    raw: dict[str, Any] | None = None


class InboundEvent(BaseModel):
    """A platform-agnostic event entering the channel runtime."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    channel_type: ChannelType
    scope_id: str
    thread_id: str | None
    user_id: str
    text: str
    is_dm: bool
    mentions_bot: bool
    metadata: dict[str, Any] = Field(default_factory=dict)
    raw: Any = None


class ThreadBinding(BaseModel):
    """A persisted binding between a thread and an agent."""

    channel_type: str
    scope_id: str
    thread_id: str
    agent_name: str
    user_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class SkipEvent(Exception):
    """Raised by parse_event() to silently drop an event from the pipeline."""


class AgentCallError(Exception):
    """Raised by call_agent() when the agent call fails after retries."""
