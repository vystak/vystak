"""Tests for ChannelStore impls."""

import asyncio
from pathlib import Path

import pytest
from vystak_channel_runtime.store import (
    ChannelStore,
    MemoryChannelStore,
    PostgresChannelStore,
    SqliteChannelStore,
    make_channel_store,
)


@pytest.mark.asyncio
async def test_memory_store_implements_protocol():
    s = MemoryChannelStore()
    assert isinstance(s, ChannelStore)


@pytest.mark.asyncio
async def test_thread_binding_round_trip():
    s = MemoryChannelStore()
    assert await s.get_thread_binding("slack", "T1", "C1:1.0") is None
    await s.set_thread_binding("slack", "T1", "C1:1.0", "hero")
    assert await s.get_thread_binding("slack", "T1", "C1:1.0") == "hero"


@pytest.mark.asyncio
async def test_thread_binding_overwrite():
    s = MemoryChannelStore()
    await s.set_thread_binding("slack", "T1", "C1:1.0", "hero")
    await s.set_thread_binding("slack", "T1", "C1:1.0", "villain")
    assert await s.get_thread_binding("slack", "T1", "C1:1.0") == "villain"


@pytest.mark.asyncio
async def test_thread_binding_delete():
    s = MemoryChannelStore()
    await s.set_thread_binding("slack", "T1", "C1:1.0", "hero")
    await s.delete_thread_binding("slack", "T1", "C1:1.0")
    assert await s.get_thread_binding("slack", "T1", "C1:1.0") is None


@pytest.mark.asyncio
async def test_route_pref_round_trip():
    s = MemoryChannelStore()
    assert await s.get_route_pref("slack", "T1") is None
    await s.set_route_pref("slack", "T1", "hero")
    assert await s.get_route_pref("slack", "T1") == "hero"
    await s.delete_route_pref("slack", "T1")
    assert await s.get_route_pref("slack", "T1") is None


@pytest.mark.asyncio
async def test_list_thread_bindings_filter():
    s = MemoryChannelStore()
    await s.set_thread_binding("slack", "T1", "t1", "hero")
    await s.set_thread_binding("slack", "T1", "t2", "villain")
    await s.set_thread_binding("slack", "T2", "t1", "hero")
    rows_t1 = await s.list_thread_bindings("slack", "T1")
    assert {r.thread_id for r in rows_t1} == {"t1", "t2"}
    all_slack = await s.list_thread_bindings("slack")
    assert len(all_slack) == 3


@pytest.mark.asyncio
async def test_isolation_by_channel_type():
    s = MemoryChannelStore()
    await s.set_thread_binding("slack", "T1", "x", "hero")
    assert await s.get_thread_binding("discord", "T1", "x") is None


@pytest.fixture
def sqlite_store(tmp_path: Path):
    return SqliteChannelStore(str(tmp_path / "channel.db"))


@pytest.mark.asyncio
async def test_sqlite_store_implements_protocol(sqlite_store):
    assert isinstance(sqlite_store, ChannelStore)


@pytest.mark.asyncio
async def test_sqlite_thread_binding_round_trip(sqlite_store):
    assert await sqlite_store.get_thread_binding("slack", "T1", "C:1") is None
    await sqlite_store.set_thread_binding("slack", "T1", "C:1", "hero")
    assert await sqlite_store.get_thread_binding("slack", "T1", "C:1") == "hero"
    await sqlite_store.close()


@pytest.mark.asyncio
async def test_sqlite_route_pref_round_trip(sqlite_store):
    await sqlite_store.set_route_pref("slack", "T1", "hero")
    assert await sqlite_store.get_route_pref("slack", "T1") == "hero"
    await sqlite_store.delete_route_pref("slack", "T1")
    assert await sqlite_store.get_route_pref("slack", "T1") is None
    await sqlite_store.close()


@pytest.mark.asyncio
async def test_sqlite_persists_across_instances(tmp_path):
    path = str(tmp_path / "channel.db")
    s1 = SqliteChannelStore(path)
    await s1.set_thread_binding("slack", "T1", "C:1", "hero")
    await s1.close()
    s2 = SqliteChannelStore(path)
    assert await s2.get_thread_binding("slack", "T1", "C:1") == "hero"
    await s2.close()


@pytest.mark.docker
@pytest.mark.asyncio
async def test_postgres_store_round_trip(postgres_dsn):
    s = PostgresChannelStore(postgres_dsn)
    await s.set_thread_binding("slack", "T1", "C:1", "hero")
    assert await s.get_thread_binding("slack", "T1", "C:1") == "hero"
    await s.delete_thread_binding("slack", "T1", "C:1")
    assert await s.get_thread_binding("slack", "T1", "C:1") is None
    await s.close()


@pytest.mark.docker
@pytest.mark.asyncio
async def test_postgres_route_pref(postgres_dsn):
    s = PostgresChannelStore(postgres_dsn)
    await s.set_route_pref("slack", "T1", "hero")
    assert await s.get_route_pref("slack", "T1") == "hero"
    await s.delete_route_pref("slack", "T1")
    await s.close()


def test_make_channel_store_none_returns_memory():
    s = make_channel_store(None)
    assert isinstance(s, MemoryChannelStore)


def test_make_channel_store_sqlite(tmp_path):
    cfg = {"type": "sqlite", "path": str(tmp_path / "x.db")}
    s = make_channel_store(cfg)
    assert isinstance(s, SqliteChannelStore)


