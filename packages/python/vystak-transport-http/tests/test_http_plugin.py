"""Tests for HttpTransportPlugin."""

from __future__ import annotations

from vystak.schema import Platform, Transport
from vystak.schema.agent import Agent
from vystak.schema.model import Model
from vystak.schema.provider import Provider
from vystak_transport_http import HttpTransportPlugin


def test_type():
    p = HttpTransportPlugin()
    assert p.type == "http"


def test_no_provision_nodes():
    p = HttpTransportPlugin()
    t = Transport(name="default-http", type="http")
    provider = Provider(name="docker", type="docker")
    pl = Platform(name="main", type="docker", provider=provider, transport=t)
    assert p.build_provision_nodes(t, pl) == []


def test_env_contract():
    p = HttpTransportPlugin()
    t = Transport(name="default-http", type="http")
    env = p.generate_env_contract(t, context={})
    assert env["VYSTAK_TRANSPORT_TYPE"] == "http"


def test_no_listener_code():
    p = HttpTransportPlugin()
    t = Transport(name="default-http", type="http")
    assert p.generate_listener_code(t) is None


def test_resolve_address_for_docker_dns():
    """resolve_address_for returns Docker-style DNS URL using platform namespace."""
    p = HttpTransportPlugin()
    provider = Provider(name="docker", type="docker")
    pl = Platform(name="main", type="docker", provider=provider, namespace="prod")
    _openai = Provider(name="openai", type="openai", api_key_env="OPENAI_API_KEY")
    model = Model(name="gpt-4o", model_name="gpt-4o", provider=_openai)
    agent = Agent(name="my-agent", model=model, port=9000)
    url = p.resolve_address_for(agent, pl)
    assert url == "http://my-agent-prod:9000/a2a"


def test_resolve_address_for_default_port():
    """resolve_address_for uses port 8000 when agent.port is None."""
    p = HttpTransportPlugin()
    provider = Provider(name="docker", type="docker")
    pl = Platform(name="main", type="docker", provider=provider, namespace="default")
    _openai = Provider(name="openai", type="openai", api_key_env="OPENAI_API_KEY")
    model = Model(name="gpt-4o", model_name="gpt-4o", provider=_openai)
    agent = Agent(name="worker", model=model)
    url = p.resolve_address_for(agent, pl)
    assert url == "http://worker-default:8000/a2a"
