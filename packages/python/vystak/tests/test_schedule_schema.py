from datetime import timedelta

import pytest
from pydantic import ValidationError
from vystak.schema.schedule import ScheduledTask, parse_every  # noqa: E402


def _mk(**kw):
    base = {"name": "t1", "cron": "0 9 * * 1"}
    base.update(kw)
    return ScheduledTask.model_validate(base)


class TestShapeValidation:
    def test_cron_ok(self):
        t = _mk()
        assert t.cron == "0 9 * * 1" and t.at is None and t.every is None

    def test_at_ok(self):
        t = ScheduledTask(name="r", at="2026-08-01T09:00:00+00:00")
        assert t.at is not None

    def test_every_ok(self):
        t = ScheduledTask(name="p", every="20m")
        assert t.every == "20m"

    def test_no_shape_rejected(self):
        with pytest.raises(ValidationError, match="exactly one"):
            ScheduledTask(name="x")

    def test_two_shapes_rejected(self):
        with pytest.raises(ValidationError, match="exactly one"):
            ScheduledTask(name="x", cron="* * * * *", every="5m")

    def test_bad_cron_rejected(self):
        with pytest.raises(ValidationError):
            ScheduledTask(name="x", cron="not a cron")

    def test_bad_every_rejected(self):
        with pytest.raises(ValidationError):
            ScheduledTask(name="x", every="fortnightly")

    def test_bad_timezone_rejected(self):
        with pytest.raises(ValidationError):
            ScheduledTask(name="x", cron="* * * * *", timezone="Mars/Olympus")


class TestParseEvery:
    @pytest.mark.parametrize("s,td", [
        ("30s", timedelta(seconds=30)),
        ("20m", timedelta(minutes=20)),
        ("2h", timedelta(hours=2)),
        ("1d", timedelta(days=1)),
    ])
    def test_units(self, s, td):
        assert parse_every(s) == td

    def test_rejects_zero(self):
        with pytest.raises(ValueError):
            parse_every("0m")


class TestDefaults:
    def test_defaults(self):
        t = _mk()
        assert t.timezone == "UTC"
        assert t.target_channel is None and t.target_thread is None
        assert t.isolated_session is True and t.skip_when_busy is True
        assert t.ack_max_chars is None and t.model is None and t.enabled is True


class TestAgentSchedules:
    def _agent(self, schedules):
        from vystak.schema import Agent, Model
        from vystak.schema.provider import Provider
        return Agent(
            name="a",
            framework="langchain-python",
            default_model=Model(
                name="m",
                provider=Provider(name="anthropic", type="anthropic"),
                model_name="claude-sonnet-4-20250514",
            ),
            schedules=schedules,
        )

    def test_agent_accepts_schedules(self):
        a = self._agent([{"name": "digest", "cron": "0 9 * * 1"}])
        assert a.schedules[0].name == "digest"

    def test_duplicate_names_rejected(self):
        with pytest.raises(ValidationError, match="duplicate schedule name"):
            self._agent([{"name": "d", "cron": "* * * * *"},
                         {"name": "d", "every": "5m"}])

    def test_reserved_heartbeat_name_rejected(self):
        with pytest.raises(ValidationError, match="reserved"):
            self._agent([{"name": "heartbeat", "cron": "* * * * *"}])
