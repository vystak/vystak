"""Durable journal of in-flight detached turns.

Tracks a turn from its initial dispatch through checkpoint boundaries to
terminal status, independent of the langgraph checkpointer, so a resumed
process can find where a turn last made durable progress and replay from
there. Always SQLite-backed at `/data/turns.db` in deployment; the
in-memory implementation is for tests and non-durable local runs.
"""

from __future__ import annotations

import asyncio
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import aiosqlite


@dataclass
class TurnRecord:
    turn_id: str
    stream_subject: str
    thread_id: str | None
    request: Any
    status: str
    last_seq: int
    boundary_seq: int
    attempts: int


class TurnJournal(ABC):
    @abstractmethod
    async def create(self, turn_id: str, stream_subject: str, request: Any) -> None: ...

    @abstractmethod
    async def set_thread_id(self, turn_id: str, thread_id: str) -> None: ...

    @abstractmethod
    async def record_boundary(self, turn_id: str, checkpoint_id: str, seq: int) -> None: ...

    @abstractmethod
    async def set_last_seq(self, turn_id: str, seq: int) -> None: ...

    @abstractmethod
    async def set_status(self, turn_id: str, status: str) -> None: ...

    @abstractmethod
    async def bump_attempts(self, turn_id: str) -> int: ...

    @abstractmethod
    async def get(self, turn_id: str) -> TurnRecord | None: ...

    @abstractmethod
    async def list_running(self) -> list[TurnRecord]: ...

    @abstractmethod
    async def seq_for_checkpoint(self, turn_id: str, checkpoint_id: str) -> int | None: ...

    async def close(self) -> None:
        return None


class InMemoryTurnJournal(TurnJournal):
    def __init__(self) -> None:
        self._records: dict[str, TurnRecord] = {}
        self._boundaries: dict[tuple[str, str], int] = {}

    async def create(self, turn_id: str, stream_subject: str, request: Any) -> None:
        self._records[turn_id] = TurnRecord(
            turn_id=turn_id,
            stream_subject=stream_subject,
            thread_id=None,
            request=request,
            status="running",
            last_seq=-1,
            boundary_seq=-1,
            attempts=0,
        )

    async def set_thread_id(self, turn_id: str, thread_id: str) -> None:
        self._records[turn_id].thread_id = thread_id

    async def record_boundary(self, turn_id: str, checkpoint_id: str, seq: int) -> None:
        self._boundaries[(turn_id, checkpoint_id)] = seq
        self._records[turn_id].boundary_seq = seq

    async def set_last_seq(self, turn_id: str, seq: int) -> None:
        self._records[turn_id].last_seq = seq

    async def set_status(self, turn_id: str, status: str) -> None:
        self._records[turn_id].status = status

    async def bump_attempts(self, turn_id: str) -> int:
        rec = self._records[turn_id]
        rec.attempts += 1
        return rec.attempts

    async def get(self, turn_id: str) -> TurnRecord | None:
        return self._records.get(turn_id)

    async def list_running(self) -> list[TurnRecord]:
        return [r for r in self._records.values() if r.status == "running"]

    async def seq_for_checkpoint(self, turn_id: str, checkpoint_id: str) -> int | None:
        return self._boundaries.get((turn_id, checkpoint_id))


_DDL = """
CREATE TABLE IF NOT EXISTS detached_turns (
    turn_id        TEXT PRIMARY KEY,
    stream_subject TEXT NOT NULL,
    thread_id      TEXT,
    request_json   TEXT NOT NULL,
    status         TEXT NOT NULL,
    last_seq       INTEGER NOT NULL DEFAULT -1,
    boundary_seq   INTEGER NOT NULL DEFAULT -1,
    attempts       INTEGER NOT NULL DEFAULT 0,
    updated_at     TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS turn_boundaries (
    turn_id       TEXT NOT NULL,
    checkpoint_id TEXT NOT NULL,
    seq           INTEGER NOT NULL,
    PRIMARY KEY (turn_id, checkpoint_id)
);
"""


