"""SqlitePanelStore — panel system-of-record (users, projects, conversations)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

import aiosqlite

from vystak_channel_panel.models import PanelUser

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL DEFAULT '',
    image TEXT NOT NULL DEFAULT '',
    role TEXT NOT NULL CHECK (role IN ('admin', 'member')),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'deactivated')),
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    is_default INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS project_members (
    project_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    PRIMARY KEY (project_id, user_id)
);
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    creator_id TEXT NOT NULL,
    agent_name TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    last_response_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    response_id TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_conversation
    ON messages (conversation_id, created_at);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _new_id() -> str:
    return uuid.uuid4().hex


class SqlitePanelStore:
    """All panel state in one SQLite file (named /data volume in-container)."""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)
        self._db: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self._db = await aiosqlite.connect(self._db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.executescript(_SCHEMA)
        await self._db.commit()

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    @property
    def db(self) -> aiosqlite.Connection:
        assert self._db is not None, "store not connected"
        return self._db

    # --- users ------------------------------------------------------------

    async def count_users(self) -> int:
        async with self.db.execute("SELECT COUNT(*) AS n FROM users") as cur:
            row = await cur.fetchone()
        return int(row["n"])

    async def create_user(
        self, email: str, *, name: str = "", image: str = "", role: str = "member"
    ) -> PanelUser:
        user = PanelUser(
            id=_new_id(),
            email=email.strip().lower(),
            name=name,
            image=image,
            role=role,
            created_at=_now(),
        )
        await self.db.execute(
            "INSERT INTO users (id, email, name, image, role, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user.id, user.email, user.name, user.image, user.role, user.status,
             user.created_at),
        )
        await self.db.commit()
        return user

    async def get_user_by_email(self, email: str) -> PanelUser | None:
        async with self.db.execute(
            "SELECT * FROM users WHERE email = ?", (email.strip().lower(),)
        ) as cur:
            row = await cur.fetchone()
        return PanelUser(**dict(row)) if row else None

    async def get_user(self, user_id: str) -> PanelUser | None:
        async with self.db.execute(
            "SELECT * FROM users WHERE id = ?", (user_id,)
        ) as cur:
            row = await cur.fetchone()
        return PanelUser(**dict(row)) if row else None

    async def list_users(self) -> list[PanelUser]:
        async with self.db.execute(
            "SELECT * FROM users ORDER BY created_at"
        ) as cur:
            rows = await cur.fetchall()
        return [PanelUser(**dict(r)) for r in rows]

    async def update_user(
        self, user_id: str, *, role: str | None = None, status: str | None = None
    ) -> PanelUser | None:
        await self.db.execute(
            "UPDATE users SET role = COALESCE(?, role), status = COALESCE(?, status) "
            "WHERE id = ?",
            (role, status, user_id),
        )
        await self.db.commit()
        return await self.get_user(user_id)

    # --- settings ---------------------------------------------------------

    async def get_setting(self, key: str) -> str | None:
        async with self.db.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ) as cur:
            row = await cur.fetchone()
        return row["value"] if row else None

    async def set_setting(self, key: str, value: str) -> None:
        await self.db.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        await self.db.commit()
