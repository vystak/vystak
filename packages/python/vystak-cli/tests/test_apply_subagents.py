"""Tests that restrictive routing scopes VYSTAK_ROUTES_JSON to declared subagents."""
import json
from unittest.mock import MagicMock, patch

from vystak.schema.agent import Agent
from vystak.schema.model import Model
from vystak.schema.platform import Platform
from vystak.schema.provider import Provider
from vystak.schema.transport import HttpConfig, Transport


def _build_agents():
    docker_provider = Provider(name="docker", type="docker")
    anthropic = Provider(name="anthropic", type="anthropic")
    transport = Transport(name="default-http", type="http", config=HttpConfig())
    platform = Platform(
        name="local", type="docker", provider=docker_provider, transport=transport,
    )
    model = Model(
        name="m", provider=anthropic, model_name="claude-sonnet-4-20250514",
    )
    weather = Agent(name="weather-agent", model=model, platform=platform)
    time = Agent(name="time-agent", model=model, platform=platform)
    assistant = Agent(
        name="assistant-agent", model=model, platform=platform,
        subagents=[weather, time],
    )
    return weather, time, assistant


def test_routes_for_solo_agent_only_contain_declared_subagents():
    """Weather agent declares no subagents — its route table is empty."""
    from vystak_provider_docker.transport_wiring import build_routes_json, get_transport_plugin

    weather, _time, _assistant = _build_agents()
    plugin = get_transport_plugin("http")
    routes = json.loads(build_routes_json(weather.subagents, plugin, weather.platform))
    assert routes == {}


def test_routes_for_caller_contain_only_declared_peers():
    """Assistant declares [weather, time] — its route table contains both, nothing more."""
    from vystak_provider_docker.transport_wiring import build_routes_json, get_transport_plugin

    _weather, _time, assistant = _build_agents()
    plugin = get_transport_plugin("http")
    routes = json.loads(build_routes_json(assistant.subagents, plugin, assistant.platform))
    assert set(routes.keys()) == {"weather-agent", "time-agent"}