def test_make_channel_store_postgres():
    cfg = {"type": "postgres", "dsn": "postgresql://u:p@h/db"}
    s = make_channel_store(cfg)
    assert isinstance(s, PostgresChannelStore)


def test_make_channel_store_unknown_raises():
    with pytest.raises(ValueError):
        make_channel_store({"type": "redis"})


# ---------------------------------------------------------------------------
# last_binding_for_agent — Memory backend
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_memory_last_binding_for_agent_empty():
    store = MemoryChannelStore()
    assert await store.last_binding_for_agent("slack", "ops-bot") is None


@pytest.mark.asyncio
async def test_memory_last_binding_for_agent_picks_most_recent():
    store = MemoryChannelStore()
    await store.set_thread_binding("slack", "T1", "thread-old", "ops-bot", user_id="U1")
    # tiny gap so updated_at differs
    await asyncio.sleep(0.01)
    await store.set_thread_binding("slack", "T1", "thread-new", "ops-bot", user_id="U2")
    binding = await store.last_binding_for_agent("slack", "ops-bot")
    assert binding is not None
    assert binding.thread_id == "thread-new"
    assert binding.user_id == "U2"


@pytest.mark.asyncio
async def test_memory_last_binding_for_agent_ignores_other_agents():
    store = MemoryChannelStore()
    await store.set_thread_binding("slack", "T1", "thread-1", "other-bot", user_id="U1")
    assert await store.last_binding_for_agent("slack", "ops-bot") is None


@pytest.mark.asyncio
async def test_memory_last_binding_for_agent_ignores_other_channel_types():
    store = MemoryChannelStore()
    await store.set_thread_binding("discord", "G1", "thread-1", "ops-bot", user_id="U1")
    assert await store.last_binding_for_agent("slack", "ops-bot") is None


# ---------------------------------------------------------------------------
# last_binding_for_agent — SQLite backend
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sqlite_last_binding_for_agent_empty(sqlite_store):
    assert await sqlite_store.last_binding_for_agent("slack", "ops-bot") is None
    await sqlite_store.close()


@pytest.mark.asyncio
async def test_sqlite_last_binding_for_agent_picks_most_recent(sqlite_store):
    await sqlite_store.set_thread_binding(
        "slack", "T1", "thread-old", "ops-bot", user_id="U1"
    )
    await asyncio.sleep(0.01)
    await sqlite_store.set_thread_binding(
        "slack", "T1", "thread-new", "ops-bot", user_id="U2"
    )
    binding = await sqlite_store.last_binding_for_agent("slack", "ops-bot")
    assert binding is not None
    assert binding.thread_id == "thread-new"
    assert binding.user_id == "U2"
    await sqlite_store.close()


@pytest.mark.asyncio
async def test_sqlite_last_binding_for_agent_ignores_other_agents(sqlite_store):
    await sqlite_store.set_thread_binding(
        "slack", "T1", "thread-1", "other-bot", user_id="U1"
    )
    assert await sqlite_store.last_binding_for_agent("slack", "ops-bot") is None
    await sqlite_store.close()


@pytest.mark.asyncio
async def test_sqlite_last_binding_for_agent_ignores_other_channel_types(sqlite_store):
    await sqlite_store.set_thread_binding(
        "discord", "G1", "thread-1", "ops-bot", user_id="U1"
    )
    assert await sqlite_store.last_binding_for_agent("slack", "ops-bot") is None
    await sqlite_store.close()


# ---------------------------------------------------------------------------
# last_binding_for_agent — Postgres backend
# ---------------------------------------------------------------------------


@pytest.mark.docker
@pytest.mark.asyncio
async def test_postgres_last_binding_for_agent_empty(postgres_dsn):
    s = PostgresChannelStore(postgres_dsn)
    assert await s.last_binding_for_agent("slack", "ops-bot") is None
    await s.close()


@pytest.mark.docker
@pytest.mark.asyncio
async def test_postgres_last_binding_for_agent_picks_most_recent(postgres_dsn):
    s = PostgresChannelStore(postgres_dsn)
    await s.set_thread_binding("slack", "T1", "thread-old", "ops-bot", user_id="U1")
    await asyncio.sleep(0.01)
    await s.set_thread_binding("slack", "T1", "thread-new", "ops-bot", user_id="U2")
    binding = await s.last_binding_for_agent("slack", "ops-bot")
    assert binding is not None
    assert binding.thread_id == "thread-new"
    assert binding.user_id == "U2"
    await s.close()


@pytest.mark.docker
@pytest.mark.asyncio
async def test_postgres_last_binding_for_agent_ignores_other_agents(postgres_dsn):
    s = PostgresChannelStore(postgres_dsn)
    await s.set_thread_binding("slack", "T1", "thread-1", "other-bot", user_id="U1")
    assert await s.last_binding_for_agent("slack", "ops-bot") is None
    await s.close()


@pytest.mark.docker
@pytest.mark.asyncio
async def test_postgres_last_binding_for_agent_ignores_other_channel_types(postgres_dsn):
    s = PostgresChannelStore(postgres_dsn)
    await s.set_thread_binding("discord", "G1", "thread-1", "ops-bot", user_id="U1")
    assert await s.last_binding_for_agent("slack", "ops-bot") is None
    await s.close()
