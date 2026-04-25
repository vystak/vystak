from unittest.mock import patch

import pytest
from vystak.schema.service import Postgres, Sqlite
from vystak_channel_slack.store import PostgresStore, SqliteStore, make_store


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


@pytest.mark.skip(reason="needs Postgres — covered by integration test")
def test_postgres_store_round_trip():
    """Live Postgres test — covered by docker-marked integration test."""


def test_make_store_dispatches_sqlite(tmp_path):
    svc = Sqlite(name="x", path=str(tmp_path / "x.db"))
    s = make_store(svc)
    assert isinstance(s, SqliteStore)


def test_make_store_dispatches_postgres_by_env_var(monkeypatch):
    monkeypatch.setenv("SLACK_STATE_URL", "postgresql://stub")
    svc = Postgres(name="x", connection_string_env="SLACK_STATE_URL")
    with patch("vystak_channel_slack.store.psycopg.connect"):
        s = make_store(svc)
    assert isinstance(s, PostgresStore)


def test_make_store_rejects_unknown_type():
    class FakeService:
        type = "bogus"

    with pytest.raises(ValueError, match="unsupported"):
        make_store(FakeService())


def test_postgres_store_uses_psycopg_connect_with_dsn():
    """Constructor stores DSN; connection happens lazily inside _conn()."""
    s = PostgresStore(dsn="postgresql://example")
    assert s._dsn == "postgresql://example"
