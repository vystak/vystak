"""Tests for DiscordChannelRuntime."""

from vystak_channel_discord.runtime import DiscordChannelRuntime
from vystak_channel_runtime.store import MemoryChannelStore


def _config():
    return {
        "channel_type": "discord",
        "agent_protocol": "a2a-turn",
        "agents": ["hero"],
        "default_agent": "hero",
        "group_policy": "open",
        "dm_policy": "open",
        "allow_from": [],
        "allow_bots": False,
        "channel_overrides": {},
        "register_slash_commands": False,
    }


def test_runtime_constructable():
    rt = DiscordChannelRuntime(
        config=_config(),
        routes={"hero": {"address": "http://hero:8000"}},
        store=MemoryChannelStore(),
    )
    assert rt.channel_type == "discord"
