"""Tests for ChannelStore impls."""

from pathlib import Path

import pytest
from vystak_channel_runtime.store import (
    ChannelStore,
    MemoryChannelStore,
    SqliteChannelStore,
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
