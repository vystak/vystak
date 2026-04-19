"""Tests for HttpTransportPlugin."""

from __future__ import annotations

from vystak.schema import Platform, Transport
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
