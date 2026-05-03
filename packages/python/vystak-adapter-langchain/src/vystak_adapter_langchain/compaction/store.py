"""Compaction state store — postgres / sqlite / in-memory backends.

Single source of truth across all three layers (autonomous middleware,
threshold pre-call, manual /compact). Each row is a generation; the prompt
callable always reads the highest generation per thread_id.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import aiosqlite


@dataclass(frozen=True)
class CompactionRow:
    thread_id: str
    generation: int
    summary_text: str
    up_to_message_id: str
    trigger: str  # 'autonomous' | 'threshold' | 'manual'
    summarizer_model: str
    input_tokens: int = 0
    output_tokens: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))  # noqa: UP017


class CompactionStore(ABC):
    """Backend-agnostic compaction store."""

    @abstractmethod
    async def write(
        self,
        *,
        thread_id: str,
        summary_text: str,
        up_to_message_id: str,
        trigger: str,
        summarizer_model: str,
        usage: dict,
    ) -> int:
        """Write a new generation; return the generation number."""

    @abstractmethod
    async def latest(self, thread_id: str) -> CompactionRow | None:
        """Return the highest-generation row for the thread, or None."""

    @abstractmethod
    async def list(self, thread_id: str) -> list[CompactionRow]:
        """Return all rows for the thread, generation-descending."""

    @abstractmethod
    async def get(self, thread_id: str, *, generation: int) -> CompactionRow | None:
        """Return the row for `(thread_id, generation)` or None."""


class InMemoryCompactionStore(CompactionStore):
    """Process-local store for MemorySaver-backed deployments."""

    def __init__(self) -> None:
        self._rows: dict[str, list[CompactionRow]] = {}

    async def write(
        self,
        *,
        thread_id: str,
        summary_text: str,
        up_to_message_id: str,
        trigger: str,
        summarizer_model: str,
        usage: dict,
    ) -> int:
        rows = self._rows.setdefault(thread_id, [])
        gen = len(rows) + 1
        rows.append(
            CompactionRow(
                thread_id=thread_id,
                generation=gen,
                summary_text=summary_text,
                up_to_message_id=up_to_message_id,
                trigger=trigger,
                summarizer_model=summarizer_model,
                input_tokens=int(usage.get("input_tokens", 0)),
                output_tokens=int(usage.get("output_tokens", 0)),
            )
        )
        return gen

    async def latest(self, thread_id: str) -> CompactionRow | None:
        rows = self._rows.get(thread_id) or []
        return rows[-1] if rows else None

    async def list(self, thread_id: str) -> list[CompactionRow]:
        rows = self._rows.get(thread_id) or []
        return list(reversed(rows))

    async def get(self, thread_id: str, *, generation: int) -> CompactionRow | None:
        rows = self._rows.get(thread_id) or []
        for row in rows:
            if row.generation == generation:
                return row
        return None


_SQLITE_DDL = """\
CREATE TABLE IF NOT EXISTS vystak_compactions (
    thread_id TEXT NOT NULL,
    generation INTEGER NOT NULL,
    summary_text TEXT NOT NULL,
    up_to_message_id TEXT NOT NULL,
    trigger TEXT NOT NULL,
    summarizer_model TEXT NOT NULL,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (thread_id, generation)
);
"""

_SQLITE_INDEX = """\
CREATE INDEX IF NOT EXISTS vystak_compactions_thread_idx
    ON vystak_compactions (thread_id, generation DESC);
"""


class SqliteCompactionStore(CompactionStore):
    """SQLite-backed store for sqlite-engine sessions."""

    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def setup(self) -> None:
        await self._db.execute(_SQLITE_DDL)
        await self._db.execute(_SQLITE_INDEX)
        await self._db.commit()

    async def write(self, **kwargs) -> int:
        thread_id = kwargs["thread_id"]
        cursor = await self._db.execute(
            "SELECT COALESCE(MAX(generation), 0) FROM vystak_compactions WHERE thread_id = ?",
            (thread_id,),
        )
        (current_max,) = await cursor.fetchone()
        gen = (current_max or 0) + 1
        usage = kwargs["usage"]
        await self._db.execute(
            """
            INSERT INTO vystak_compactions
              (thread_id, generation, summary_text, up_to_message_id,
               trigger, summarizer_model, input_tokens, output_tokens)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                thread_id,
                gen,
                kwargs["summary_text"],
                kwargs["up_to_message_id"],
                kwargs["trigger"],
                kwargs["summarizer_model"],
                int(usage.get("input_tokens", 0)),
                int(usage.get("output_tokens", 0)),
            ),
        )
        await self._db.commit()
        return gen

    async def latest(self, thread_id: str) -> CompactionRow | None:
        cursor = await self._db.execute(
            """
            SELECT thread_id, generation, summary_text, up_to_message_id,
                   trigger, summarizer_model, input_tokens, output_tokens, created_at
              FROM vystak_compactions
             WHERE thread_id = ?
             ORDER BY generation DESC LIMIT 1
            """,
            (thread_id,),
        )
        row = await cursor.fetchone()
        return _row_to_compaction(row) if row else None

    async def list(self, thread_id: str) -> list[CompactionRow]:
        cursor = await self._db.execute(
            """
            SELECT thread_id, generation, summary_text, up_to_message_id,
                   trigger, summarizer_model, input_tokens, output_tokens, created_at
              FROM vystak_compactions
             WHERE thread_id = ?
             ORDER BY generation DESC
            """,
            (thread_id,),
        )
        rows = await cursor.fetchall()
        return [_row_to_compaction(r) for r in rows]

    async def get(self, thread_id: str, *, generation: int) -> CompactionRow | None:
        cursor = await self._db.execute(
            """
            SELECT thread_id, generation, summary_text, up_to_message_id,
                   trigger, summarizer_model, input_tokens, output_tokens, created_at
              FROM vystak_compactions
             WHERE thread_id = ? AND generation = ?
            """,
            (thread_id, generation),
        )
        row = await cursor.fetchone()
        return _row_to_compaction(row) if row else None


