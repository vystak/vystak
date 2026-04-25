"""Persistent store for runtime channel bindings + user preferences."""

from __future__ import annotations

import os
import sqlite3
import time
from abc import ABC, abstractmethod

import psycopg


class RoutesStore(ABC):
    """Abstract interface — implemented by SqliteStore and PostgresStore (Task 4)."""

    @abstractmethod
    def migrate(self) -> None: ...

    @abstractmethod
    def channel_binding(self, team: str, channel: str) -> str | None: ...

    @abstractmethod
    def set_channel_binding(
        self, team: str, channel: str, agent: str, inviter: str | None
    ) -> None: ...

    @abstractmethod
    def unbind_channel(self, team: str, channel: str) -> None: ...

    @abstractmethod
    def user_pref(self, team: str, user: str) -> str | None: ...

    @abstractmethod
    def set_user_pref(self, team: str, user: str, agent: str) -> None: ...

    @abstractmethod
    def unset_user_pref(self, team: str, user: str) -> None: ...

    @abstractmethod
    def record_inviter(self, team: str, channel: str, user: str) -> None: ...

    @abstractmethod
    def inviter(self, team: str, channel: str) -> str | None: ...

    @abstractmethod
    def thread_binding(
        self, team: str, channel: str, thread_ts: str
    ) -> str | None: ...

    @abstractmethod
    def set_thread_binding(
        self, team: str, channel: str, thread_ts: str, agent: str
    ) -> None: ...

    @abstractmethod
    def unbind_thread(
        self, team: str, channel: str, thread_ts: str
    ) -> None: ...


_SCHEMA = """
CREATE TABLE IF NOT EXISTS channel_bindings (
    team_id TEXT NOT NULL, channel_id TEXT NOT NULL,
    agent_name TEXT NOT NULL, inviter_id TEXT,
    created_at INTEGER NOT NULL,
    PRIMARY KEY (team_id, channel_id));
CREATE TABLE IF NOT EXISTS user_prefs (
    team_id TEXT NOT NULL, user_id TEXT NOT NULL,
    agent_name TEXT NOT NULL, created_at INTEGER NOT NULL,
    PRIMARY KEY (team_id, user_id));
CREATE TABLE IF NOT EXISTS inviters (
    team_id TEXT NOT NULL, channel_id TEXT NOT NULL,
    user_id TEXT NOT NULL, joined_at INTEGER NOT NULL,
    PRIMARY KEY (team_id, channel_id));
CREATE TABLE IF NOT EXISTS thread_bindings (
    team_id TEXT NOT NULL, channel_id TEXT NOT NULL,
    thread_ts TEXT NOT NULL, agent_name TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    PRIMARY KEY (team_id, channel_id, thread_ts));
"""


