"""Channel store: persist thread bindings + route prefs across channel types."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

import aiosqlite
import asyncpg

from vystak_channel_runtime.types import ThreadBinding


@runtime_checkable
class ChannelStore(Protocol):
    """Generic store for runtime channel state.

    All keys are namespaced by (channel_type, scope_id, thread_id).
    Scope id meaning is per-channel:
      slack:   team_id
      discord: f"{guild_id}/{channel_id}" (or "dm/{user_id}")
      chat:    session originator
    """

    async def get_thread_binding(
        self, channel_type: str, scope_id: str, thread_id: str
    ) -> str | None: ...

    async def set_thread_binding(
        self,
        channel_type: str,
        scope_id: str,
        thread_id: str,
        agent_name: str,
        user_id: str | None = None,
    ) -> None: ...

    async def delete_thread_binding(
        self, channel_type: str, scope_id: str, thread_id: str
    ) -> None: ...

    async def get_route_pref(
        self, channel_type: str, scope_id: str
    ) -> str | None: ...

    async def set_route_pref(
        self, channel_type: str, scope_id: str, agent_name: str
    ) -> None: ...

    async def delete_route_pref(
        self, channel_type: str, scope_id: str
    ) -> None: ...

    async def list_thread_bindings(
        self, channel_type: str, scope_id: str | None = None
    ) -> list[ThreadBinding]: ...

    async def last_binding_for_agent(
        self, channel_type: str, agent_name: str
    ) -> ThreadBinding | None: ...

    async def close(self) -> None: ...


class MemoryChannelStore:
    """In-memory ChannelStore. Loses state on restart. Test default."""

    def __init__(self) -> None:
        self._threads: dict[tuple[str, str, str], dict[str, Any]] = {}
        self._prefs: dict[tuple[str, str], str] = {}

    async def get_thread_binding(
        self, channel_type: str, scope_id: str, thread_id: str
    ) -> str | None:
        row = self._threads.get((channel_type, scope_id, thread_id))
        return row["agent_name"] if row else None

    async def set_thread_binding(
        self,
        channel_type: str,
        scope_id: str,
        thread_id: str,
        agent_name: str,
        user_id: str | None = None,
    ) -> None:
        now = datetime.now(UTC)
        existing = self._threads.get((channel_type, scope_id, thread_id))
        created = existing["created_at"] if existing else now
        self._threads[(channel_type, scope_id, thread_id)] = {
            "agent_name": agent_name,
            "user_id": user_id,
            "created_at": created,
            "updated_at": now,
        }

    async def delete_thread_binding(
        self, channel_type: str, scope_id: str, thread_id: str
    ) -> None:
        self._threads.pop((channel_type, scope_id, thread_id), None)

    async def get_route_pref(
        self, channel_type: str, scope_id: str
    ) -> str | None:
        return self._prefs.get((channel_type, scope_id))

    async def set_route_pref(
        self, channel_type: str, scope_id: str, agent_name: str
    ) -> None:
        self._prefs[(channel_type, scope_id)] = agent_name

    async def delete_route_pref(
        self, channel_type: str, scope_id: str
    ) -> None:
        self._prefs.pop((channel_type, scope_id), None)

    async def list_thread_bindings(
        self, channel_type: str, scope_id: str | None = None
    ) -> list[ThreadBinding]:
        out: list[ThreadBinding] = []
        for (ct, sid, tid), row in self._threads.items():
            if ct != channel_type:
                continue
            if scope_id is not None and sid != scope_id:
                continue
            out.append(
                ThreadBinding(
                    channel_type=ct,
                    scope_id=sid,
                    thread_id=tid,
                    agent_name=row["agent_name"],
                    user_id=row.get("user_id"),
                    created_at=row.get("created_at"),
                    updated_at=row.get("updated_at"),
                )
            )
        return out

    async def last_binding_for_agent(
        self, channel_type: str, agent_name: str
    ) -> ThreadBinding | None:
        candidates = [
            (key, row)
            for key, row in self._threads.items()
            if key[0] == channel_type and row["agent_name"] == agent_name
        ]
        if not candidates:
            return None
        candidates.sort(key=lambda item: item[1]["updated_at"], reverse=True)
        (ct, scope_id, thread_id), row = candidates[0]
        return ThreadBinding(
            channel_type=ct,
            scope_id=scope_id,
            thread_id=thread_id,
            agent_name=row["agent_name"],
            user_id=row.get("user_id"),
            created_at=row.get("created_at"),
            updated_at=row.get("updated_at"),
        )

    async def close(self) -> None:
        self._threads.clear()
        self._prefs.clear()


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS thread_bindings (
    channel_type TEXT NOT NULL,
    scope_id     TEXT NOT NULL,
    thread_id    TEXT NOT NULL,
    agent_name   TEXT NOT NULL,
    user_id      TEXT,
    created_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (channel_type, scope_id, thread_id)
);

CREATE TABLE IF NOT EXISTS route_prefs (
    channel_type TEXT NOT NULL,
    scope_id     TEXT NOT NULL,
    agent_name   TEXT NOT NULL,
    created_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (channel_type, scope_id)
);

CREATE INDEX IF NOT EXISTS idx_thread_bindings_scope
    ON thread_bindings (channel_type, scope_id);

CREATE INDEX IF NOT EXISTS idx_thread_bindings_agent
    ON thread_bindings (channel_type, agent_name, updated_at DESC);
"""


