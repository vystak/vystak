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

from langgraph.checkpoint.base import BaseCheckpointSaver

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


def _resolve_connection_string(service: Any, injected_env_var: str) -> str | None:
    """Resolve a Postgres connection string for a `sessions`/`memory` service.

    Resolution order mirrors what the docker provider actually wires up:
    1. `injected_env_var` (e.g. `SESSION_STORE_URL` / `MEMORY_STORE_URL`) —
       set by the provider at deploy time from the provisioned service's
       connection string (`nodes/agent.py`'s `dep_result.info["connection_string"]`).
       This is the path every managed-service deploy takes.
    2. `service.connection_string_env` — for BYO/unmanaged services (the
       schema's `Service.is_managed` is False when this is set), the name of
       an env var *this* process should read the connection string from.
       Note this is a var *name*, not the connection string itself — there
       is no `Service.connection_string` field.
    """
    value = os.environ.get(injected_env_var)
    if value:
        return value
    env_name = getattr(service, "connection_string_env", None)
    if env_name:
        return os.environ.get(env_name)
    return None


def build_checkpointer(agent: Any):
    sessions = getattr(agent, "sessions", None)
    engine = getattr(sessions, "engine", None) if sessions is not None else None

    if engine == "postgres":
        conn = _resolve_connection_string(sessions, "SESSION_STORE_URL")

        def _make_pg_cm():
            from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
            return AsyncPostgresSaver.from_conn_string(conn)

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
    memory = getattr(agent, "memory", None)
    if memory is None:
        return None

    engine = getattr(memory, "engine", None)

    if engine == "postgres":
        conn = _resolve_connection_string(memory, "MEMORY_STORE_URL")

        def _make_cm():
            from langgraph.store.postgres.aio import AsyncPostgresStore
            return AsyncPostgresStore.from_conn_string(conn)

        return _LazyStore(_make_cm)

    # in-memory fallback for any other / unset engine
    from langgraph.store.memory import InMemoryStore
    return InMemoryStore()


class CheckpointObserver:
    """Records committed checkpoint ids per thread.

    The Responses stream drains this to emit `vystak.checkpoint` markers. A
    marker is only ever emitted after the underlying `aput` returned, which is
    what makes the recorded stream position a truthful durability high-water
    mark.
    """

    def __init__(self) -> None:
        self._pending: dict[str, list[str]] = {}

    def record(self, thread_id: str, checkpoint_id: str) -> None:
        if not thread_id or not checkpoint_id:
            return
        self._pending.setdefault(thread_id, []).append(checkpoint_id)

    def drain(self, thread_id: str) -> list[str]:
        return self._pending.pop(thread_id, []) if thread_id in self._pending else []

    def release(self, thread_id: str) -> None:
        self._pending.pop(thread_id, None)


class ObservedSaver(BaseCheckpointSaver):
    """Transparent proxy around a checkpointer that reports committed puts.

    Subclasses `BaseCheckpointSaver` (rather than being a plain object, as
    an earlier draft of this class was) because LangGraph's
    `ensure_valid_checkpointer` rejects anything that isn't a
    `BaseCheckpointSaver` instance at `graph.compile()` time -- a plain
    proxy breaks every real deployment. Every method delegates to `inner`;
    `aput` additionally records the committed checkpoint id with `observer`
    only after the delegate call returns, which is what makes the recorded
    stream position a truthful durability high-water mark. `__getattr__`
    covers inner-specific attributes (e.g. a sqlite `conn`) that aren't part
    of the base class's public surface.
    """

    def __init__(self, inner: Any, observer: CheckpointObserver) -> None:
        # Deliberately skip BaseCheckpointSaver.__init__: it assigns
        # self.serde, which we delegate to `inner` via a property instead.
        self._inner = inner
        self._observer = observer

    @property
    def serde(self) -> Any:
        return self._inner.serde

    @property
    def config_specs(self) -> list:
        return self._inner.config_specs

    def get(self, config):  # noqa: ANN001, ANN201
        return self._inner.get(config)

    def get_tuple(self, config):  # noqa: ANN001, ANN201
        return self._inner.get_tuple(config)

    def list(self, config, *, filter=None, before=None, limit=None):  # noqa: A002, ANN001, ANN201
        return self._inner.list(config, filter=filter, before=before, limit=limit)

    def put(self, config, checkpoint, metadata, new_versions):  # noqa: ANN001, ANN201
        return self._inner.put(config, checkpoint, metadata, new_versions)

    def put_writes(self, config, writes, task_id, task_path=""):  # noqa: ANN001, ANN201
        return self._inner.put_writes(config, writes, task_id, task_path)

    def delete_thread(self, thread_id):  # noqa: ANN001, ANN201
        return self._inner.delete_thread(thread_id)

    def delete_for_runs(self, run_ids):  # noqa: ANN001, ANN201
        return self._inner.delete_for_runs(run_ids)

    def copy_thread(self, source_thread_id, target_thread_id):  # noqa: ANN001, ANN201
        return self._inner.copy_thread(source_thread_id, target_thread_id)

    def prune(self, thread_ids, *, strategy="keep_latest"):  # noqa: ANN001, ANN201
        return self._inner.prune(thread_ids, strategy=strategy)

    async def aget(self, config):  # noqa: ANN001, ANN201
        return await self._inner.aget(config)

    async def aget_tuple(self, config):  # noqa: ANN001, ANN201
        return await self._inner.aget_tuple(config)

    async def alist(self, config, *, filter=None, before=None, limit=None):  # noqa: A002, ANN001, ANN201
        async for item in self._inner.alist(config, filter=filter, before=before, limit=limit):
            yield item

    async def aput(self, config, checkpoint, metadata, new_versions):  # noqa: ANN001
        result = await self._inner.aput(config, checkpoint, metadata, new_versions)
        thread_id = (config or {}).get("configurable", {}).get("thread_id", "")
        self._observer.record(str(thread_id), str(checkpoint.get("id", "")))
        return result

    async def aput_writes(self, config, writes, task_id, task_path=""):  # noqa: ANN001, ANN201
        return await self._inner.aput_writes(config, writes, task_id, task_path)

    async def adelete_thread(self, thread_id):  # noqa: ANN001, ANN201
        return await self._inner.adelete_thread(thread_id)

    async def adelete_for_runs(self, run_ids):  # noqa: ANN001, ANN201
        return await self._inner.adelete_for_runs(run_ids)

    async def acopy_thread(self, source_thread_id, target_thread_id):  # noqa: ANN001, ANN201
        return await self._inner.acopy_thread(source_thread_id, target_thread_id)

    async def aprune(self, thread_ids, *, strategy="keep_latest"):  # noqa: ANN001, ANN201
        return await self._inner.aprune(thread_ids, strategy=strategy)

    def get_next_version(self, current, channel):  # noqa: ANN001, ANN201
        return self._inner.get_next_version(current, channel)

    def with_allowlist(self, extra_allowlist):  # noqa: ANN001, ANN201
        return ObservedSaver(self._inner.with_allowlist(extra_allowlist), self._observer)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)
