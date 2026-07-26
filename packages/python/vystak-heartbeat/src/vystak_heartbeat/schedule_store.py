"""SqliteScheduleStore — persistent scheduled-task storage with reconciliation.

Whole `ScheduledTask` payloads are stored as JSON so the schema doesn't need
a migration every time the model grows a field. `UNIQUE (agent_canonical,
name)` spans both `source` values ('declarative' and 'runtime'), but the two
directions of a same-name collision are handled differently to preserve the
invariant that `source=runtime` tasks are never touched by apply/reconcile:
`create_runtime` raises `NameCollisionError` when a name is already taken by
a declarative task, while `reconcile_declarative` silently skips (and warns
about) a declarative entry whose name is already owned by a runtime task,
leaving that runtime row completely untouched.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime

import aiosqlite
from vystak.schema.schedule import ScheduledTask

logger = logging.getLogger("vystak.heartbeat.schedule_store")

# Bump when _SCHEMA changes in a way existing databases need migrating for.
# _migrate() compares this against the `schema_version` row in `settings`
# (absent == 1) and applies the matching upgrade steps — mirrors
# vystak_channel_panel.store's pattern.
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
    next_fire_at TEXT,
    last_fire_at TEXT,
    last_result TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (agent_canonical, name)
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""

# Fields whose change means a previously-computed next_fire_at is stale and
# must be recomputed by the scheduler.
_SHAPE_FIELDS = ("cron", "at", "every", "timezone")


class NameCollisionError(Exception):
    """Raised when a runtime task name collides with an existing task.

    The `UNIQUE (agent_canonical, name)` constraint spans both `source`
    values, so this fires when `create_runtime` targets a name already held
    by a declarative task (or another runtime task) for the same agent. The
    reverse direction — a declarative task colliding with an existing
    runtime one — does NOT raise: `reconcile_declarative` skips that entry
    and logs a warning instead, so a runtime row is never overwritten or
    resurrected by apply/reconcile.
    """


@dataclass
class StoredTask:
    id: str
    agent_canonical: str
    source: str  # "declarative" | "runtime"
    status: str  # "active" | "completed" | "missed" | "cancelled"
    task: ScheduledTask
    created_by: str  # "definition" | "cli" | "agent:<canonical>"
    next_fire_at: datetime | None  # aware UTC
    last_fire_at: datetime | None
    last_result: str | None


def _new_id() -> str:
    return uuid.uuid4().hex


def _to_iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat()


def _from_iso(s: str | None) -> datetime | None:
    if s is None:
        return None
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _row_to_stored(row: aiosqlite.Row) -> StoredTask:
    return StoredTask(
        id=row["id"],
        agent_canonical=row["agent_canonical"],
        source=row["source"],
        status=row["status"],
        task=ScheduledTask.model_validate_json(row["payload"]),
        created_by=row["created_by"],
        next_fire_at=_from_iso(row["next_fire_at"]),
        last_fire_at=_from_iso(row["last_fire_at"]),
        last_result=row["last_result"],
    )


class SqliteScheduleStore:
    """All scheduled-task state in one SQLite file."""

    def __init__(self, path: str) -> None:
        self._path = path
        self._db: aiosqlite.Connection | None = None
        self._write_lock = asyncio.Lock()

    async def connect(self) -> None:
        self._db = await aiosqlite.connect(self._path)
        self._db.row_factory = aiosqlite.Row
        await self._db.executescript(_SCHEMA)
        await self._db.commit()
        await self._migrate()

    async def _migrate(self) -> None:
        """Bring an existing database up to SCHEMA_VERSION in place.

        `executescript(_SCHEMA)` in connect() is `CREATE TABLE IF NOT
        EXISTS` only — it never alters a table that already exists. This
        runs once per connect(), after schema creation, and is a no-op once
        the database is already current. Kept as a scaffold (mirrors
        vystak_channel_panel.store._migrate) so a future schema bump has
        somewhere to slot in ALTER TABLE steps guarded by `PRAGMA
        table_info` checks.
        """
        raw = await self.get_setting("schema_version")
        version = int(raw) if raw is not None else 1
        if version >= SCHEMA_VERSION:
            if raw is None:
                await self.set_setting("schema_version", str(SCHEMA_VERSION))
            return
        async with self._write() as db:
            # Future ALTER TABLE steps go here, each guarded by a
            # PRAGMA table_info(...) check for re-entry safety.
            await db.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                ("schema_version", str(SCHEMA_VERSION)),
            )

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    @property
    def db(self) -> aiosqlite.Connection:
        assert self._db is not None, "store not connected"
        return self._db

    @asynccontextmanager
    async def _write(self) -> AsyncIterator[aiosqlite.Connection]:
        """Run a write under an exclusive lock, committing on success and
        rolling back on any failure — including cancellation.

        Same rationale as vystak_channel_panel.store.SqlitePanelStore._write:
        aiosqlite queues every call onto one worker thread against one
        shared connection with deferred transactions, so without a lock a
        multi-statement block (e.g. reconcile_declarative's delete+upserts)
        could be interleaved and partially committed by another coroutine.
        """
        async with self._write_lock:
            try:
                yield self.db
                await self.db.commit()
            except BaseException:
                await self.db.rollback()
                raise

    # --- settings -----------------------------------------------------

    async def get_setting(self, key: str) -> str | None:
        async with self.db.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ) as cur:
            row = await cur.fetchone()
        return row["value"] if row else None

    async def set_setting(self, key: str, value: str) -> None:
        async with self._write() as db:
            await db.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    # --- runtime CRUD ---------------------------------------------------

    async def create_runtime(
        self, agent_canonical: str, task: ScheduledTask, created_by: str
    ) -> StoredTask:
        task_id = _new_id()
        payload = task.model_dump_json()
        try:
            async with self._write() as db:
                await db.execute(
                    "INSERT INTO scheduled_tasks "
                    "(id, agent_canonical, name, source, status, payload, created_by) "
                    "VALUES (?, ?, ?, 'runtime', 'active', ?, ?)",
                    (task_id, agent_canonical, task.name, payload, created_by),
                )
        except sqlite3.IntegrityError as e:
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
            clauses.append("agent_canonical = ?")
            params.append(agent)
        if source is not None:
            clauses.append("source = ?")
            params.append(source)
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        async with self.db.execute(
            f"SELECT * FROM scheduled_tasks {where} ORDER BY created_at", params
        ) as cur:
            rows = await cur.fetchall()
        return [_row_to_stored(r) for r in rows]

    async def get(self, task_id: str) -> StoredTask | None:
        async with self.db.execute(
            "SELECT * FROM scheduled_tasks WHERE id = ?", (task_id,)
        ) as cur:
            row = await cur.fetchone()
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
        async with self._write() as db:
            if shape_changed:
                await db.execute(
                    "UPDATE scheduled_tasks SET payload = ?, next_fire_at = NULL "
                    "WHERE id = ?",
                    (payload, task_id),
                )
            else:
                await db.execute(
                    "UPDATE scheduled_tasks SET payload = ? WHERE id = ?",
                    (payload, task_id),
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
        async with self._write() as db:
            await db.execute(
                "UPDATE scheduled_tasks SET status = 'cancelled' WHERE id = ?",
                (task_id,),
            )

    # --- declarative reconciliation -------------------------------------

    async def reconcile_declarative(
        self, agent_canonical: str, tasks: list[ScheduledTask]
    ) -> None:
        names = [t.name for t in tasks]
        async with self._write() as db:
            if names:
                placeholders = ",".join("?" for _ in names)
                await db.execute(
                    "DELETE FROM scheduled_tasks WHERE agent_canonical = ? "
                    f"AND source = 'declarative' AND name NOT IN ({placeholders})",
                    (agent_canonical, *names),
                )
            else:
                await db.execute(
                    "DELETE FROM scheduled_tasks WHERE agent_canonical = ? "
                    "AND source = 'declarative'",
                    (agent_canonical,),
                )
            for task in tasks:
                payload = task.model_dump_json()
                async with db.execute(
                    "SELECT source FROM scheduled_tasks "
                    "WHERE agent_canonical = ? AND name = ?",
                    (agent_canonical, task.name),
                ) as cur:
                    existing = await cur.fetchone()
                if existing is not None and existing["source"] == "runtime":
                    logger.warning(
                        "reconcile: declarative task %r for agent %r skipped "
                        "— a runtime task already owns this name; runtime "
                        "task left untouched",
                        task.name,
                        agent_canonical,
                    )
                    continue
                # The WHERE guard on DO UPDATE is defense-in-depth: the SELECT
                # above already filters out runtime collisions, but this
                # keeps the invariant true even under concurrent writers —
                # a false condition makes the statement a no-op for that row
                # instead of overwriting it.
                await db.execute(
                    "INSERT INTO scheduled_tasks "
                    "(id, agent_canonical, name, source, status, payload, created_by) "
                    "VALUES (?, ?, ?, 'declarative', 'active', ?, 'definition') "
                    "ON CONFLICT(agent_canonical, name) DO UPDATE SET "
                    "  status = 'active', "
                    "  payload = excluded.payload, "
                    "  next_fire_at = CASE "
                    "    WHEN scheduled_tasks.payload != excluded.payload THEN NULL "
                    "    ELSE scheduled_tasks.next_fire_at "
                    "  END "
                    "WHERE scheduled_tasks.source = 'declarative'",
                    (_new_id(), agent_canonical, task.name, payload),
                )

    # --- fire bookkeeping ------------------------------------------------

    async def set_next_fire(self, task_id: str, when: datetime | None) -> None:
        async with self._write() as db:
            await db.execute(
                "UPDATE scheduled_tasks SET next_fire_at = ? WHERE id = ?",
                (_to_iso(when), task_id),
            )

    async def record_fire(
        self,
        task_id: str,
        fired_at: datetime,
        result: str,
        *,
        completed: bool = False,
    ) -> None:
        async with self._write() as db:
            if completed:
                await db.execute(
                    "UPDATE scheduled_tasks SET last_fire_at = ?, last_result = ?, "
                    "status = 'completed' WHERE id = ?",
                    (_to_iso(fired_at), result, task_id),
                )
            else:
                await db.execute(
                    "UPDATE scheduled_tasks SET last_fire_at = ?, last_result = ? "
                    "WHERE id = ?",
                    (_to_iso(fired_at), result, task_id),
                )

    async def mark_missed(self, task_id: str) -> None:
        async with self._write() as db:
            await db.execute(
                "UPDATE scheduled_tasks SET status = 'missed' WHERE id = ?",
                (task_id,),
            )

    async def due(self, now: datetime) -> list[StoredTask]:
        async with self.db.execute(
            "SELECT * FROM scheduled_tasks WHERE status = 'active' "
            "AND next_fire_at IS NOT NULL AND next_fire_at <= ? "
            "ORDER BY next_fire_at",
            (_to_iso(now),),
        ) as cur:
            rows = await cur.fetchall()
        return [s for s in (_row_to_stored(r) for r in rows) if s.task.enabled]

    async def min_next_fire(self) -> datetime | None:
        async with self.db.execute(
            "SELECT payload, next_fire_at FROM scheduled_tasks "
            "WHERE status = 'active' AND next_fire_at IS NOT NULL"
        ) as cur:
            rows = await cur.fetchall()
        times = [
            _from_iso(r["next_fire_at"])
            for r in rows
            if ScheduledTask.model_validate_json(r["payload"]).enabled
        ]
        return min(times) if times else None
