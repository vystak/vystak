"""PgScheduleStore — asyncpg-backed mirror of SqliteScheduleStore.

Same method set and semantics as :mod:`vystak_heartbeat.schedule_store`'s
``SqliteScheduleStore`` — including the runtime-collision skip-and-warn
guard in ``reconcile_declarative`` (see that module's docstring for the
full rationale). ``StoredTask`` and ``NameCollisionError`` are imported
from there rather than redefined, so callers (and ``except`` clauses) work
identically regardless of which backend is configured.

Payload is stored as ``TEXT`` (whole-``ScheduledTask`` JSON, same as
SQLite) rather than ``JSONB``: this package never queries into the
payload, so JSONB would only add codec-registration complexity
(asyncpg decodes ``jsonb`` columns as raw ``str`` unless you register a
type codec) for no benefit — ``TEXT`` + ``model_dump_json()``/
``model_validate_json()`` mirrors the SQLite path exactly.

Timestamps use ``TIMESTAMPTZ`` and are passed/returned as native aware
``datetime`` objects (normalized to UTC on both write and read) instead of
the ISO-string round trip SQLite needs for its ``TEXT`` columns.

Concurrency: SQLite serializes writes through an explicit
``asyncio.Lock`` because aiosqlite multiplexes one connection through a
single worker thread. Postgres has real per-transaction isolation, so
each method acquires its own pooled connection; multi-statement
operations (``reconcile_declarative``) wrap in an explicit
``conn.transaction()`` for atomicity instead.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

import asyncpg
from vystak.schema.schedule import ScheduledTask

from vystak_heartbeat.schedule_store import NameCollisionError, StoredTask

logger = logging.getLogger("vystak.heartbeat.schedule_store_pg")

# Bump when _SCHEMA changes in a way existing databases need migrating for.
# Mirrors SqliteScheduleStore.SCHEMA_VERSION / _migrate.
SCHEMA_VERSION: int = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS scheduled_tasks (
    id TEXT PRIMARY KEY,
    agent_canonical TEXT NOT NULL,
    name TEXT NOT NULL,
    source TEXT NOT NULL CHECK (source IN ('declarative','runtime')),
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active','completed','missed','cancelled')),
    payload TEXT NOT NULL,
    created_by TEXT NOT NULL,
    next_fire_at TIMESTAMPTZ,
    last_fire_at TIMESTAMPTZ,
    last_result TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (agent_canonical, name)
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""

# Fields whose change means a previously-computed next_fire_at is stale and
# must be recomputed by the scheduler. Mirrors schedule_store._SHAPE_FIELDS.
_SHAPE_FIELDS = ("cron", "at", "every", "timezone")


def _new_id() -> str:
    return uuid.uuid4().hex


def _to_utc(dt: datetime | None) -> datetime | None:
    """Normalize any aware/naive datetime to aware UTC.

    Used both when writing (naive datetimes are treated as already-UTC,
    matching schedule_store._to_iso) and when reading back a TIMESTAMPTZ
    column (asyncpg returns an aware datetime already, but not necessarily
    in the UTC zone depending on session settings).
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _row_to_stored(row: asyncpg.Record) -> StoredTask:
    return StoredTask(
        id=row["id"],
        agent_canonical=row["agent_canonical"],
        source=row["source"],
        status=row["status"],
        task=ScheduledTask.model_validate_json(row["payload"]),
        created_by=row["created_by"],
        next_fire_at=_to_utc(row["next_fire_at"]),
        last_fire_at=_to_utc(row["last_fire_at"]),
        last_result=row["last_result"],
    )


