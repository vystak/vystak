"""Tests for NatsTransportPlugin."""

from __future__ import annotations

from vystak.schema import NatsConfig, Platform, Transport
from vystak.schema.agent import Agent
from vystak.schema.model import Model
from vystak.schema.provider import Provider
from vystak_transport_nats import NatsTransportPlugin


def _make_provider() -> Provider:
    return Provider(name="docker", type="docker")


def _make_openai_provider() -> Provider:
    return Provider(name="openai", type="openai", api_key_env="OPENAI_API_KEY")


def _make_agent(name: str = "my-agent") -> Agent:
    model = Model(name="gpt-4o", model_name="gpt-4o", provider=_make_openai_provider())
    return Agent(name=name, model=model)


def test_type():
    p = NatsTransportPlugin()
    assert p.type == "nats"


def test_build_provision_nodes_returns_empty():
    p = NatsTransportPlugin()
    t = Transport(name="bus", type="nats")
    pl = Platform(name="main", type="docker", provider=_make_provider(), transport=t)
    assert p.build_provision_nodes(t, pl) == []


def test_generate_env_contract_without_nats_url():
    p = NatsTransportPlugin()
    t = Transport(name="bus", type="nats", config=NatsConfig(subject_prefix="vystak"))
    env = p.generate_env_contract(t, context={})
    assert env["VYSTAK_TRANSPORT_TYPE"] == "nats"
    assert "VYSTAK_NATS_URL" not in env
    assert env["VYSTAK_NATS_SUBJECT_PREFIX"] == "vystak"


def test_generate_env_contract_with_nats_url():
    p = NatsTransportPlugin()
    t = Transport(name="bus", type="nats", config=NatsConfig(subject_prefix="myapp"))
    env = p.generate_env_contract(t, context={"nats_url": "nats://vystak-nats:4222"})
    assert env["VYSTAK_TRANSPORT_TYPE"] == "nats"
    assert env["VYSTAK_NATS_URL"] == "nats://vystak-nats:4222"
    assert env["VYSTAK_NATS_SUBJECT_PREFIX"] == "myapp"


def test_generate_env_contract_without_config():
    """When transport.config is None, only VYSTAK_TRANSPORT_TYPE is set."""
    p = NatsTransportPlugin()
    t = Transport(name="bus", type="nats")
    env = p.generate_env_contract(t, context={})
    assert env["VYSTAK_TRANSPORT_TYPE"] == "nats"
    assert "VYSTAK_NATS_SUBJECT_PREFIX" not in env


def test_generate_listener_code_returns_none():
    p = NatsTransportPlugin()
    t = Transport(name="bus", type="nats")
    assert p.generate_listener_code(t) is None


def test_resolve_address_for_default_prefix():
    """resolve_address_for uses 'vystak' prefix when config has default."""
    p = NatsTransportPlugin()
    t = Transport(name="bus", type="nats", config=NatsConfig())
    pl = Platform(
        name="main", type="docker", provider=_make_provider(), transport=t, namespace="prod"
    )
    agent = _make_agent("time-agent")
    subject = p.resolve_address_for(agent, pl)
    assert subject == "vystak.prod.agents.time-agent.tasks"


def test_resolve_address_for_custom_prefix():
    """resolve_address_for uses config.subject_prefix when set."""
    p = NatsTransportPlugin()
    t = Transport(name="bus", type="nats", config=NatsConfig(subject_prefix="myns"))
    pl = Platform(
        name="main", type="docker", provider=_make_provider(), transport=t, namespace="staging"
    )
    agent = _make_agent("weather-agent")
    subject = p.resolve_address_for(agent, pl)
    assert subject == "myns.staging.agents.weather-agent.tasks"


def test_resolve_address_for_no_config_falls_back_to_vystak():
    """resolve_address_for falls back to 'vystak' prefix when config is None."""
    p = NatsTransportPlugin()
    t = Transport(name="bus", type="nats")
    pl = Platform(
        name="main", type="docker", provider=_make_provider(), transport=t, namespace="default"
    )
    agent = _make_agent("echo")
    subject = p.resolve_address_for(agent, pl)
    assert subject == "vystak.default.agents.echo.tasks"


def test_resolve_address_for_no_namespace_defaults_to_default():
    """resolve_address_for uses 'default' namespace when platform.namespace is None."""
    p = NatsTransportPlugin()
    t = Transport(name="bus", type="nats", config=NatsConfig(subject_prefix="vystak"))
    pl = Platform(name="main", type="docker", provider=_make_provider(), transport=t)
    agent = _make_agent("my-agent")
    subject = p.resolve_address_for(agent, pl)
    assert subject == "vystak.default.agents.my-agent.tasks"
