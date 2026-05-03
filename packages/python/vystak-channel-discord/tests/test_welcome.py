"""Tests for Discord welcome / auto-bind."""

import pytest
from vystak_channel_discord.welcome import auto_bind_single_agent
from vystak_channel_runtime.store import MemoryChannelStore


@pytest.mark.asyncio
async def test_auto_bind_does_nothing_when_multiple_agents():
    store = MemoryChannelStore()
    await auto_bind_single_agent(store, scope_id="100/200", agents=["hero", "villain"])
    assert await store.get_route_pref("discord", "100/200") is None


@pytest.mark.asyncio
async def test_auto_bind_sets_pref_when_single_agent():
    store = MemoryChannelStore()
    await auto_bind_single_agent(store, scope_id="100/200", agents=["hero"])
    assert await store.get_route_pref("discord", "100/200") == "hero"


@pytest.mark.asyncio
async def test_auto_bind_does_nothing_when_already_bound():
    store = MemoryChannelStore()
    await store.set_route_pref("discord", "100/200", "villain")
    await auto_bind_single_agent(store, scope_id="100/200", agents=["hero"])
    assert await store.get_route_pref("discord", "100/200") == "villain"
