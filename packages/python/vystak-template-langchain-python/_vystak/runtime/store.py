"""Session checkpointer factory.

LangGraph 1.x checkpointers (AsyncSqliteSaver, AsyncPostgresSaver) are built
via async context managers. We can't materialize them sync at app construction
time. _LazyCheckpointer wraps a context-manager factory; the FastAPI lifespan
opens the context once at startup via AsyncExitStack and keeps it open for
the app's lifetime.
"""

import os
import tempfile
from typing import Any

_DATA_DIR = "/data"


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


def resolve_sessions_path() -> str:
    """Resolve the default checkpointer path.

    Chain: VYSTAK_SESSIONS_PATH -> /data/sessions.db (when /data exists and is
    writable, i.e. the deployed container) -> a temp-dir path (unit tests, dev
    machines, and any platform that mounts no volume).
    """
    override = os.environ.get("VYSTAK_SESSIONS_PATH")
    if override:
        return override
    if os.path.isdir(_DATA_DIR) and os.access(_DATA_DIR, os.W_OK):
        return os.path.join(_DATA_DIR, "sessions.db")
    return os.path.join(tempfile.gettempdir(), "vystak-sessions.db")


def build_checkpointer(agent: Any):
    sessions = getattr(agent, "sessions", None)
    engine = getattr(sessions, "engine", None) if sessions is not None else None

    if engine == "postgres":
        def _make_pg_cm():
            from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
            return AsyncPostgresSaver.from_conn_string(sessions.connection_string)

        return _LazyCheckpointer(_make_pg_cm)

    if engine == "sqlite":
        path = getattr(sessions, "path", None) or resolve_sessions_path()
    else:
        # No sessions declared: durable by default rather than in-memory.
        path = resolve_sessions_path()

    def _make_cm():
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
        return AsyncSqliteSaver.from_conn_string(path)

    return _LazyCheckpointer(_make_cm)


class _LazyStore:
    """Async-context-manager factory for a long-term memory store.

    Same shape as _LazyCheckpointer; the lifespan opens the context via
    AsyncExitStack and keeps the resolved store for the app's lifetime.
    """

    def __init__(self, cm_factory):  # noqa: ANN001
        self._cm_factory = cm_factory

    def context_manager(self):
        return self._cm_factory()


def build_memory_store(agent: Any):
    """Build a LangGraph BaseStore for long-term memory.

    Reads agent.memory.engine. Returns InMemoryStore (sync, no lifespan) or
    a _LazyStore wrapping AsyncPostgresStore (resolved via lifespan).
    """
    import os

    memory = getattr(agent, "memory", None)
    if memory is None:
        return None

    engine = getattr(memory, "engine", None)

    if engine == "postgres":
        conn = (
            os.environ.get("MEMORY_STORE_URL")
            or getattr(memory, "connection_string", None)
        )

        def _make_cm():
            from langgraph.store.postgres.aio import AsyncPostgresStore
            return AsyncPostgresStore.from_conn_string(conn)

        return _LazyStore(_make_cm)

    # in-memory fallback for any other / unset engine
    from langgraph.store.memory import InMemoryStore
    return InMemoryStore()
