"""SqlitePanelStore — panel system-of-record (users, projects, conversations)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

import aiosqlite

from vystak_channel_panel.models import PanelUser, Project

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

    # --- projects ---------------------------------------------------------

    async def create_project(
        self, name: str, owner_id: str, *, is_default: bool = False
    ) -> Project:
        project = Project(
            id=_new_id(),
            name=name,
            owner_id=owner_id,
            is_default=is_default,
            created_at=_now(),
        )
        await self.db.execute(
            "INSERT INTO projects (id, name, owner_id, is_default, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (project.id, project.name, project.owner_id,
             int(project.is_default), project.created_at),
        )
        await self.db.commit()
        return project

    async def get_project(self, project_id: str) -> Project | None:
        async with self.db.execute(
            "SELECT * FROM projects WHERE id = ?", (project_id,)
        ) as cur:
            row = await cur.fetchone()
        return self._project_from_row(row) if row else None

    @staticmethod
    def _project_from_row(row) -> Project:
        d = dict(row)
        d["is_default"] = bool(d["is_default"])
        return Project(**d)

    async def list_projects_for_user(self, user_id: str) -> list[Project]:
        async with self.db.execute(
            "SELECT DISTINCT p.* FROM projects p "
            "LEFT JOIN project_members m ON m.project_id = p.id "
            "WHERE p.owner_id = ? OR m.user_id = ? "
            "ORDER BY p.created_at",
            (user_id, user_id),
        ) as cur:
            rows = await cur.fetchall()
        return [self._project_from_row(r) for r in rows]

    async def delete_project(self, project_id: str) -> None:
        await self.db.execute(
            "DELETE FROM messages WHERE conversation_id IN "
            "(SELECT id FROM conversations WHERE project_id = ?)",
            (project_id,),
        )
        await self.db.execute(
            "DELETE FROM conversations WHERE project_id = ?", (project_id,)
        )
        await self.db.execute(
            "DELETE FROM project_members WHERE project_id = ?", (project_id,)
        )
        await self.db.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        await self.db.commit()

    async def add_member(self, project_id: str, user_id: str) -> None:
        await self.db.execute(
            "INSERT OR IGNORE INTO project_members (project_id, user_id) "
            "VALUES (?, ?)",
            (project_id, user_id),
        )
        await self.db.commit()

    async def remove_member(self, project_id: str, user_id: str) -> None:
        await self.db.execute(
            "DELETE FROM project_members WHERE project_id = ? AND user_id = ?",
            (project_id, user_id),
        )
        await self.db.commit()

    async def list_members(self, project_id: str) -> list[PanelUser]:
        async with self.db.execute(
            "SELECT u.* FROM users u "
            "JOIN project_members m ON m.user_id = u.id "
            "WHERE m.project_id = ? ORDER BY u.created_at",
            (project_id,),
        ) as cur:
            rows = await cur.fetchall()
        return [PanelUser(**dict(r)) for r in rows]

    async def user_can_access_project(self, project_id: str, user_id: str) -> bool:
        async with self.db.execute(
            "SELECT 1 FROM projects p "
            "LEFT JOIN project_members m "
            "  ON m.project_id = p.id AND m.user_id = ? "
            "WHERE p.id = ? AND (p.owner_id = ? OR m.user_id IS NOT NULL)",
            (user_id, project_id, user_id),
        ) as cur:
            return await cur.fetchone() is not None

    async def ensure_default_project(self, user_id: str) -> Project:
        async with self.db.execute(
            "SELECT * FROM projects WHERE owner_id = ? AND is_default = 1",
            (user_id,),
        ) as cur:
            row = await cur.fetchone()
        if row:
            return self._project_from_row(row)
        return await self.create_project("Personal", user_id, is_default=True)
