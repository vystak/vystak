"""Persistent store for runtime channel bindings + user preferences."""

from __future__ import annotations

import sqlite3
import time
from abc import ABC, abstractmethod


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