class SqliteStore(RoutesStore):
    """SQLite-backed RoutesStore. Single-file, single-process safe."""

    def __init__(self, path: str):
        self._path = path

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path, isolation_level=None)  # autocommit
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def migrate(self) -> None:
        conn = self._conn()
        try:
            conn.executescript(_SCHEMA)
        finally:
            conn.close()

    def channel_binding(self, team: str, channel: str) -> str | None:
        conn = self._conn()
        try:
            row = conn.execute(
                "SELECT agent_name FROM channel_bindings "
                "WHERE team_id=? AND channel_id=?",
                (team, channel),
            ).fetchone()
            return row[0] if row else None
        finally:
            conn.close()

    def set_channel_binding(
        self, team: str, channel: str, agent: str, inviter: str | None
    ) -> None:
        conn = self._conn()
        try:
            conn.execute(
                "INSERT OR REPLACE INTO channel_bindings "
                "(team_id, channel_id, agent_name, inviter_id, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (team, channel, agent, inviter, int(time.time())),
            )
        finally:
            conn.close()

    def unbind_channel(self, team: str, channel: str) -> None:
        conn = self._conn()
        try:
            conn.execute(
                "DELETE FROM channel_bindings "
                "WHERE team_id=? AND channel_id=?",
                (team, channel),
            )
        finally:
            conn.close()

    def user_pref(self, team: str, user: str) -> str | None:
        conn = self._conn()
        try:
            row = conn.execute(
                "SELECT agent_name FROM user_prefs "
                "WHERE team_id=? AND user_id=?",
                (team, user),
            ).fetchone()
            return row[0] if row else None
        finally:
            conn.close()

    def set_user_pref(self, team: str, user: str, agent: str) -> None:
        conn = self._conn()
        try:
            conn.execute(
                "INSERT OR REPLACE INTO user_prefs "
                "(team_id, user_id, agent_name, created_at) "
                "VALUES (?, ?, ?, ?)",
                (team, user, agent, int(time.time())),
            )
        finally:
            conn.close()

    def unset_user_pref(self, team: str, user: str) -> None:
        conn = self._conn()
        try:
            conn.execute(
                "DELETE FROM user_prefs "
                "WHERE team_id=? AND user_id=?",
                (team, user),
            )
        finally:
            conn.close()

    def record_inviter(self, team: str, channel: str, user: str) -> None:
        conn = self._conn()
        try:
            conn.execute(
                "INSERT OR REPLACE INTO inviters "
                "(team_id, channel_id, user_id, joined_at) "
                "VALUES (?, ?, ?, ?)",
                (team, channel, user, int(time.time())),
            )
        finally:
            conn.close()

    def inviter(self, team: str, channel: str) -> str | None:
        conn = self._conn()
        try:
            row = conn.execute(
                "SELECT user_id FROM inviters "
                "WHERE team_id=? AND channel_id=?",
                (team, channel),
            ).fetchone()
            return row[0] if row else None
        finally:
            conn.close()

    def thread_binding(
        self, team: str, channel: str, thread_ts: str
    ) -> str | None:
        conn = self._conn()
        try:
            row = conn.execute(
                "SELECT agent_name FROM thread_bindings "
                "WHERE team_id=? AND channel_id=? AND thread_ts=?",
                (team, channel, thread_ts),
            ).fetchone()
            return row[0] if row else None
        finally:
            conn.close()

    def set_thread_binding(
        self, team: str, channel: str, thread_ts: str, agent: str
    ) -> None:
        conn = self._conn()
        try:
            conn.execute(
                "INSERT OR REPLACE INTO thread_bindings "
                "(team_id, channel_id, thread_ts, agent_name, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (team, channel, thread_ts, agent, int(time.time())),
            )
        finally:
            conn.close()

    def unbind_thread(
        self, team: str, channel: str, thread_ts: str
    ) -> None:
        conn = self._conn()
        try:
            conn.execute(
                "DELETE FROM thread_bindings "
                "WHERE team_id=? AND channel_id=? AND thread_ts=?",
                (team, channel, thread_ts),
            )
        finally:
            conn.close()


_PG_SCHEMA = """
CREATE TABLE IF NOT EXISTS channel_bindings (
    team_id TEXT NOT NULL, channel_id TEXT NOT NULL,
    agent_name TEXT NOT NULL, inviter_id TEXT,
    created_at BIGINT NOT NULL,
    PRIMARY KEY (team_id, channel_id));
CREATE TABLE IF NOT EXISTS user_prefs (
    team_id TEXT NOT NULL, user_id TEXT NOT NULL,
    agent_name TEXT NOT NULL, created_at BIGINT NOT NULL,
    PRIMARY KEY (team_id, user_id));
CREATE TABLE IF NOT EXISTS inviters (
    team_id TEXT NOT NULL, channel_id TEXT NOT NULL,
    user_id TEXT NOT NULL, joined_at BIGINT NOT NULL,
    PRIMARY KEY (team_id, channel_id));
CREATE TABLE IF NOT EXISTS thread_bindings (
    team_id TEXT NOT NULL, channel_id TEXT NOT NULL,
    thread_ts TEXT NOT NULL, agent_name TEXT NOT NULL,
    created_at BIGINT NOT NULL,
    PRIMARY KEY (team_id, channel_id, thread_ts));
"""


