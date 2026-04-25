from datetime import datetime, timezone


def get_time(location: str = "UTC") -> str:
    """Get the current UTC time."""
    now = datetime.now(timezone.utc)
    return f"Current UTC time: {now.strftime('%Y-%m-%d %H:%M:%S UTC')}"
