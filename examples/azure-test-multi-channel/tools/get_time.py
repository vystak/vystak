"""Return the current time in UTC or in any IANA timezone."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def get_time(timezone_name: str = "UTC") -> str:
    """Get the current time.

    Args:
        timezone_name: An IANA timezone (e.g. "UTC", "America/Los_Angeles",
            "Europe/Lisbon", "Asia/Tokyo"). Pass "UTC" or omit for UTC.
            If the user mentioned a city or country, infer the matching
            IANA name (e.g. "Lisbon" -> "Europe/Lisbon", "PST" or
            "Pacific" -> "America/Los_Angeles", "ET" or "Eastern" ->
            "America/New_York").

    Returns a string like "2026-04-27 14:30:00 PDT (-0700)" so the
    consumer can see both the formatted local time and the offset.
    """
    if timezone_name in ("", "UTC", "utc", "Z", "z"):
        now = datetime.now(timezone.utc)
        return f"Current UTC time: {now.strftime('%Y-%m-%d %H:%M:%S UTC')}"
    try:
        tz = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        return (
            f"Unknown timezone: {timezone_name!r}. Use an IANA name like "
            f"'America/Los_Angeles', 'Europe/Lisbon', 'Asia/Tokyo'."
        )
    now = datetime.now(tz)
    return (
        f"Current time in {timezone_name}: "
        f"{now.strftime('%Y-%m-%d %H:%M:%S %Z (%z)')}"
    )
