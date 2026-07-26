"""Next-fire computation and restart (missed-fire) policy."""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from croniter import croniter
from vystak.schema.schedule import ScheduledTask, parse_every

GRACE_WINDOW_S = 86400


def _as_utc(dt: datetime, tz_name: str) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo(tz_name))
    return dt.astimezone(UTC)


def compute_next_fire(task: ScheduledTask, now: datetime) -> datetime | None:
    if task.cron is not None:
        tz = ZoneInfo(task.timezone)
        nxt = croniter(task.cron, now.astimezone(tz)).get_next(datetime)
        return nxt.astimezone(UTC)
    if task.every is not None:
        return now + parse_every(task.every)
    if task.at is not None:
        return _as_utc(task.at, task.timezone)
    return None


def classify_startup(
    task: ScheduledTask, stored_next: datetime | None, now: datetime
) -> tuple[str, datetime | None]:
    if task.at is not None:
        when = _as_utc(task.at, task.timezone)
        if when > now:
            return ("schedule", when)
        if (now - when).total_seconds() <= GRACE_WINDOW_S:
            return ("fire-now", None)
        return ("missed", None)
    # Recurring: never replay — always recompute strictly from now.
    return ("schedule", compute_next_fire(task, now))
