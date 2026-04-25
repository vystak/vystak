"""Tests for subagent string-ref resolution in load_multi_yaml."""
import copy

import pytest
from vystak.schema.multi_loader import load_multi_yaml

BASE = {
    "providers": {"docker": {"type": "docker"}, "anthropic": {"type": "anthropic"}},
    "platforms": {"local": {"type": "docker", "provider": "docker"}},
    "models": {
        "sonnet": {"provider": "anthropic", "model_name": "claude-sonnet-4-20250514"},
    },
    "agents": [
        {"name": "weather-agent", "model": "sonnet", "platform": "local"},
        {"name": "time-agent", "model": "sonnet", "platform": "local"},
        {
            "name": "assistant-agent",
            "model": "sonnet",
            "platform": "local",
            "subagents": ["weather-agent", "time-agent"],
        },
    ],
}


def test_subagent_string_refs_resolve_to_agent_objects():
    data = copy.deepcopy(BASE)
    agents, _channels, _vault = load_multi_yaml(data)
    assistant = next(a for a in agents if a.name == "assistant-agent")
    assert [s.name for s in assistant.subagents] == ["weather-agent", "time-agent"]
    weather_top = next(a for a in agents if a.name == "weather-agent")
    assert assistant.subagents[0] is weather_top  # identity, not just equality


def test_unknown_subagent_raises_with_helpful_message():
    data = copy.deepcopy(BASE)
    data["agents"][2]["subagents"] = ["weather-agent", "ghost-agent"]
    with pytest.raises(KeyError, match="ghost-agent"):
        load_multi_yaml(data)


def test_agent_without_subagents_field_loads_normally():
    data = copy.deepcopy(BASE)
    data["agents"][2].pop("subagents")
    agents, _channels, _vault = load_multi_yaml(data)
    assistant = next(a for a in agents if a.name == "assistant-agent")
    assert assistant.subagents == []