def _row_to_compaction(row) -> CompactionRow:
    created_at = row[8]
    if isinstance(created_at, str):
        try:
            created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        except ValueError:
            created_at = datetime.now(UTC)
    return CompactionRow(
        thread_id=row[0],
        generation=row[1],
        summary_text=row[2],
        up_to_message_id=row[3],
        trigger=row[4],
        summarizer_model=row[5],
        input_tokens=row[6],
        output_tokens=row[7],
        created_at=created_at,
    )


_POSTGRES_DDL = """\
CREATE TABLE IF NOT EXISTS vystak_compactions (
    thread_id TEXT NOT NULL,
    generation INTEGER NOT NULL,
    summary_text TEXT NOT NULL,
    up_to_message_id TEXT NOT NULL,
    trigger TEXT NOT NULL,
    summarizer_model TEXT NOT NULL,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (thread_id, generation)
);
"""

_POSTGRES_INDEX = """\
CREATE INDEX IF NOT EXISTS vystak_compactions_thread_idx
    ON vystak_compactions (thread_id, generation DESC);
"""


class PostgresCompactionStore(CompactionStore):
    """Postgres-backed store for postgres-engine sessions."""

    def __init__(self, conn) -> None:
        self._conn = conn

    async def setup(self) -> None:
        async with self._conn.cursor() as cur:
            await cur.execute(_POSTGRES_DDL)
            await cur.execute(_POSTGRES_INDEX)

    async def write(self, **kwargs) -> int:
        usage = kwargs["usage"]
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO vystak_compactions
                  (thread_id, generation, summary_text, up_to_message_id,
                   trigger, summarizer_model, input_tokens, output_tokens)
                VALUES (
                  %s,
                  COALESCE(
                    (SELECT MAX(generation) FROM vystak_compactions
                     WHERE thread_id = %s), 0
                  ) + 1,
                  %s, %s, %s, %s, %s, %s
                )
                RETURNING generation
                """,
                (
                    kwargs["thread_id"],
                    kwargs["thread_id"],
                    kwargs["summary_text"],
                    kwargs["up_to_message_id"],
                    kwargs["trigger"],
                    kwargs["summarizer_model"],
                    int(usage.get("input_tokens", 0)),
                    int(usage.get("output_tokens", 0)),
                ),
            )
            (gen,) = await cur.fetchone()
            return gen

    async def latest(self, thread_id: str) -> CompactionRow | None:
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                SELECT thread_id, generation, summary_text, up_to_message_id,
                       trigger, summarizer_model, input_tokens, output_tokens, created_at
                  FROM vystak_compactions
                 WHERE thread_id = %s
                 ORDER BY generation DESC LIMIT 1
                """,
                (thread_id,),
            )
            row = await cur.fetchone()
            return _row_to_compaction(row) if row else None

    async def list(self, thread_id: str) -> list[CompactionRow]:
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                SELECT thread_id, generation, summary_text, up_to_message_id,
                       trigger, summarizer_model, input_tokens, output_tokens, created_at
                  FROM vystak_compactions
                 WHERE thread_id = %s
                 ORDER BY generation DESC
                """,
                (thread_id,),
            )
            rows = await cur.fetchall()
            return [_row_to_compaction(r) for r in rows]

    async def get(self, thread_id: str, *, generation: int) -> CompactionRow | None:
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                SELECT thread_id, generation, summary_text, up_to_message_id,
                       trigger, summarizer_model, input_tokens, output_tokens, created_at
                  FROM vystak_compactions
                 WHERE thread_id = %s AND generation = %s
                """,
                (thread_id, generation),
            )
            row = await cur.fetchone()
            return _row_to_compaction(row) if row else None
