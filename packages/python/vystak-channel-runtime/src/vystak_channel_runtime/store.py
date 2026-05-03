"""Channel store: persist thread bindings + route prefs across channel types."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

import aiosqlite

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
"""


class SqliteChannelStore:
    """ChannelStore backed by aiosqlite (single-file SQLite)."""

    def __init__(self, path: str) -> None:
        self._path = path
        self._lock = None  # type: ignore[assignment]

    async def _ensure(self) -> aiosqlite.Connection:
        # Lazy connection; aiosqlite is per-connection threadsafe.
        conn = await aiosqlite.connect(self._path)
        for stmt in _SCHEMA_SQL.split(";"):
            stmt = stmt.strip()
            if stmt:
                await conn.execute(stmt)
        await conn.commit()
        return conn

    async def get_thread_binding(
        self, channel_type: str, scope_id: str, thread_id: str
    ) -> str | None:
        conn = await self._ensure()
        try:
            cur = await conn.execute(
                "SELECT agent_name FROM thread_bindings "
                "WHERE channel_type=? AND scope_id=? AND thread_id=?",
                (channel_type, scope_id, thread_id),
            )
            row = await cur.fetchone()
            return row[0] if row else None
        finally:
            await conn.close()

    async def set_thread_binding(
        self,
        channel_type: str,
        scope_id: str,
        thread_id: str,
        agent_name: str,
        user_id: str | None = None,
    ) -> None:
        conn = await self._ensure()
        try:
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
        finally:
            await conn.close()

    async def delete_thread_binding(
        self, channel_type: str, scope_id: str, thread_id: str
    ) -> None:
        conn = await self._ensure()
        try:
            await conn.execute(
                "DELETE FROM thread_bindings "
                "WHERE channel_type=? AND scope_id=? AND thread_id=?",
                (channel_type, scope_id, thread_id),
            )
            await conn.commit()
        finally:
            await conn.close()

    async def get_route_pref(
        self, channel_type: str, scope_id: str
    ) -> str | None:
        conn = await self._ensure()
        try:
            cur = await conn.execute(
                "SELECT agent_name FROM route_prefs "
                "WHERE channel_type=? AND scope_id=?",
                (channel_type, scope_id),
            )
            row = await cur.fetchone()
            return row[0] if row else None
        finally:
            await conn.close()

    async def set_route_pref(
        self, channel_type: str, scope_id: str, agent_name: str
    ) -> None:
        conn = await self._ensure()
        try:
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
        finally:
            await conn.close()

    async def delete_route_pref(
        self, channel_type: str, scope_id: str
    ) -> None:
        conn = await self._ensure()
        try:
            await conn.execute(
                "DELETE FROM route_prefs WHERE channel_type=? AND scope_id=?",
                (channel_type, scope_id),
            )
            await conn.commit()
        finally:
            await conn.close()

    async def list_thread_bindings(
        self, channel_type: str, scope_id: str | None = None
    ) -> list[ThreadBinding]:
        conn = await self._ensure()
        try:
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
                )
                for r in rows
            ]
        finally:
            await conn.close()

    async def close(self) -> None:
        # No persistent connection to close.
        pass
