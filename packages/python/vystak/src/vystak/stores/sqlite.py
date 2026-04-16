"""Async SQLite-backed key-value store for long-term memory."""

import json
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone

import aiosqlite


@dataclass
class Item:
    """A single item in the store."""

    namespace: tuple[str, ...]
    key: str
    value: dict
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class AsyncSqliteStore:
    """Async SQLite-backed store compatible with LangGraph's store interface."""

    def __init__(self, db: aiosqlite.Connection):
        self._db = db

    @classmethod
    @asynccontextmanager
    async def from_conn_string(cls, path: str):
        """Async context manager that opens a SQLite database."""
        db = await aiosqlite.connect(path)
        store = cls(db)
        await store.setup()
        try:
            yield store
        finally:
            await db.close()

    async def setup(self) -> None:
        """Create the store table if it doesn't exist."""
        await self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS store (
                namespace TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (namespace, key)
            )
            """
        )
        await self._db.commit()

    async def aput(self, namespace: tuple[str, ...], key: str, value: dict) -> None:
        """Upsert an item."""
        ns_str = "|".join(namespace)
        now = datetime.now(timezone.utc).isoformat()
        await self._db.execute(
            """
            INSERT INTO store (namespace, key, value, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(namespace, key) DO UPDATE SET value = ?, created_at = ?
            """,
            (ns_str, key, json.dumps(value), now, json.dumps(value), now),
        )
        await self._db.commit()

    async def aget(self, namespace: tuple[str, ...], key: str) -> Item | None:
        """Get a single item."""
        ns_str = "|".join(namespace)
        cursor = await self._db.execute(
            "SELECT namespace, key, value, created_at FROM store WHERE namespace = ? AND key = ?",
            (ns_str, key),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return Item(
            namespace=tuple(row[0].split("|")),
            key=row[1],
            value=json.loads(row[2]),
            created_at=datetime.fromisoformat(row[3]),
        )

    async def asearch(
        self,
        namespace: tuple[str, ...],
        *,
        query: str | None = None,
        limit: int = 10,
    ) -> list[Item]:
        """List items in a namespace. Query parameter is ignored (no embeddings)."""
        ns_str = "|".join(namespace)
        cursor = await self._db.execute(
            "SELECT namespace, key, value, created_at FROM store WHERE namespace = ? ORDER BY created_at DESC LIMIT ?",
            (ns_str, limit),
        )
        rows = await cursor.fetchall()
        return [
            Item(
                namespace=tuple(row[0].split("|")),
                key=row[1],
                value=json.loads(row[2]),
                created_at=datetime.fromisoformat(row[3]),
            )
            for row in rows
        ]

    async def adelete(self, namespace: tuple[str, ...], key: str) -> None:
        """Remove an item."""
        ns_str = "|".join(namespace)
        await self._db.execute(
            "DELETE FROM store WHERE namespace = ? AND key = ?",
            (ns_str, key),
        )
        await self._db.commit()
