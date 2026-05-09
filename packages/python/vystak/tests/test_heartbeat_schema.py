"""Schema-level tests for the Heartbeat model."""

import pytest
from pydantic import ValidationError

from vystak.schema.heartbeat import Heartbeat


def test_minimal_heartbeat_round_trips():
    hb = Heartbeat(
        schedule="*/30 * * * *",
        target_channel="slack-main.channels.dev",
    )
    assert hb.schedule == "*/30 * * * *"
    assert hb.timezone == "UTC"
    assert hb.target_channel == "slack-main.channels.dev"
    assert hb.target_thread is None
    assert hb.prompt is None
    assert hb.isolated_session is True
    assert hb.skip_when_busy is True
    assert hb.ack_max_chars == 300
    assert hb.enabled is True


def test_full_heartbeat_round_trips():
    hb = Heartbeat(
        schedule="0 9 * * 1-5",
        timezone="America/New_York",
        target_channel="slack-main.channels.dev",
        target_thread="C0123456789",
        prompt="Custom prompt",
        isolated_session=False,
        skip_when_busy=False,
        ack_max_chars=500,
        enabled=False,
    )
    dumped = hb.model_dump()
    restored = Heartbeat.model_validate(dumped)
    assert restored == hb


def test_invalid_cron_rejected():
    with pytest.raises(ValidationError) as exc:
        Heartbeat(
            schedule="every 30 minutes",
            target_channel="x.channels.dev",
        )
    assert "invalid cron expression" in str(exc.value)


def test_target_channel_required():
    with pytest.raises(ValidationError):
        Heartbeat(schedule="*/30 * * * *")  # type: ignore[call-arg]


def test_complex_cron_accepted():
    """5-field cron with day-of-week ranges should validate."""
    hb = Heartbeat(
        schedule="*/15 9-22 * * 1-5",
        target_channel="x.channels.dev",
    )
    assert hb.schedule == "*/15 9-22 * * 1-5"
