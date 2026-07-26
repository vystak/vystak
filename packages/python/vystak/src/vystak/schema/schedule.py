"""ScheduledTask model — declarative + runtime-creatable agent schedules.

See docs/superpowers/specs/2026-07-25-scheduled-tasks-design.md.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Self
from zoneinfo import ZoneInfo

from croniter import croniter
from pydantic import BaseModel, Field, field_validator, model_validator

from vystak.schema.heartbeat import Heartbeat

_EVERY_RE = re.compile(r"^(\d+)([smhd])$")
_UNIT = {"s": "seconds", "m": "minutes", "h": "hours", "d": "days"}


def parse_every(s: str) -> timedelta:
    """Parse a duration string like '30s', '20m', '2h', '1d'."""
    m = _EVERY_RE.match(s)
    if m is None:
        raise ValueError(f"invalid duration {s!r}; use e.g. '30s', '20m', '2h', '1d'")
    n = int(m.group(1))
    if n <= 0:
        raise ValueError(f"duration must be positive, got {s!r}")
    return timedelta(**{_UNIT[m.group(2)]: n})


class ScheduledTask(BaseModel):
    """A schedule that fires a prompt at an agent.

    Exactly one of `cron`, `at`, `every` must be set.
    """

    name: str = Field(..., description="Unique per agent; reconciliation identity.")
    cron: str | None = Field(None, description="5-field cron expression.")
    at: datetime | None = Field(
        None, description="One-shot fire time (ISO-8601). Auto-completes after firing."
    )
    every: str | None = Field(
        None, description="Interval duration: '30s', '20m', '2h', '1d'."
    )
    timezone: str = Field("UTC", description="IANA timezone for cron/naive-at.")
    prompt: str | None = Field(None, description="Prompt sent to the agent on fire.")
    target_channel: str | None = Field(
        None, description="Channel canonical_name for result delivery. None → log only."
    )
    target_thread: str | None = None
    isolated_session: bool = True
    skip_when_busy: bool = True
    ack_max_chars: int | None = Field(
        None,
        ge=1,
        description="When set, replies containing HEARTBEAT_OK within this "
        "length are suppressed (heartbeat ack contract).",
    )
    model: str | None = Field(None, description="Model name from the agent's pool.")
    enabled: bool = True

    @field_validator("cron")
    @classmethod
    def _validate_cron(cls, v: str | None) -> str | None:
        if v is not None and (len(v.split()) != 5 or not croniter.is_valid(v)):
            raise ValueError(f"invalid 5-field cron expression: {v!r}")
        return v

    @field_validator("every")
    @classmethod
    def _validate_every(cls, v: str | None) -> str | None:
        if v is not None:
            parse_every(v)
        return v

    @field_validator("timezone")
    @classmethod
    def _validate_tz(cls, v: str) -> str:
        try:
            ZoneInfo(v)
        except Exception as e:
            raise ValueError(f"invalid IANA timezone {v!r}") from e
        return v

    @model_validator(mode="after")
    def _exactly_one_shape(self) -> Self:
        shapes = [s for s in (self.cron, self.at, self.every) if s is not None]
        if len(shapes) != 1:
            raise ValueError(
                "exactly one of cron | at | every must be set "
                f"(got {len(shapes)} on schedule '{self.name}')"
            )
        return self


def from_heartbeat(hb: Heartbeat) -> ScheduledTask:
    """Compile a Heartbeat declaration into its equivalent ScheduledTask.

    The task keeps `prompt=None` when the heartbeat has no prompt; the
    scheduler substitutes DEFAULT_PROMPT at fire time only for the task
    named 'heartbeat' (preserving HEARTBEAT.md semantics).
    """
    return ScheduledTask(
        name="heartbeat",
        cron=hb.schedule,
        timezone=hb.timezone,
        prompt=hb.prompt,
        target_channel=hb.target_channel,
        target_thread=hb.target_thread,
        isolated_session=hb.isolated_session,
        skip_when_busy=hb.skip_when_busy,
        ack_max_chars=hb.ack_max_chars,
        model=hb.model,
        enabled=hb.enabled,
    )
