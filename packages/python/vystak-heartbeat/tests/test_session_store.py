"""Heartbeat session store tests (in-memory + sqlite)."""

from pathlib import Path

import pytest
from vystak_heartbeat.session_store import (
    InMemoryStore,
    SqliteStore,
)


@pytest.mark.asyncio
async def test_in_memory_get_set_round_trip():
    s = InMemoryStore()
    assert await s.get_model("t1") is None
    await s.set_model("t1", "haiku")
    assert await s.get_model("t1") == "haiku"


@pytest.mark.asyncio
async def test_sqlite_persistence_across_instances(tmp_path: Path):
    db = tmp_path / "x.db"
    s1 = SqliteStore(str(db))
    await s1.set_model("t1", "haiku")
    await s1.close()
    s2 = SqliteStore(str(db))
    assert await s2.get_model("t1") == "haiku"
    await s2.close()


@pytest.mark.asyncio
async def test_sqlite_overwrite():
    s = SqliteStore(":memory:")
    await s.set_model("t1", "haiku")
    await s.set_model("t1", "sonnet")
    assert await s.get_model("t1") == "sonnet"
    await s.close()
