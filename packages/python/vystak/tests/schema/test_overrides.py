"""Tests for EnvironmentOverride — per-environment config swaps."""

from __future__ import annotations

import pytest
from vystak.schema import Agent, Model, NatsConfig, Platform, Provider, Transport
from vystak.schema.overrides import EnvironmentOverride

_MODEL_NAME = "claude-sonnet-4-20250514"


def _agent(agent_name: str, platform_name: str, transport_type: str = "http") -> Agent:
    platform = Platform(
        name=platform_name,
        type="docker",
        provider=Provider(name="docker", type="docker"),
        transport=Transport(name="t", type=transport_type),
    )
    return Agent(
        name=agent_name,
        model=Model(
            name="m",
            provider=Provider(name="anthropic", type="anthropic", api_key_env="K"),
            model_name=_MODEL_NAME,
        ),
        platform=platform,
    )


class TestEnvironmentOverride:
    def test_empty_override_is_noop(self):
        agents = [_agent("a", "main")]
        merged = EnvironmentOverride().apply(agents)
        assert merged[0].platform.transport.type == "http"

    def test_override_replaces_transport_on_matching_platform(self):
        agents = [_agent("a", "main"), _agent("b", "main")]
        override = EnvironmentOverride(
            transports={"main": Transport(name="bus", type="nats", config=NatsConfig())}
        )
        merged = override.apply(agents)
        assert merged[0].platform.transport.type == "nats"
        assert merged[1].platform.transport.type == "nats"

    def test_override_affects_only_matching_platform(self):
        a_main = _agent("a", "main")
        b_aca = _agent("b", "aca")
        override = EnvironmentOverride(
            transports={"main": Transport(name="bus", type="nats", config=NatsConfig())}
        )
        merged = override.apply([a_main, b_aca])
        assert merged[0].platform.transport.type == "nats"
        assert merged[1].platform.transport.type == "http"

    def test_override_unknown_platform_raises(self):
        agents = [_agent("a", "main")]
        override = EnvironmentOverride(
            transports={"nonexistent": Transport(name="bus", type="nats")}
        )
        with pytest.raises(ValueError, match="nonexistent"):
            override.apply(agents)

    def test_apply_does_not_mutate_base(self):
        agents = [_agent("a", "main")]
        override = EnvironmentOverride(
            transports={"main": Transport(name="bus", type="nats", config=NatsConfig())}
        )
        merged = override.apply(agents)
        # Base agent still has the original http transport.
        assert agents[0].platform.transport.type == "http"
        # Merged list has the nats transport.
        assert merged[0].platform.transport.type == "nats"
