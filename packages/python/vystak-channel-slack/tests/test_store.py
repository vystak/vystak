import pytest
from vystak_channel_slack.store import SqliteStore


@pytest.fixture
def store(tmp_path):
    s = SqliteStore(path=str(tmp_path / "state.db"))
    s.migrate()
    return s


def test_set_and_get_channel_binding(store):
    store.set_channel_binding("T1", "C1", "weather-agent", "U1")
    assert store.channel_binding("T1", "C1") == "weather-agent"


def test_unknown_channel_returns_none(store):
    assert store.channel_binding("T1", "C-ghost") is None


def test_overwrite_channel_binding(store):
    store.set_channel_binding("T1", "C1", "weather-agent", "U1")
    store.set_channel_binding("T1", "C1", "support-agent", "U1")
    assert store.channel_binding("T1", "C1") == "support-agent"


def test_user_preference_round_trip(store):
    store.set_user_pref("T1", "U1", "weather-agent")
    assert store.user_pref("T1", "U1") == "weather-agent"


def test_record_inviter_round_trip(store):
    store.record_inviter("T1", "C1", "U1")
    assert store.inviter("T1", "C1") == "U1"


def test_unbind_channel(store):
    store.set_channel_binding("T1", "C1", "weather-agent", "U1")
    store.unbind_channel("T1", "C1")
    assert store.channel_binding("T1", "C1") is None


def test_migrate_idempotent(tmp_path):
    s = SqliteStore(path=str(tmp_path / "state.db"))
    s.migrate()
    s.migrate()
    s.set_channel_binding("T", "C", "w", "U")
    assert s.channel_binding("T", "C") == "w"
