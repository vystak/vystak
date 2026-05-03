"""Slack-only inviter tracking — one row per (team, channel)."""

from __future__ import annotations

import aiosqlite

_DDL = """
CREATE TABLE IF NOT EXISTS slack_inviters (
    team_id    TEXT NOT NULL,
    channel_id TEXT NOT NULL,
    user_id    TEXT NOT NULL,
    PRIMARY KEY (team_id, channel_id)
);
"""


class InviterStore:
    """Stores who first invited the bot into a channel."""

    def __init__(self, path: str) -> None:
        self._path = path

    async def _ensure(self) -> aiosqlite.Connection:
        conn = await aiosqlite.connect(self._path)
        await conn.execute(_DDL)
        await conn.commit()
        return conn

    async def get_inviter(self, team_id: str, channel_id: str) -> str | None:
        conn = await self._ensure()
        try:
            cur = await conn.execute(
                "SELECT user_id FROM slack_inviters WHERE team_id=? AND channel_id=?",
                (team_id, channel_id),
            )
            row = await cur.fetchone()
            return row[0] if row else None
        finally:
            await conn.close()

    async def record_inviter(self, team_id: str, channel_id: str, user_id: str) -> None:
        conn = await self._ensure()
        try:
            await conn.execute(
                """
                INSERT INTO slack_inviters (team_id, channel_id, user_id)
                VALUES (?, ?, ?)
                ON CONFLICT(team_id, channel_id) DO UPDATE SET user_id=excluded.user_id
                """,
                (team_id, channel_id, user_id),
            )
            await conn.commit()
        finally:
            await conn.close()