class PgScheduleStore:
    """All scheduled-task state in Postgres, via asyncpg."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._pool: asyncpg.Pool | None = None

    async def connect(self) -> None:
        self._pool = await asyncpg.create_pool(self._dsn, min_size=1, max_size=4)
        async with self._pool.acquire() as conn:
            await conn.execute(_SCHEMA)
        await self._migrate()

    async def _migrate(self) -> None:
        """Bring an existing database up to SCHEMA_VERSION in place.

        Scaffold only, mirrors SqliteScheduleStore._migrate — a no-op once
        the database is already current; a future schema bump slots ALTER
        TABLE steps in here.
        """
        raw = await self.get_setting("schema_version")
        version = int(raw) if raw is not None else 1
        if version >= SCHEMA_VERSION:
            if raw is None:
                await self.set_setting("schema_version", str(SCHEMA_VERSION))
            return
        # Future ALTER TABLE steps go here.
        await self.set_setting("schema_version", str(SCHEMA_VERSION))

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    @property
    def pool(self) -> asyncpg.Pool:
        assert self._pool is not None, "store not connected"
        return self._pool

    # --- settings -----------------------------------------------------

    async def get_setting(self, key: str) -> str | None:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT value FROM settings WHERE key = $1", key)
        return row["value"] if row else None

    async def set_setting(self, key: str, value: str) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO settings (key, value) VALUES ($1, $2) "
                "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
                key, value,
            )

    # --- runtime CRUD ---------------------------------------------------

    async def create_runtime(
        self, agent_canonical: str, task: ScheduledTask, created_by: str
    ) -> StoredTask:
        task_id = _new_id()
        payload = task.model_dump_json()
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO scheduled_tasks "
                    "(id, agent_canonical, name, source, status, payload, created_by) "
                    "VALUES ($1, $2, $3, 'runtime', 'active', $4, $5)",
                    task_id, agent_canonical, task.name, payload, created_by,
                )
        except asyncpg.UniqueViolationError as e:
            raise NameCollisionError(
                f"task {task.name!r} already exists for agent {agent_canonical!r}"
            ) from e
        stored = await self.get(task_id)
        assert stored is not None
        return stored

    async def list(
        self,
        *,
        agent: str | None = None,
        source: str | None = None,
        status: str | None = None,
    ) -> list[StoredTask]:
        clauses: list[str] = []
        params: list[str] = []
        if agent is not None:
            params.append(agent)
            clauses.append(f"agent_canonical = ${len(params)}")
        if source is not None:
            params.append(source)
            clauses.append(f"source = ${len(params)}")
        if status is not None:
            params.append(status)
            clauses.append(f"status = ${len(params)}")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT * FROM scheduled_tasks {where} ORDER BY created_at", *params
            )
        return [_row_to_stored(r) for r in rows]

    async def get(self, task_id: str) -> StoredTask | None:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM scheduled_tasks WHERE id = $1", task_id
            )
        return _row_to_stored(row) if row else None

    async def _get_or_raise(self, task_id: str) -> StoredTask:
        row = await self.get(task_id)
        if row is None:
            raise KeyError(task_id)
        return row

    async def update_runtime(self, task_id: str, patch: dict) -> StoredTask:
        row = await self._get_or_raise(task_id)
        if row.source == "declarative":
            raise PermissionError(
                f"task {task_id} is declarative and cannot be modified"
            )
        # name is immutable identity: the `name` column and the payload's
        # embedded name must never desync (the UNIQUE(agent_canonical, name)
        # invariant, and the reserved 'heartbeat' contract, both depend on
        # the column being authoritative). A same-name patch is a no-op and
        # allowed; anything else is rejected here before any write happens.
        if "name" in patch and patch["name"] != row.task.name:
            raise ValueError("task name is immutable — create a new task instead")
        # model_copy() does not re-run validators, so re-validate the
        # patched shape via model_validate() before persisting it.
        candidate = row.task.model_copy(update=patch)
        updated_task = ScheduledTask.model_validate(candidate.model_dump())
        shape_changed = any(
            getattr(row.task, f) != getattr(updated_task, f) for f in _SHAPE_FIELDS
        )
        payload = updated_task.model_dump_json()
        async with self.pool.acquire() as conn:
            if shape_changed:
                await conn.execute(
                    "UPDATE scheduled_tasks SET payload = $1, next_fire_at = NULL "
                    "WHERE id = $2",
                    payload, task_id,
                )
            else:
                await conn.execute(
                    "UPDATE scheduled_tasks SET payload = $1 WHERE id = $2",
                    payload, task_id,
                )
        stored = await self.get(task_id)
        assert stored is not None
        return stored

    async def cancel_runtime(self, task_id: str) -> None:
        row = await self._get_or_raise(task_id)
        if row.source == "declarative":
            raise PermissionError(
                f"task {task_id} is declarative and cannot be cancelled"
            )
        async with self.pool.acquire() as conn:
            await conn.execute(
                "UPDATE scheduled_tasks SET status = 'cancelled' WHERE id = $1",
                task_id,
            )

    # --- declarative reconciliation -------------------------------------

    async def reconcile_declarative(
        self, agent_canonical: str, tasks: list[ScheduledTask]
    ) -> None:
        names = [t.name for t in tasks]
        async with self.pool.acquire() as conn, conn.transaction():
            if names:
                await conn.execute(
                    "DELETE FROM scheduled_tasks WHERE agent_canonical = $1 "
                    "AND source = 'declarative' AND name <> ALL($2::text[])",
                    agent_canonical, names,
                )
            else:
                await conn.execute(
                    "DELETE FROM scheduled_tasks WHERE agent_canonical = $1 "
                    "AND source = 'declarative'",
                    agent_canonical,
                )
            for task in tasks:
                payload = task.model_dump_json()
                existing = await conn.fetchrow(
                    "SELECT source FROM scheduled_tasks "
                    "WHERE agent_canonical = $1 AND name = $2",
                    agent_canonical, task.name,
                )
                if existing is not None and existing["source"] == "runtime":
                    logger.warning(
                        "reconcile: declarative task %r for agent %r skipped "
                        "— a runtime task already owns this name; runtime "
                        "task left untouched",
                        task.name,
                        agent_canonical,
                    )
                    continue
                # The WHERE guard on DO UPDATE is defense-in-depth: the
                # SELECT above already filters out runtime collisions, but
                # this keeps the invariant true even under concurrent
                # writers — a false condition makes the statement a no-op
                # for that row instead of overwriting it.
                await conn.execute(
                    "INSERT INTO scheduled_tasks "
                    "(id, agent_canonical, name, source, status, payload, created_by) "
                    "VALUES ($1, $2, $3, 'declarative', 'active', $4, 'definition') "
                    "ON CONFLICT (agent_canonical, name) DO UPDATE SET "
                    "  status = 'active', "
                    "  payload = EXCLUDED.payload, "
                    "  next_fire_at = CASE "
                    "    WHEN scheduled_tasks.payload != EXCLUDED.payload THEN NULL "
                    "    ELSE scheduled_tasks.next_fire_at "
                    "  END "
                    "WHERE scheduled_tasks.source = 'declarative'",
                    _new_id(), agent_canonical, task.name, payload,
                )

    # --- fire bookkeeping ------------------------------------------------

    async def set_next_fire(self, task_id: str, when: datetime | None) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                "UPDATE scheduled_tasks SET next_fire_at = $1 WHERE id = $2",
                _to_utc(when), task_id,
            )

    async def record_fire(
        self,
        task_id: str,
        fired_at: datetime,
        result: str,
        *,
        completed: bool = False,
    ) -> None:
        async with self.pool.acquire() as conn:
            if completed:
                await conn.execute(
                    "UPDATE scheduled_tasks SET last_fire_at = $1, last_result = $2, "
                    "status = 'completed' WHERE id = $3",
                    _to_utc(fired_at), result, task_id,
                )
            else:
                await conn.execute(
                    "UPDATE scheduled_tasks SET last_fire_at = $1, last_result = $2 "
                    "WHERE id = $3",
                    _to_utc(fired_at), result, task_id,
                )

    async def mark_missed(self, task_id: str) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                "UPDATE scheduled_tasks SET status = 'missed' WHERE id = $1",
                task_id,
            )

    async def due(self, now: datetime) -> list[StoredTask]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM scheduled_tasks WHERE status = 'active' "
                "AND next_fire_at IS NOT NULL AND next_fire_at <= $1 "
                "ORDER BY next_fire_at",
                _to_utc(now),
            )
        return [s for s in (_row_to_stored(r) for r in rows) if s.task.enabled]

    async def min_next_fire(self) -> datetime | None:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT payload, next_fire_at FROM scheduled_tasks "
                "WHERE status = 'active' AND next_fire_at IS NOT NULL"
            )
        times = [
            _to_utc(r["next_fire_at"])
            for r in rows
            if ScheduledTask.model_validate_json(r["payload"]).enabled
        ]
        return min(times) if times else None
