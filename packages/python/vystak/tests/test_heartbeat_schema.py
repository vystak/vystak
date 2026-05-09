"""Schema-level tests for the Heartbeat model."""

import pytest
from pydantic import ValidationError
from vystak.schema import Agent, Heartbeat, Model, Provider


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
    # "every 30 minutes" has 3 words so the 5-field check fires first;
    # either message confirms the schedule was rejected.
    assert "cron expression" in str(exc.value)


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


def test_six_field_cron_rejected():
    """6-field (second-precision) cron should be rejected — runtime is 5-field only."""
    with pytest.raises(ValidationError) as exc:
        Heartbeat(
            schedule="*/10 * * * * *",
            target_channel="x.channels.dev",
        )
    assert "5 fields" in str(exc.value)


def test_ack_max_chars_must_be_positive():
    with pytest.raises(ValidationError):
        Heartbeat(
            schedule="*/30 * * * *",
            target_channel="x.channels.dev",
            ack_max_chars=0,
        )


def test_invalid_timezone_rejected():
    with pytest.raises(ValidationError) as exc:
        Heartbeat(
            schedule="*/30 * * * *",
            target_channel="x.channels.dev",
            timezone="Americka/New_York",   # typo
        )
    assert "unknown IANA timezone" in str(exc.value)


def _model() -> Model:
    return Model(
        name="claude",
        provider=Provider(name="anthropic", type="anthropic"),
        model_name="claude-sonnet-4-6",
    )


def test_agent_without_heartbeat_default_none():
    agent = Agent(name="bot", framework="langchain-python", model=_model())
    assert agent.heartbeat is None


def test_agent_with_heartbeat_round_trips():
    agent = Agent(
        name="bot",
        framework="langchain-python",
        model=_model(),
        heartbeat=Heartbeat(
            schedule="*/5 * * * *",
            target_channel="x.channels.dev",
        ),
    )
    dumped = agent.model_dump()
    restored = Agent.model_validate(dumped)
    assert restored.heartbeat is not None
    assert restored.heartbeat.schedule == "*/5 * * * *"


def test_heartbeat_exported_from_schema():
    """Importable from the top-level schema package."""
    from vystak.schema import Heartbeat as Exported

    assert Exported is Heartbeat