class SqliteChannelStore:
    """ChannelStore backed by aiosqlite (single-file SQLite).

    Holds one persistent connection per instance — `_ensure` is idempotent
    and runs DDL only on the first call. `close()` shuts it down.
    """

    def __init__(self, path: str) -> None:
        self._path = path
        self._conn: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()

    async def _ensure(self) -> aiosqlite.Connection:
        if self._conn is not None:
            return self._conn
        async with self._lock:
            if self._conn is not None:
                return self._conn
            conn = await aiosqlite.connect(self._path)
            for stmt in _SCHEMA_SQL.split(";"):
                stmt = stmt.strip()
                if stmt:
                    await conn.execute(stmt)
            await conn.commit()
            self._conn = conn
            return conn

    async def get_thread_binding(
        self, channel_type: str, scope_id: str, thread_id: str
    ) -> str | None:
        conn = await self._ensure()
        cur = await conn.execute(
            "SELECT agent_name FROM thread_bindings "
            "WHERE channel_type=? AND scope_id=? AND thread_id=?",
            (channel_type, scope_id, thread_id),
        )
        row = await cur.fetchone()
        return row[0] if row else None

    async def set_thread_binding(
        self,
        channel_type: str,
        scope_id: str,
        thread_id: str,
        agent_name: str,
        user_id: str | None = None,
    ) -> None:
        conn = await self._ensure()
        await conn.execute(
            """
            INSERT INTO thread_bindings
                (channel_type, scope_id, thread_id, agent_name, user_id)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(channel_type, scope_id, thread_id) DO UPDATE SET
                agent_name=excluded.agent_name,
                user_id=excluded.user_id,
                updated_at=CURRENT_TIMESTAMP
            """,
            (channel_type, scope_id, thread_id, agent_name, user_id),
        )
        await conn.commit()

    async def delete_thread_binding(
        self, channel_type: str, scope_id: str, thread_id: str
    ) -> None:
        conn = await self._ensure()
        await conn.execute(
            "DELETE FROM thread_bindings "
            "WHERE channel_type=? AND scope_id=? AND thread_id=?",
            (channel_type, scope_id, thread_id),
        )
        await conn.commit()

    async def get_route_pref(
        self, channel_type: str, scope_id: str
    ) -> str | None:
        conn = await self._ensure()
        cur = await conn.execute(
            "SELECT agent_name FROM route_prefs "
            "WHERE channel_type=? AND scope_id=?",
            (channel_type, scope_id),
        )
        row = await cur.fetchone()
        return row[0] if row else None

    async def set_route_pref(
        self, channel_type: str, scope_id: str, agent_name: str
    ) -> None:
        conn = await self._ensure()
        await conn.execute(
            """
            INSERT INTO route_prefs (channel_type, scope_id, agent_name)
            VALUES (?, ?, ?)
            ON CONFLICT(channel_type, scope_id) DO UPDATE SET
                agent_name=excluded.agent_name,
                updated_at=CURRENT_TIMESTAMP
            """,
            (channel_type, scope_id, agent_name),
        )
        await conn.commit()

    async def delete_route_pref(
        self, channel_type: str, scope_id: str
    ) -> None:
        conn = await self._ensure()
        await conn.execute(
            "DELETE FROM route_prefs WHERE channel_type=? AND scope_id=?",
            (channel_type, scope_id),
        )
        await conn.commit()

    async def list_thread_bindings(
        self, channel_type: str, scope_id: str | None = None
    ) -> list[ThreadBinding]:
        conn = await self._ensure()
        if scope_id is None:
            cur = await conn.execute(
                "SELECT channel_type, scope_id, thread_id, agent_name, user_id, "
                "created_at, updated_at FROM thread_bindings WHERE channel_type=?",
                (channel_type,),
            )
        else:
            cur = await conn.execute(
                "SELECT channel_type, scope_id, thread_id, agent_name, user_id, "
                "created_at, updated_at FROM thread_bindings "
                "WHERE channel_type=? AND scope_id=?",
                (channel_type, scope_id),
            )
        rows = await cur.fetchall()
        return [
            ThreadBinding(
                channel_type=r[0],
                scope_id=r[1],
                thread_id=r[2],
                agent_name=r[3],
                user_id=r[4],
                created_at=r[5],
                updated_at=r[6],
            )
            for r in rows
        ]

    async def last_binding_for_agent(
        self, channel_type: str, agent_name: str
    ) -> ThreadBinding | None:
        conn = await self._ensure()
        cur = await conn.execute(
            "SELECT channel_type, scope_id, thread_id, agent_name, user_id, "
            "created_at, updated_at FROM thread_bindings "
            "WHERE channel_type=? AND agent_name=? "
            "ORDER BY updated_at DESC, rowid DESC LIMIT 1",
            (channel_type, agent_name),
        )
        row = await cur.fetchone()
        if row is None:
            return None
        return ThreadBinding(
            channel_type=row[0],
            scope_id=row[1],
            thread_id=row[2],
            agent_name=row[3],
            user_id=row[4],
            created_at=row[5],
            updated_at=row[6],
        )

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None


