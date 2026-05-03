"""Tests for ChannelStore impls."""

import pytest
from vystak_channel_runtime.store import (
    ChannelStore,
    MemoryChannelStore,
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
