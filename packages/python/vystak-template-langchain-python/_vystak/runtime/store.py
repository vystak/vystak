"""Session checkpointer factory."""

from typing import Any


class _LazyCheckpointer:
    """Wraps an async-only saver behind a sync factory; resolved at app startup."""

    def __init__(self, factory):  # noqa: ANN001
        self._factory = factory

    async def aresolve(self):
        return await self._factory()


def build_checkpointer(agent: Any):
    sessions = getattr(agent, "sessions", None)
    if sessions is None:
        from langgraph.checkpoint.memory import MemorySaver
        return MemorySaver()

    engine = getattr(sessions, "engine", None)
    if engine == "sqlite":
        async def _make():
            from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
            return AsyncSqliteSaver.from_conn_string(":memory:")
        return _LazyCheckpointer(_make)

    if engine == "postgres":
        async def _make():
            from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
            return AsyncPostgresSaver.from_conn_string(sessions.connection_string)
        return _LazyCheckpointer(_make)

    from langgraph.checkpoint.memory import MemorySaver
    return MemorySaver()