class PostgresStore(RoutesStore):
    """Postgres-backed RoutesStore. Uses psycopg v3 (sync)."""

    def __init__(self, dsn: str):
        self._dsn = dsn

    def _conn(self):
        return psycopg.connect(self._dsn, autocommit=True)

    def migrate(self) -> None:
        with self._conn() as conn:
            conn.execute(_PG_SCHEMA)

    def channel_binding(self, team: str, channel: str) -> str | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT agent_name FROM channel_bindings "
                "WHERE team_id=%s AND channel_id=%s",
                (team, channel),
            ).fetchone()
            return row[0] if row else None

    def set_channel_binding(
        self, team: str, channel: str, agent: str, inviter: str | None
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO channel_bindings "
                "(team_id, channel_id, agent_name, inviter_id, created_at) "
                "VALUES (%s, %s, %s, %s, %s) "
                "ON CONFLICT (team_id, channel_id) DO UPDATE SET "
                "agent_name = EXCLUDED.agent_name, "
                "inviter_id = EXCLUDED.inviter_id, "
                "created_at = EXCLUDED.created_at",
                (team, channel, agent, inviter, int(time.time())),
            )

    def unbind_channel(self, team: str, channel: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "DELETE FROM channel_bindings "
                "WHERE team_id=%s AND channel_id=%s",
                (team, channel),
            )

    def user_pref(self, team: str, user: str) -> str | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT agent_name FROM user_prefs "
                "WHERE team_id=%s AND user_id=%s",
                (team, user),
            ).fetchone()
            return row[0] if row else None

    def set_user_pref(self, team: str, user: str, agent: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO user_prefs "
                "(team_id, user_id, agent_name, created_at) "
                "VALUES (%s, %s, %s, %s) "
                "ON CONFLICT (team_id, user_id) DO UPDATE SET "
                "agent_name = EXCLUDED.agent_name, "
                "created_at = EXCLUDED.created_at",
                (team, user, agent, int(time.time())),
            )

    def unset_user_pref(self, team: str, user: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "DELETE FROM user_prefs "
                "WHERE team_id=%s AND user_id=%s",
                (team, user),
            )

    def record_inviter(self, team: str, channel: str, user: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO inviters "
                "(team_id, channel_id, user_id, joined_at) "
                "VALUES (%s, %s, %s, %s) "
                "ON CONFLICT (team_id, channel_id) DO UPDATE SET "
                "user_id = EXCLUDED.user_id, "
                "joined_at = EXCLUDED.joined_at",
                (team, channel, user, int(time.time())),
            )

    def inviter(self, team: str, channel: str) -> str | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT user_id FROM inviters "
                "WHERE team_id=%s AND channel_id=%s",
                (team, channel),
            ).fetchone()
            return row[0] if row else None

    def thread_binding(
        self, team: str, channel: str, thread_ts: str
    ) -> str | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT agent_name FROM thread_bindings "
                "WHERE team_id=%s AND channel_id=%s AND thread_ts=%s",
                (team, channel, thread_ts),
            ).fetchone()
            return row[0] if row else None

    def set_thread_binding(
        self, team: str, channel: str, thread_ts: str, agent: str
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO thread_bindings "
                "(team_id, channel_id, thread_ts, agent_name, created_at) "
                "VALUES (%s, %s, %s, %s, %s) "
                "ON CONFLICT (team_id, channel_id, thread_ts) DO UPDATE SET "
                "agent_name = EXCLUDED.agent_name, "
                "created_at = EXCLUDED.created_at",
                (team, channel, thread_ts, agent, int(time.time())),
            )

    def unbind_thread(
        self, team: str, channel: str, thread_ts: str
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                "DELETE FROM thread_bindings "
                "WHERE team_id=%s AND channel_id=%s AND thread_ts=%s",
                (team, channel, thread_ts),
            )


def make_store(service) -> RoutesStore:
    """Dispatch on Service.type. Default sqlite path is /data/channel-state.db."""
    if service.type == "sqlite":
        path = getattr(service, "path", None) or "/data/channel-state.db"
        return SqliteStore(path=path)
    if service.type == "postgres":
        env_var = getattr(service, "connection_string_env", None)
        if env_var:
            return PostgresStore(dsn=os.environ[env_var])
        # provider-managed: connection injected as PG_DSN
        return PostgresStore(dsn=os.environ["PG_DSN"])
    raise ValueError(f"unsupported state type: {service.type}")
