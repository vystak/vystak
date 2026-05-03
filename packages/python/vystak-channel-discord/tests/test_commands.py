"""Tests for /vystak slash command handlers."""

import pytest
from vystak_channel_discord.commands import (
    handle_prefer,
    handle_route,
    handle_status,
    handle_unprefer,
    handle_unroute,
)
from vystak_channel_runtime.store import MemoryChannelStore


@pytest.mark.asyncio
async def test_handle_route_sets_thread_binding():
    store = MemoryChannelStore()
    msg = await handle_route(store, scope_id="100/200", thread_id="100/200:", agent="hero")
    assert "hero" in msg
    assert await store.get_thread_binding("discord", "100/200", "100/200:") == "hero"


@pytest.mark.asyncio
async def test_handle_unroute_removes_binding():
    store = MemoryChannelStore()
    await store.set_thread_binding("discord", "100/200", "100/200:", "hero")
    msg = await handle_unroute(store, scope_id="100/200", thread_id="100/200:")
    assert "removed" in msg.lower() or "unrouted" in msg.lower()
    assert await store.get_thread_binding("discord", "100/200", "100/200:") is None


@pytest.mark.asyncio
async def test_handle_prefer_sets_route_pref():
    store = MemoryChannelStore()
    msg = await handle_prefer(store, scope_id="dm/42", agent="villain")
    assert "villain" in msg
    assert await store.get_route_pref("discord", "dm/42") == "villain"


@pytest.mark.asyncio
async def test_handle_unprefer_removes_route_pref():
    store = MemoryChannelStore()
    await store.set_route_pref("discord", "dm/42", "villain")
    await handle_unprefer(store, scope_id="dm/42")
    assert await store.get_route_pref("discord", "dm/42") is None


@pytest.mark.asyncio
async def test_handle_status_lists_bindings():
    store = MemoryChannelStore()
    await store.set_thread_binding("discord", "100/200", "T:1", "hero")
    msg = await handle_status(store, scope_id="100/200")
    assert "hero" in msg
    assert "T:1" in msg
