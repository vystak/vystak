"""build_checkpointer factory dispatches on agent.sessions.engine."""

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


def test_no_sessions_returns_in_memory_saver():
    cp = build_checkpointer(_agent(sessions=None))
    # langgraph 1.x renamed MemorySaver -> InMemorySaver while keeping the
    # MemorySaver alias importable. Accept either class name.
    assert cp.__class__.__name__ in {"MemorySaver", "InMemorySaver"}


def test_sqlite_returns_async_sqlite_saver_factory():
    cp = build_checkpointer(_agent(sessions=_Sessions(engine="sqlite")))
    assert cp.__class__.__name__ in {"AsyncSqliteSaver", "_LazyCheckpointer"}


def test_postgres_returns_postgres_saver_factory():
    sessions = _Sessions(engine="postgres", connection_string="postgresql://x")
    cp = build_checkpointer(_agent(sessions=sessions))
    assert cp.__class__.__name__ in {"AsyncPostgresSaver", "_LazyCheckpointer"}
