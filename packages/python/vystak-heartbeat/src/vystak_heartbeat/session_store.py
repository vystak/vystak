"""HeartbeatSessionStore — abstract per-thread model selection store."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod

import aiosqlite


class HeartbeatSessionStore(ABC):
    @abstractmethod
    async def get_model(self, session_id: str) -> str | None: ...

    @abstractmethod
    async def set_model(self, session_id: str, model_name: str) -> None: ...

    async def close(self) -> None:
        return None


class InMemoryStore(HeartbeatSessionStore):
    """Minimal in-memory impl used until Task 9 fully populates this module."""

    def __init__(self) -> None:
        self._d: dict[str, str] = {}

    async def get_model(self, session_id: str) -> str | None:
        return self._d.get(session_id)

    async def set_model(self, session_id: str, model_name: str) -> None:
        self._d[session_id] = model_name


_DDL = """
CREATE TABLE IF NOT EXISTS heartbeat_session_models (
    session_id TEXT PRIMARY KEY,
    model_name TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


class SqliteStore(HeartbeatSessionStore):
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
            await conn.execute(_DDL)
            await conn.commit()
            self._conn = conn
            return conn

    async def get_model(self, session_id: str) -> str | None:
        conn = await self._ensure()
        cur = await conn.execute(
            "SELECT model_name FROM heartbeat_session_models WHERE session_id=?",
            (session_id,),
        )
        row = await cur.fetchone()
        return row[0] if row else None

    async def set_model(self, session_id: str, model_name: str) -> None:
        conn = await self._ensure()
        await conn.execute(
            """
            INSERT INTO heartbeat_session_models (session_id, model_name)
            VALUES (?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                model_name = excluded.model_name,
                updated_at = CURRENT_TIMESTAMP
            """,
            (session_id, model_name),
        )
        await conn.commit()

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None
