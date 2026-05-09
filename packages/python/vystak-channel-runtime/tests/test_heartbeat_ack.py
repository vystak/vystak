"""Tests for the heartbeat ack-stripping function."""

import pytest
from vystak_channel_runtime.heartbeat import HEARTBEAT_OK, is_heartbeat_ok


@pytest.mark.parametrize(
    "text",
    [
        "HEARTBEAT_OK",
        "  HEARTBEAT_OK\n",
        "HEARTBEAT_OK\n\n",
        "All good. HEARTBEAT_OK",
        "HEARTBEAT_OK — nothing to report.",
    ],
)
def test_short_replies_with_sentinel_drop(text: str):
    assert is_heartbeat_ok(text, max_chars=300) is True


@pytest.mark.parametrize(
    "text",
    [
        "All clear, nothing to report.",
        "User mentioned X needs review.",
        "HEARTBEATOK",  # missing underscore
        "HEARTBEAT-OK",
    ],
)
def test_replies_without_sentinel_post(text: str):
    assert is_heartbeat_ok(text, max_chars=300) is False


def test_empty_or_whitespace_does_not_drop():
    """Empty replies should NOT silently swallow — they signal a real bug."""
    assert is_heartbeat_ok("", max_chars=300) is False
    assert is_heartbeat_ok("   \n\t  ", max_chars=300) is False


def test_long_reply_with_sentinel_posts():
    """Replies longer than ack_max_chars are always delivered."""
    body = "x" * 400
    text = f"{body} {HEARTBEAT_OK}"
    assert is_heartbeat_ok(text, max_chars=300) is False


def test_exactly_max_chars_with_sentinel_drops():
    text = ("HEARTBEAT_OK " * 10).strip()  # well under 300
    assert is_heartbeat_ok(text, max_chars=300) is True
