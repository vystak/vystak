"""build_checkpointer factory dispatches on agent.sessions.engine."""

import os
from unittest import mock

from _vystak.runtime.store import build_checkpointer


class _Sessions:
    def __init__(self, engine: str | None = None, connection_string: str | None = None):
        self.engine = engine
        self.connection_string = connection_string


def _agent(sessions=None):
    class _A:
        pass
    a = _A()
    a.sessions = sessions
    return a


def test_no_sessions_returns_durable_lazy_checkpointer(tmp_path):
    # Durable by default: even with no sessions declared, build_checkpointer
    # returns a _LazyCheckpointer wrapping AsyncSqliteSaver, never MemorySaver.
    with mock.patch.dict(os.environ, {"VYSTAK_SESSIONS_PATH": str(tmp_path / "s.db")}):
        cp = build_checkpointer(_agent(sessions=None))
    assert cp.__class__.__name__ == "_LazyCheckpointer"


def test_sqlite_returns_async_sqlite_saver_factory():
    cp = build_checkpointer(_agent(sessions=_Sessions(engine="sqlite")))
    assert cp.__class__.__name__ in {"AsyncSqliteSaver", "_LazyCheckpointer"}


def test_postgres_returns_postgres_saver_factory():
    sessions = _Sessions(engine="postgres", connection_string="postgresql://x")
    cp = build_checkpointer(_agent(sessions=sessions))
    assert cp.__class__.__name__ in {"AsyncPostgresSaver", "_LazyCheckpointer"}
