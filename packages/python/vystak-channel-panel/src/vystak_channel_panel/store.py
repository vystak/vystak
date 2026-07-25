"""SqlitePanelStore — panel system-of-record (users, projects, conversations)."""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

import aiosqlite

from vystak_channel_panel.models import Conversation, PanelMessage, PanelUser, Project

logger = logging.getLogger(__name__)

# Bump when _SCHEMA changes in a way existing databases need migrating for.
# _migrate() compares this against the `schema_version` row in `settings`
# (absent == 1) and applies the matching upgrade steps.
SCHEMA_VERSION: int = 2

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
    parts TEXT,
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
        self._setup_lock = asyncio.Lock()
        self._write_lock = asyncio.Lock()

    async def connect(self) -> None:
        self._db = await aiosqlite.connect(self._db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.executescript(_SCHEMA)
        await self._db.commit()
        await self._migrate()

    async def _migrate(self) -> None:
        """Bring an existing database up to SCHEMA_VERSION in place.

        `executescript(_SCHEMA)` in connect() is `CREATE TABLE IF NOT
        EXISTS` only — it never alters a table that already exists, so a
        pre-existing `/data` volume (e.g. the live `vystak-panel-state`
        volume) would otherwise never gain a new column. This runs once per
        connect(), after schema creation, and is a no-op once the database
        is already current.

        Guarded two ways, since a live volume with real data exists:
        the `schema_version` row in `settings` (the durable, cross-restart
        record) AND an actual `PRAGMA table_info(messages)` check before
        the ALTER TABLE — so this can't fail with "duplicate column" if the
        version row and the on-disk shape ever disagree.
        """
        raw = await self.get_setting("schema_version")
        version = int(raw) if raw is not None else 1
        if version >= SCHEMA_VERSION:
            return
        # sqlite3 opens its implicit transaction lazily, before the first
        # DML statement — DDL such as ALTER TABLE runs and commits
        # independently of it. So the ALTER TABLE below is NOT covered by
        # this method's `_write()` block: it autocommits the instant it
        # runs, regardless of whether the `schema_version` write that
        # follows succeeds. A crash between the two leaves a torn state
        # (column added, version not yet bumped) — re-entry safety comes
        # from the `PRAGMA table_info` column check below, not from block
        # atomicity. Do not remove this check as "redundant" with the
        # `_write()` wrapper; doing so reintroduces a `duplicate column
        # name` failure on the next connect() after a crash in that window.
        async with self.db.execute("PRAGMA table_info(messages)") as cur:
            columns = {row["name"] async for row in cur}
        async with self._write() as db:
            if "parts" not in columns:
                await db.execute("ALTER TABLE messages ADD COLUMN parts TEXT")
            # Inlined rather than calling set_setting(): set_setting()
            # acquires _write_lock itself, and this method already holds it
            # (we're inside the `async with self._write()` block above) —
            # asyncio.Lock is not reentrant, so calling set_setting() here
            # would deadlock at startup. Keep this inlined if you're tempted
            # to DRY it up.
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

        aiosqlite queues every call onto one worker thread against one
        shared connection, and uses deferred transactions: without a lock,
        another coroutine's `_write()` block could interleave between two
        `await db.execute()` calls here and commit() early, making this
        block's pending statements durable before it's done — so a later
        failure in *this* block can no longer be rolled back. Every mutating
        method in this store — single- or multi-statement — routes through
        `_write()`, so once the store is serving traffic, `commit()`/
        `rollback()` never happen outside this lock and no unrelated write
        can adopt another's pending statements. (The one exception is the
        initial schema-creation commit in `connect()`, which runs once
        before the store accepts any calls, so nothing can interleave with
        it.)

        Catches `BaseException`, not `Exception`: `asyncio.CancelledError`
        and `GeneratorExit` are `BaseException` subclasses, and Starlette
        cancels the response task on client disconnect — a cancelled write
        must roll back too, not leave statements pending.
        """
        async with self._write_lock:
            try:
                yield self.db
                await self.db.commit()
            except BaseException:
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
        async with self._write() as db:
            await db.execute(
                "INSERT INTO users (id, email, name, image, role, status, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (user.id, user.email, user.name, user.image, user.role, user.status,
                 user.created_at),
            )
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
        async with self._write() as db:
            await db.execute(
                "UPDATE users SET role = COALESCE(?, role), status = COALESCE(?, status) "
                "WHERE id = ?",
                (role, status, user_id),
            )
        return await self.get_user(user_id)

    async def update_user_guarded(
        self, user_id: str, *, role: str | None = None, status: str | None = None
    ) -> tuple[PanelUser | None, bool]:
        """Update a user unless doing so would remove the last active admin.

        Returns ``(user, ok)``:
          * ``(user, True)``  — applied; ``user`` is the updated row
          * ``(None, False)`` — no such user
          * ``(user, False)`` — refused; ``user`` is the unchanged row

        The guard lives in the UPDATE's WHERE clause so the check and the
        write are one atomic statement. A count-then-update sequence races:
        two concurrent demotions of different admins would each see a
        sufficient count and together drop the panel to zero admins.
        """
        async with self._write() as db:
            cur = await db.execute(
                "UPDATE users SET role = COALESCE(?, role), status = COALESCE(?, status) "
                "WHERE id = ? "
                "AND ( "
                "  (COALESCE(?, role) = 'admin' AND COALESCE(?, status) = 'active') "
                "  OR EXISTS ( "
                "       SELECT 1 FROM users o "
                "        WHERE o.id <> users.id "
                "          AND o.role = 'admin' "
                "          AND o.status = 'active' "
                "     ) "
                ")",
                (role, status, user_id, role, status),
            )
            rowcount = cur.rowcount
        # Read happens outside the _write() block: get_user() does not
        # acquire _write_lock, but keeping it out keeps this method's shape
        # consistent with the other guarded-write + read methods.
        if rowcount == 0:
            user = await self.get_user(user_id)
            return (None, False) if user is None else (user, False)
        return await self.get_user(user_id), True

    async def claim_setup_admin(
        self, email: str, *, name: str = "", image: str = ""
    ) -> PanelUser:
        """Atomically claim first-run setup: mark setup complete, create the
        admin user, and create their default project — or do none of it.

        Raises sqlite3.IntegrityError if setup was already claimed.

        The durable guard is the `settings` primary key: a second INSERT of
        the 'setup_complete' row fails, so only one caller can proceed even
        across restarts. The in-process lock serializes concurrent requests
        that share this store's single SQLite connection, where an
        interleaved rollback would otherwise affect another caller's
        pending statements.
        """
        async with self._setup_lock:
            user = PanelUser(
                id=_new_id(),
                email=email.strip().lower(),
                name=name,
                image=image,
                role="admin",
                created_at=_now(),
            )
            project = Project(
                id=_new_id(),
                name="Personal",
                owner_id=user.id,
                is_default=True,
                created_at=_now(),
            )
            async with self._write() as db:
                # First: the durable, cross-restart guard. A duplicate claim
                # fails here, before any user/project row is created.
                await db.execute(
                    "INSERT INTO settings (key, value) VALUES (?, ?)",
                    ("setup_complete", "1"),
                )
                await db.execute(
                    "INSERT INTO users "
                    "(id, email, name, image, role, status, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (user.id, user.email, user.name, user.image, user.role,
                     user.status, user.created_at),
                )
                await db.execute(
                    "INSERT INTO projects "
                    "(id, name, owner_id, is_default, created_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (project.id, project.name, project.owner_id,
                     int(project.is_default), project.created_at),
                )
            return user

    # --- settings ---------------------------------------------------------

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
        async with self._write() as db:
            await db.execute(
                "INSERT INTO projects (id, name, owner_id, is_default, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (project.id, project.name, project.owner_id,
                 int(project.is_default), project.created_at),
            )
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
        async with self._write() as db:
            await db.execute(
                "INSERT OR IGNORE INTO project_members (project_id, user_id) "
                "VALUES (?, ?)",
                (project_id, user_id),
            )

    async def remove_member(self, project_id: str, user_id: str) -> None:
        async with self._write() as db:
            await db.execute(
                "DELETE FROM project_members WHERE project_id = ? AND user_id = ?",
                (project_id, user_id),
            )

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
        async with self._write() as db:
            await db.execute(
                "INSERT INTO conversations "
                "(id, project_id, creator_id, agent_name, title, last_response_id, "
                " created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (conv.id, conv.project_id, conv.creator_id, conv.agent_name,
                 conv.title, conv.last_response_id, conv.created_at, conv.updated_at),
            )
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
        # COALESCE preserves the partial-update contract — a None argument
        # leaves that column unchanged. Routed through _write() (Task 4)
        # like every other mutating method, so this commit() can't land
        # inside another caller's pending _write() block.
        async with self._write() as db:
            await db.execute(
                "UPDATE conversations SET title = COALESCE(?, title), "
                "last_response_id = COALESCE(?, last_response_id), updated_at = ? "
                "WHERE id = ?",
                (title, last_response_id, _now(), conversation_id),
            )
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
        parts: list[dict] | None = None,
    ) -> PanelMessage:
        # `content` stays the source of truth for message text; `parts` is
        # strictly additive (e.g. tool-call detail for replay) and never
        # replaces it.
        msg = PanelMessage(
            id=_new_id(),
            conversation_id=conversation_id,
            role=role,
            content=content,
            response_id=response_id,
            created_at=_now(),
            parts=parts,
        )
        # Insert + bump in one transaction via _write() (Task 4): a message
        # must never persist without its conversation's updated_at bump.
        async with self._write() as db:
            await db.execute(
                "INSERT INTO messages "
                "(id, conversation_id, role, content, response_id, parts, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (msg.id, msg.conversation_id, msg.role, msg.content,
                 msg.response_id, json.dumps(parts) if parts is not None else None,
                 msg.created_at),
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
        return [self._message_from_row(r) for r in rows]

    @staticmethod
    def _message_from_row(row) -> PanelMessage:
        d = dict(row)
        raw_parts = d.get("parts")
        if raw_parts is None:
            d["parts"] = None
        else:
            try:
                d["parts"] = json.loads(raw_parts)
            except json.JSONDecodeError:
                # A malformed `parts` value must not take out the entire
                # conversation's message history — degrade to None (the
                # same shape as "no parts recorded") and log rather than
                # raise.
                logger.warning(
                    "message %s has malformed parts JSON; treating as None",
                    d.get("id"),
                )
                d["parts"] = None
        return PanelMessage(**d)
