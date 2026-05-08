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
from vystak_transport_nats import NatsTransportPlugin

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
    return Agent(name=name, framework="langchain-python", model=_MODEL, port=port)


# ---------------------------------------------------------------------------
# get_transport_plugin
# ---------------------------------------------------------------------------


def test_get_transport_plugin_http():
    plugin = get_transport_plugin("http")
    assert isinstance(plugin, HttpTransportPlugin)
    assert plugin.type == "http"


def test_get_transport_plugin_nats():
    plugin = get_transport_plugin("nats")
    assert isinstance(plugin, NatsTransportPlugin)
    assert plugin.type == "nats"


def test_get_transport_plugin_unknown():
    with pytest.raises(KeyError, match="Unknown transport type"):
        get_transport_plugin("kafka")


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
    # Phase 10: card_url alongside address so the SDK client can resolve.
    assert (
        routes["alpha"]["card_url"]
        == "http://vystak-alpha:8000/.well-known/agent.json"
    )


def test_build_peer_routes_multiple_agents():
    plugin = HttpTransportPlugin()
    pl = _platform("prod")
    agents = [_agent("svc-a"), _agent("svc-b", port=9000)]

    routes = build_peer_routes(agents, plugin, pl)

    assert set(routes.keys()) == {"svc-a", "svc-b"}
    assert routes["svc-a"]["address"] == "http://vystak-svc-a:8000/a2a"
    assert routes["svc-b"]["address"] == "http://vystak-svc-b:9000/a2a"
    assert (
        routes["svc-a"]["card_url"]
        == "http://vystak-svc-a:8000/.well-known/agent.json"
    )
    assert (
        routes["svc-b"]["card_url"]
        == "http://vystak-svc-b:9000/.well-known/agent.json"
    )


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
    assert parsed["bot"]["card_url"] == "http://vystak-bot:8000/.well-known/agent.json"


def test_build_routes_json_empty_agents():
    plugin = HttpTransportPlugin()
    pl = _platform()
    assert build_routes_json([], plugin, pl) == "{}"


# ---------------------------------------------------------------------------
# NATS transport: card_url is omitted (not discoverable over NATS)
# ---------------------------------------------------------------------------


def _nats_platform(namespace: str = "default", prefix: str = "vystak") -> Platform:
    from vystak.schema.transport import NatsConfig

    return Platform(
        name="main",
        type="docker",
        provider=_DOCKER_PROVIDER,
        namespace=namespace,
        transport=Transport(
            name="bus",
            type="nats",
            config=NatsConfig(jetstream=True, subject_prefix=prefix),
        ),
    )


def test_build_peer_routes_nats_omits_card_url():
    """NATS routes carry the listener subject; cards are not discoverable
    over NATS so card_url is omitted entirely."""
    plugin = NatsTransportPlugin()
    pl = _nats_platform("multi-nats", prefix="vystak-nats")
    agents = [_agent("weather"), _agent("time")]

    routes = build_peer_routes(agents, plugin, pl)

    assert set(routes.keys()) == {"weather", "time"}
    assert routes["weather"]["address"] == "vystak-nats.multi-nats.agents.weather.tasks"
    assert routes["time"]["address"] == "vystak-nats.multi-nats.agents.time.tasks"
    # Critical: NATS routes must NOT carry a bogus card_url like
    # "<subject>/.well-known/agent.json" that fails URL parsing.
    assert "card_url" not in routes["weather"]
    assert "card_url" not in routes["time"]


def test_build_routes_json_nats_serialised_omits_card_url():
    """End-to-end JSON shape: subagent runtime sees no card_url for NATS."""
    plugin = NatsTransportPlugin()
    pl = _nats_platform("multi-nats", prefix="vystak-nats")
    agents = [_agent("weather")]

    raw = build_routes_json(agents, plugin, pl)
    parsed = json.loads(raw)
    assert "card_url" not in parsed["weather"]
    assert parsed["weather"]["address"] == "vystak-nats.multi-nats.agents.weather.tasks"
