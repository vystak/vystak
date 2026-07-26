from datetime import UTC, datetime, timedelta

from vystak.schema.schedule import ScheduledTask
from vystak_heartbeat.firing import classify_startup, compute_next_fire

NOW = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)   # a Saturday


class TestComputeNextFire:
    def test_cron_respects_timezone(self):
        t = ScheduledTask(name="d", cron="0 9 * * 1", timezone="America/New_York")
        nxt = compute_next_fire(t, NOW)
        # Monday 2026-07-27 09:00 EDT == 13:00 UTC
        assert nxt == datetime(2026, 7, 27, 13, 0, tzinfo=UTC)

    def test_every_adds_interval(self):
        t = ScheduledTask(name="p", every="20m")
        assert compute_next_fire(t, NOW) == NOW + timedelta(minutes=20)

    def test_at_returns_timestamp(self):
        when = NOW + timedelta(hours=3)
        t = ScheduledTask(name="o", at=when)
        assert compute_next_fire(t, NOW) == when

    def test_naive_at_localized_via_timezone_field(self):
        t = ScheduledTask(name="o", at=datetime(2026, 7, 27, 9, 0),
                          timezone="America/New_York")
        assert compute_next_fire(t, NOW) == datetime(2026, 7, 27, 13, 0, tzinfo=UTC)


class TestClassifyStartup:
    def test_recurring_skips_missed(self):
        t = ScheduledTask(name="d", cron="0 9 * * 1")
        action, nxt = classify_startup(t, NOW - timedelta(days=3), NOW)
        assert action == "schedule" and nxt > NOW

    def test_oneshot_future_scheduled(self):
        t = ScheduledTask(name="o", at=NOW + timedelta(hours=1))
        assert classify_startup(t, None, NOW) == ("schedule", NOW + timedelta(hours=1))

    def test_oneshot_missed_within_grace_fires_now(self):
        t = ScheduledTask(name="o", at=NOW - timedelta(hours=2))
        assert classify_startup(t, NOW - timedelta(hours=2), NOW)[0] == "fire-now"

    def test_oneshot_older_than_grace_marked_missed(self):
        t = ScheduledTask(name="o", at=NOW - timedelta(days=2))
        assert classify_startup(t, NOW - timedelta(days=2), NOW)[0] == "missed"

    def test_interval_recomputes_from_now(self):
        t = ScheduledTask(name="p", every="1h")
        action, nxt = classify_startup(t, NOW - timedelta(hours=5), NOW)
        assert action == "schedule" and nxt == NOW + timedelta(hours=1)
