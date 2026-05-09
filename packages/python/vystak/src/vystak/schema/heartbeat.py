"""Heartbeat model — periodic agent self-invocation configuration.

See docs/superpowers/specs/2026-05-09-heartbeat-design.md for the design
rationale. The heartbeat is declared on the Agent; the channel named in
`target_channel` hosts the scheduler at runtime.
"""

from __future__ import annotations

from croniter import croniter
from pydantic import BaseModel, Field, field_validator


class Heartbeat(BaseModel):
    """Periodic agent self-invocation, fired by the channel named in
    `target_channel`."""

    schedule: str = Field(
        ...,
        description="5-field cron expression, e.g. '*/30 * * * *'.",
    )
    timezone: str = Field(
        "UTC",
        description="IANA timezone name for cron evaluation.",
    )
    target_channel: str = Field(
        ...,
        description="Channel canonical_name (e.g. 'slack-main.channels.dev').",
    )
    target_thread: str | None = Field(
        None,
        description=(
            "Specific delivery thread/scope id. If None, the channel runtime "
            "resolves at fire time from the most recent ThreadBinding for "
            "this agent."
        ),
    )
    prompt: str | None = Field(
        None,
        description=(
            "Override the built-in heartbeat prompt. None uses the default."
        ),
    )
    isolated_session: bool = Field(
        True,
        description=(
            "When True, the fire uses a synthetic scope/thread so it doesn't "
            "pollute the user-visible session history."
        ),
    )
    skip_when_busy: bool = Field(
        True,
        description=(
            "Skip a fire if a previous heartbeat is still in flight. Does "
            "not coordinate with concurrent user turns."
        ),
    )
    ack_max_chars: int = Field(
        300,
        description=(
            "Maximum reply length to scan for HEARTBEAT_OK. Replies longer "
            "than this are always delivered."
        ),
    )
    enabled: bool = Field(
        True,
        description="Set False to keep config but disable scheduling.",
    )

    @field_validator("schedule")
    @classmethod
    def _validate_cron(cls, v: str) -> str:
        if not croniter.is_valid(v):
            raise ValueError(f"invalid cron expression: {v!r}")
        return v