class SqliteTurnJournal(TurnJournal):
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
            await conn.executescript(_DDL)
            await conn.commit()
            self._conn = conn
            return conn

    async def create(self, turn_id: str, stream_subject: str, request: Any) -> None:
        conn = await self._ensure()
        await conn.execute(
            """
            INSERT INTO detached_turns
                (turn_id, stream_subject, thread_id, request_json,
                 status, last_seq, boundary_seq, attempts)
            VALUES (?, ?, NULL, ?, 'running', -1, -1, 0)
            """,
            (turn_id, stream_subject, json.dumps(request)),
        )
        await conn.commit()

    async def set_thread_id(self, turn_id: str, thread_id: str) -> None:
        conn = await self._ensure()
        await conn.execute(
            "UPDATE detached_turns SET thread_id=?, updated_at=CURRENT_TIMESTAMP WHERE turn_id=?",
            (thread_id, turn_id),
        )
        await conn.commit()

    async def record_boundary(self, turn_id: str, checkpoint_id: str, seq: int) -> None:
        conn = await self._ensure()
        await conn.execute(
            """
            INSERT INTO turn_boundaries (turn_id, checkpoint_id, seq)
            VALUES (?, ?, ?)
            ON CONFLICT(turn_id, checkpoint_id) DO UPDATE SET
                seq = excluded.seq
            """,
            (turn_id, checkpoint_id, seq),
        )
        await conn.execute(
            "UPDATE detached_turns SET boundary_seq=?,"
            " updated_at=CURRENT_TIMESTAMP WHERE turn_id=?",
            (seq, turn_id),
        )
        await conn.commit()

    async def set_last_seq(self, turn_id: str, seq: int) -> None:
        conn = await self._ensure()
        await conn.execute(
            "UPDATE detached_turns SET last_seq=?, updated_at=CURRENT_TIMESTAMP WHERE turn_id=?",
            (seq, turn_id),
        )
        await conn.commit()

    async def set_status(self, turn_id: str, status: str) -> None:
        conn = await self._ensure()
        await conn.execute(
            "UPDATE detached_turns SET status=?, updated_at=CURRENT_TIMESTAMP WHERE turn_id=?",
            (status, turn_id),
        )
        await conn.commit()

    async def bump_attempts(self, turn_id: str) -> int:
        conn = await self._ensure()
        await conn.execute(
            "UPDATE detached_turns SET attempts=attempts+1,"
            " updated_at=CURRENT_TIMESTAMP WHERE turn_id=?",
            (turn_id,),
        )
        await conn.commit()
        cur = await conn.execute(
            "SELECT attempts FROM detached_turns WHERE turn_id=?", (turn_id,)
        )
        row = await cur.fetchone()
        return row[0]

    async def get(self, turn_id: str) -> TurnRecord | None:
        conn = await self._ensure()
        cur = await conn.execute(
            """
            SELECT turn_id, stream_subject, thread_id, request_json, status,
                   last_seq, boundary_seq, attempts
            FROM detached_turns WHERE turn_id=?
            """,
            (turn_id,),
        )
        row = await cur.fetchone()
        if row is None:
            return None
        return self._row_to_record(row)

    async def list_running(self) -> list[TurnRecord]:
        conn = await self._ensure()
        cur = await conn.execute(
            """
            SELECT turn_id, stream_subject, thread_id, request_json, status,
                   last_seq, boundary_seq, attempts
            FROM detached_turns WHERE status='running'
            """
        )
        rows = await cur.fetchall()
        return [self._row_to_record(row) for row in rows]

    async def seq_for_checkpoint(self, turn_id: str, checkpoint_id: str) -> int | None:
        conn = await self._ensure()
        cur = await conn.execute(
            "SELECT seq FROM turn_boundaries WHERE turn_id=? AND checkpoint_id=?",
            (turn_id, checkpoint_id),
        )
        row = await cur.fetchone()
        return row[0] if row else None

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    @staticmethod
    def _row_to_record(row: Any) -> TurnRecord:
        (
            turn_id,
            stream_subject,
            thread_id,
            request_json,
            status,
            last_seq,
            boundary_seq,
            attempts,
        ) = row
        return TurnRecord(
            turn_id=turn_id,
            stream_subject=stream_subject,
            thread_id=thread_id,
            request=json.loads(request_json),
            status=status,
            last_seq=last_seq,
            boundary_seq=boundary_seq,
            attempts=attempts,
        )
