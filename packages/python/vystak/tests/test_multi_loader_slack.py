# test_multi_loader_slack.py
import copy

import pytest
from vystak.schema.multi_loader import load_multi_yaml

BASE = {
    "providers": {
        "docker": {"type": "docker"},
        "anthropic": {"type": "anthropic"},
    },
    "platforms": {"local": {"type": "docker", "provider": "docker"}},
    "models": {
        "sonnet": {"provider": "anthropic", "model_name": "claude-sonnet-4-20250514"},
    },
    "agents": [
        {"name": "weather-agent", "model": "sonnet", "platform": "local"},
        {"name": "support-agent", "model": "sonnet", "platform": "local"},
    ],
    "channels": [
        {
            "name": "slack-main",
            "type": "slack",
            "platform": "local",
            "secrets": [{"name": "SLACK_BOT_TOKEN"},
                        {"name": "SLACK_APP_TOKEN"}],
            "agents": ["weather-agent", "support-agent"],
            "default_agent": "weather-agent",
            "channel_overrides": {
                "C12345678": {"agent": "support-agent",
                              "system_prompt": "triage"},
            },
        }
    ],
}


def test_slack_channel_resolves_agent_refs():
    data = copy.deepcopy(BASE)
    agents, channels, _vault = load_multi_yaml(data)
    ch = channels[0]
    assert [a.name for a in ch.agents] == ["weather-agent", "support-agent"]
    assert ch.default_agent.name == "weather-agent"
    assert ch.channel_overrides["C12345678"].agent.name == "support-agent"


def test_slack_routes_legacy_field_rejected():
    data = copy.deepcopy(BASE)
    data["channels"][0]["routes"] = [{"match": {"dm": True},
                                       "agent": "weather-agent"}]
    data["channels"][0].pop("agents")
    data["channels"][0].pop("default_agent")
    data["channels"][0].pop("channel_overrides")
    with pytest.raises(ValueError, match="routes.*deprecated"):
        load_multi_yaml(data)


def test_default_agent_unknown_name_raises():
    data = copy.deepcopy(BASE)
    data["channels"][0]["default_agent"] = "ghost"
    with pytest.raises(KeyError, match="ghost"):
        load_multi_yaml(data)
