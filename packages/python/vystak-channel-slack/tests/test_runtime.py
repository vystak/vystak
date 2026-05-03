"""Tests for SlackChannelRuntime."""

from vystak_channel_runtime.store import MemoryChannelStore
from vystak_channel_slack.runtime import SlackChannelRuntime


def _config():
    return {
        "channel_type": "slack",
        "agent_protocol": "a2a-turn",
        "agents": ["hero"],
        "default_agent": "hero",
        "group_policy": "open",
        "dm_policy": "open",
        "allow_from": [],
        "allow_bots": False,
        "channel_overrides": {},
    }


def test_runtime_constructable():
    rt = SlackChannelRuntime(
        config=_config(),
        routes={"hero": {"address": "http://hero:8000"}},
        store=MemoryChannelStore(),
    )
    assert rt.channel_type == "slack"
