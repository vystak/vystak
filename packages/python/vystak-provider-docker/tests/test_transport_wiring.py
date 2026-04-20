"""Tests for vystak_provider_docker.transport_wiring."""

from __future__ import annotations

import json

import pytest
from vystak.schema.agent import Agent
from vystak.schema.model import Model
from vystak.schema.platform import Platform
from vystak.schema.provider import Provider
from vystak.schema.transport import Transport
from vystak_provider_docker.transport_wiring import (
    build_peer_routes,
    build_routes_json,
    get_transport_plugin,
)
from vystak_transport_http import HttpTransportPlugin

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_OPENAI_PROVIDER = Provider(name="openai", type="openai", api_key_env="OPENAI_API_KEY")
_MODEL = Model(name="gpt-4o", model_name="gpt-4o", provider=_OPENAI_PROVIDER)
_DOCKER_PROVIDER = Provider(name="docker", type="docker")


def _platform(namespace: str = "default") -> Platform:
    return Platform(
        name="main",
        type="docker",
        provider=_DOCKER_PROVIDER,
        namespace=namespace,
        transport=Transport(name="default-http", type="http"),
    )


def _agent(name: str, port: int | None = None) -> Agent:
    return Agent(name=name, model=_MODEL, port=port)


# ---------------------------------------------------------------------------
# get_transport_plugin
# ---------------------------------------------------------------------------


def test_get_transport_plugin_http():
    plugin = get_transport_plugin("http")
    assert isinstance(plugin, HttpTransportPlugin)
    assert plugin.type == "http"


def test_get_transport_plugin_unknown():
    with pytest.raises(KeyError, match="Unknown transport type"):
        get_transport_plugin("nats")


# ---------------------------------------------------------------------------
# build_peer_routes
# ---------------------------------------------------------------------------


def test_build_peer_routes_single_agent():
    plugin = HttpTransportPlugin()
    pl = _platform("staging")
    agents = [_agent("alpha", port=8000)]

    routes = build_peer_routes(agents, plugin, pl)

    assert "alpha" in routes
    assert routes["alpha"]["canonical"] == "alpha.agents.default"
    assert routes["alpha"]["address"] == "http://vystak-alpha:8000/a2a"


def test_build_peer_routes_multiple_agents():
    plugin = HttpTransportPlugin()
    pl = _platform("prod")
    agents = [_agent("svc-a"), _agent("svc-b", port=9000)]

    routes = build_peer_routes(agents, plugin, pl)

    assert set(routes.keys()) == {"svc-a", "svc-b"}
    assert routes["svc-a"]["address"] == "http://vystak-svc-a:8000/a2a"
    assert routes["svc-b"]["address"] == "http://vystak-svc-b:9000/a2a"


def test_build_peer_routes_empty():
    plugin = HttpTransportPlugin()
    pl = _platform()
    assert build_peer_routes([], plugin, pl) == {}


# ---------------------------------------------------------------------------
# build_routes_json
# ---------------------------------------------------------------------------


def test_build_routes_json_is_valid_json():
    plugin = HttpTransportPlugin()
    pl = _platform("test")
    agents = [_agent("bot")]

    raw = build_routes_json(agents, plugin, pl)
    parsed = json.loads(raw)

    assert "bot" in parsed
    assert parsed["bot"]["address"] == "http://vystak-bot:8000/a2a"


def test_build_routes_json_empty_agents():
    plugin = HttpTransportPlugin()
    pl = _platform()
    assert build_routes_json([], plugin, pl) == "{}"
