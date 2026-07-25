"""SqlitePanelStore — panel system-of-record (users, projects, conversations)."""

from __future__ import annotations

import sqlite3
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

import aiosqlite

from vystak_channel_panel.models import Conversation, PanelMessage, PanelUser, Project

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
CREATE UNIQUE INDEX IF NOT EXISTS idx_projects_one_default
    ON projects (owner_id) WHERE is_default = 1;
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

    @asynccontextmanager
    async def _write(self) -> AsyncIterator[aiosqlite.Connection]:
        """Commit a multi-statement write, rolling back if any statement fails.

        aiosqlite uses deferred transactions: without the rollback, a write
        that raises midway leaves earlier statements pending, and the next
        unrelated commit() adopts them.
        """
        try:
            yield self.db
            await self.db.commit()
        except Exception:
            await self.db.rollback()
            raise

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
        async with self._write() as db:
            await db.execute(
                "DELETE FROM messages WHERE conversation_id IN "
                "(SELECT id FROM conversations WHERE project_id = ?)",
                (project_id,),
            )
            await db.execute(
                "DELETE FROM conversations WHERE project_id = ?", (project_id,)
            )
            await db.execute(
                "DELETE FROM project_members WHERE project_id = ?", (project_id,)
            )
            await db.execute("DELETE FROM projects WHERE id = ?", (project_id,))

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

    async def _get_default_project(self, user_id: str) -> Project | None:
        async with self.db.execute(
            "SELECT * FROM projects WHERE owner_id = ? AND is_default = 1",
            (user_id,),
        ) as cur:
            row = await cur.fetchone()
        return self._project_from_row(row) if row else None

    async def ensure_default_project(self, user_id: str) -> Project:
        existing = await self._get_default_project(user_id)
        if existing is not None:
            return existing
        try:
            return await self.create_project("Personal", user_id, is_default=True)
        except sqlite3.IntegrityError:
            # Concurrent caller won; its row is the one default project.
            winner = await self._get_default_project(user_id)
            if winner is None:
                raise
            return winner

    # --- conversations ----------------------------------------------------

    async def create_conversation(
        self, project_id: str, creator_id: str, agent_name: str, *, title: str = ""
    ) -> Conversation:
        now = _now()
        conv = Conversation(
            id=_new_id(),
            project_id=project_id,
            creator_id=creator_id,
            agent_name=agent_name,
            title=title,
            created_at=now,
            updated_at=now,
        )
        await self.db.execute(
            "INSERT INTO conversations "
            "(id, project_id, creator_id, agent_name, title, last_response_id, "
            " created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (conv.id, conv.project_id, conv.creator_id, conv.agent_name,
             conv.title, conv.last_response_id, conv.created_at, conv.updated_at),
        )
        await self.db.commit()
        return conv

    async def get_conversation(self, conversation_id: str) -> Conversation | None:
        async with self.db.execute(
            "SELECT * FROM conversations WHERE id = ?", (conversation_id,)
        ) as cur:
            row = await cur.fetchone()
        return Conversation(**dict(row)) if row else None

    async def list_conversations(self, project_id: str) -> list[Conversation]:
        async with self.db.execute(
            "SELECT * FROM conversations WHERE project_id = ? "
            "ORDER BY updated_at DESC",
            (project_id,),
        ) as cur:
            rows = await cur.fetchall()
        return [Conversation(**dict(r)) for r in rows]

    async def update_conversation(
        self,
        conversation_id: str,
        *,
        title: str | None = None,
        last_response_id: str | None = None,
    ) -> Conversation | None:
        # Single statement: a multi-statement partial update that raises
        # midway leaves an uncommitted write the next unrelated commit()
        # would silently adopt (see the update_user fix in Task 3).
        # COALESCE preserves the partial-update contract — a None argument
        # leaves that column unchanged.
        await self.db.execute(
            "UPDATE conversations SET title = COALESCE(?, title), "
            "last_response_id = COALESCE(?, last_response_id), updated_at = ? "
            "WHERE id = ?",
            (title, last_response_id, _now(), conversation_id),
        )
        await self.db.commit()
        return await self.get_conversation(conversation_id)

    async def delete_conversation(self, conversation_id: str) -> None:
        # Multi-statement write — use the store's _write() helper so a
        # mid-sequence failure rolls back instead of leaving pending
        # statements for the next unrelated commit() to adopt (Task 4).
        async with self._write() as db:
            await db.execute(
                "DELETE FROM messages WHERE conversation_id = ?", (conversation_id,)
            )
            await db.execute(
                "DELETE FROM conversations WHERE id = ?", (conversation_id,)
            )

    # --- messages ---------------------------------------------------------

    async def add_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        *,
        response_id: str | None = None,
    ) -> PanelMessage:
        msg = PanelMessage(
            id=_new_id(),
            conversation_id=conversation_id,
            role=role,
            content=content,
            response_id=response_id,
            created_at=_now(),
        )
        # Insert + bump in one transaction via _write() (Task 4): a message
        # must never persist without its conversation's updated_at bump.
        async with self._write() as db:
            await db.execute(
                "INSERT INTO messages "
                "(id, conversation_id, role, content, response_id, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (msg.id, msg.conversation_id, msg.role, msg.content,
                 msg.response_id, msg.created_at),
            )
            await db.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?",
                (msg.created_at, conversation_id),
            )
        return msg

    async def list_messages(self, conversation_id: str) -> list[PanelMessage]:
        async with self.db.execute(
            "SELECT * FROM messages WHERE conversation_id = ? ORDER BY created_at",
            (conversation_id,),
        ) as cur:
            rows = await cur.fetchall()
        return [PanelMessage(**dict(r)) for r in rows]
