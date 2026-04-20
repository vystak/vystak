"""Tests for TransportPlugin ABC."""

from __future__ import annotations

import pytest
from vystak.providers.base import TransportPlugin
from vystak.schema import Platform, Transport
from vystak.schema.provider import Provider


class FakeTransportPlugin(TransportPlugin):
    type = "fake"

    def build_provision_nodes(self, transport, platform):
        return []

    def generate_env_contract(self, transport, context):
        return {"VYSTAK_TRANSPORT_TYPE": "fake"}

    def generate_listener_code(self, transport):
        return None


def test_cannot_instantiate_abstract():
    with pytest.raises(TypeError):
        TransportPlugin()


def test_concrete_plugin():
    p = FakeTransportPlugin()
    assert p.type == "fake"
    t = Transport(name="x", type="http")
    pl = Platform(
        name="p",
        type="local",
        provider=Provider(name="docker", type="docker"),
        transport=t,
    )
    assert p.build_provision_nodes(t, pl) == []
    assert p.generate_env_contract(t, {}) == {"VYSTAK_TRANSPORT_TYPE": "fake"}
    assert p.generate_listener_code(t) is None
