"""Session checkpointer factory.

LangGraph 1.x checkpointers (AsyncSqliteSaver, AsyncPostgresSaver) are built
via async context managers. We can't materialize them sync at app construction
time. _LazyCheckpointer wraps a context-manager factory; the FastAPI lifespan
opens the context once at startup via AsyncExitStack and keeps it open for
the app's lifetime.
"""

from typing import Any


class _LazyCheckpointer:
    """Async-context-manager factory for a checkpointer.

    The factory returns whatever `AsyncSqliteSaver.from_conn_string` /
    `AsyncPostgresSaver.from_conn_string` returns — an async context manager
    whose `__aenter__` produces the actual saver instance. The lifespan opens
    the context with AsyncExitStack so the saver lives for the app's lifetime.
    """

    def __init__(self, cm_factory):  # noqa: ANN001
        self._cm_factory = cm_factory

    def context_manager(self):
        return self._cm_factory()


def build_checkpointer(agent: Any):
    sessions = getattr(agent, "sessions", None)
    if sessions is None:
        from langgraph.checkpoint.memory import MemorySaver
        return MemorySaver()

    engine = getattr(sessions, "engine", None)
    if engine == "sqlite":
        path = getattr(sessions, "path", None) or ":memory:"

        def _make_cm():
            from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
            return AsyncSqliteSaver.from_conn_string(path)

        return _LazyCheckpointer(_make_cm)

    if engine == "postgres":
        def _make_cm():
            from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
            return AsyncPostgresSaver.from_conn_string(sessions.connection_string)

        return _LazyCheckpointer(_make_cm)

    from langgraph.checkpoint.memory import MemorySaver
    return MemorySaver()