_PG_SCHEMA_SQL = [
    """
    CREATE TABLE IF NOT EXISTS thread_bindings (
        channel_type TEXT NOT NULL,
        scope_id     TEXT NOT NULL,
        thread_id    TEXT NOT NULL,
        agent_name   TEXT NOT NULL,
        user_id      TEXT,
        created_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (channel_type, scope_id, thread_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS route_prefs (
        channel_type TEXT NOT NULL,
        scope_id     TEXT NOT NULL,
        agent_name   TEXT NOT NULL,
        created_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (channel_type, scope_id)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_thread_bindings_scope
        ON thread_bindings (channel_type, scope_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_thread_bindings_agent
        ON thread_bindings (channel_type, agent_name, updated_at DESC)
    """,
]


class PostgresChannelStore:
    """ChannelStore backed by asyncpg."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._pool: asyncpg.Pool | None = None

    async def _ensure(self) -> asyncpg.Pool:
        if self._pool is None:
            self._pool = await asyncpg.create_pool(self._dsn, min_size=1, max_size=4)
            async with self._pool.acquire() as conn:
                for stmt in _PG_SCHEMA_SQL:
                    await conn.execute(stmt)
        return self._pool

    async def get_thread_binding(
        self, channel_type: str, scope_id: str, thread_id: str
    ) -> str | None:
        pool = await self._ensure()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT agent_name FROM thread_bindings "
                "WHERE channel_type=$1 AND scope_id=$2 AND thread_id=$3",
                channel_type, scope_id, thread_id,
            )
            return row["agent_name"] if row else None

    async def set_thread_binding(
        self,
        channel_type: str,
        scope_id: str,
        thread_id: str,
        agent_name: str,
        user_id: str | None = None,
    ) -> None:
        pool = await self._ensure()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO thread_bindings
                    (channel_type, scope_id, thread_id, agent_name, user_id)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (channel_type, scope_id, thread_id) DO UPDATE SET
                    agent_name=EXCLUDED.agent_name,
                    user_id=EXCLUDED.user_id,
                    updated_at=CURRENT_TIMESTAMP
                """,
                channel_type, scope_id, thread_id, agent_name, user_id,
            )

    async def delete_thread_binding(
        self, channel_type: str, scope_id: str, thread_id: str
    ) -> None:
        pool = await self._ensure()
        async with pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM thread_bindings "
                "WHERE channel_type=$1 AND scope_id=$2 AND thread_id=$3",
                channel_type, scope_id, thread_id,
            )

    async def get_route_pref(
        self, channel_type: str, scope_id: str
    ) -> str | None:
        pool = await self._ensure()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT agent_name FROM route_prefs "
                "WHERE channel_type=$1 AND scope_id=$2",
                channel_type, scope_id,
            )
            return row["agent_name"] if row else None

    async def set_route_pref(
        self, channel_type: str, scope_id: str, agent_name: str
    ) -> None:
        pool = await self._ensure()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO route_prefs (channel_type, scope_id, agent_name)
                VALUES ($1, $2, $3)
                ON CONFLICT (channel_type, scope_id) DO UPDATE SET
                    agent_name=EXCLUDED.agent_name,
                    updated_at=CURRENT_TIMESTAMP
                """,
                channel_type, scope_id, agent_name,
            )

    async def delete_route_pref(
        self, channel_type: str, scope_id: str
    ) -> None:
        pool = await self._ensure()
        async with pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM route_prefs WHERE channel_type=$1 AND scope_id=$2",
                channel_type, scope_id,
            )

    async def list_thread_bindings(
        self, channel_type: str, scope_id: str | None = None
    ) -> list[ThreadBinding]:
        pool = await self._ensure()
        async with pool.acquire() as conn:
            if scope_id is None:
                rows = await conn.fetch(
                    "SELECT channel_type, scope_id, thread_id, agent_name, user_id, "
                    "created_at, updated_at FROM thread_bindings "
                    "WHERE channel_type=$1",
                    channel_type,
                )
            else:
                rows = await conn.fetch(
                    "SELECT channel_type, scope_id, thread_id, agent_name, user_id, "
                    "created_at, updated_at FROM thread_bindings "
                    "WHERE channel_type=$1 AND scope_id=$2",
                    channel_type, scope_id,
                )
            return [
                ThreadBinding(
                    channel_type=r["channel_type"],
                    scope_id=r["scope_id"],
                    thread_id=r["thread_id"],
                    agent_name=r["agent_name"],
                    user_id=r["user_id"],
                    created_at=r["created_at"],
                    updated_at=r["updated_at"],
                )
                for r in rows
            ]

    async def last_binding_for_agent(
        self, channel_type: str, agent_name: str
    ) -> ThreadBinding | None:
        pool = await self._ensure()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT channel_type, scope_id, thread_id, agent_name, user_id, "
                "created_at, updated_at FROM thread_bindings "
                "WHERE channel_type=$1 AND agent_name=$2 "
                "ORDER BY updated_at DESC LIMIT 1",
                channel_type, agent_name,
            )
            if row is None:
                return None
            return ThreadBinding(
                channel_type=row["channel_type"],
                scope_id=row["scope_id"],
                thread_id=row["thread_id"],
                agent_name=row["agent_name"],
                user_id=row["user_id"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None


def make_channel_store(state_config: dict | None) -> ChannelStore:
    """Build a ChannelStore from a Service-shaped config dict.

    Accepts None (-> MemoryChannelStore) or one of:
      {"type": "sqlite",   "path": "/path/to.db"}
      {"type": "postgres", "dsn":  "postgresql://..."}
      {"type": "memory"}
    """
    if state_config is None:
        return MemoryChannelStore()
    kind = state_config.get("type")
    if kind in (None, "memory"):
        return MemoryChannelStore()
    if kind == "sqlite":
        return SqliteChannelStore(state_config["path"])
    if kind == "postgres":
        return PostgresChannelStore(state_config["dsn"])
    raise ValueError(f"unknown channel store type: {kind!r}")
