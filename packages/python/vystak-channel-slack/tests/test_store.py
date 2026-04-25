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


def test_set_and_get_thread_binding(store):
    store.set_thread_binding("T1", "C1", "1700.111", "weather-agent")
    assert store.thread_binding("T1", "C1", "1700.111") == "weather-agent"


def test_unknown_thread_returns_none(store):
    assert store.thread_binding("T1", "C1", "1700.999") is None


def test_overwrite_thread_binding(store):
    store.set_thread_binding("T1", "C1", "1700.111", "weather-agent")
    store.set_thread_binding("T1", "C1", "1700.111", "support-agent")
    assert store.thread_binding("T1", "C1", "1700.111") == "support-agent"


def test_unbind_thread(store):
    store.set_thread_binding("T1", "C1", "1700.111", "weather-agent")
    store.unbind_thread("T1", "C1", "1700.111")
    assert store.thread_binding("T1", "C1", "1700.111") is None


def test_thread_bindings_isolated_by_channel_and_team(store):
    store.set_thread_binding("T1", "C1", "1700.111", "weather-agent")
    # Different channel, same thread_ts
    assert store.thread_binding("T1", "C2", "1700.111") is None
    # Different team, same channel + thread_ts
    assert store.thread_binding("T2", "C1", "1700.111") is None


def test_migrate_creates_thread_bindings_table(tmp_path):
    """Re-uses the existing idempotent migration test pattern."""
    import sqlite3

    from vystak_channel_slack.store import SqliteStore

    db = tmp_path / "state.db"
    s = SqliteStore(path=str(db))
    s.migrate()
    s.migrate()  # idempotent

    conn = sqlite3.connect(str(db))
    try:
        names = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    finally:
        conn.close()
    assert "thread_bindings" in names
