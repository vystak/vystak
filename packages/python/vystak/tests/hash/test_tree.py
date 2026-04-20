"""Hash-tree tests for transport integration."""

from vystak.hash.tree import hash_agent
from vystak.schema import (
    Agent,
    Model,
    NatsConfig,
    Platform,
    Provider,
    Transport,
    TransportConnection,
)


def _agent(transport: Transport | None = None) -> Agent:
    """Build an Agent with an embedded Platform + Transport for hashing tests."""
    platform = Platform(
        name="main",
        type="docker",
        provider=Provider(name="docker", type="docker"),
        transport=transport,  # None triggers the default-http synthesis
    )
    return Agent(
        name="a",
        model=Model(
            name="m",
            provider=Provider(name="anthropic", type="anthropic", api_key_env="K"),
            model_name="claude-sonnet-4-20250514",
        ),
        platform=platform,
    )


class TestTransportHashing:
    def test_transport_section_present(self):
        tree = hash_agent(_agent())
        assert hasattr(tree, "transport")
        assert isinstance(tree.transport, str)
        assert len(tree.transport) == 64  # sha256 hex

    def test_hash_changes_when_transport_type_changes(self):
        t1 = Transport(name="bus", type="http")
        t2 = Transport(name="bus", type="nats", config=NatsConfig())
        h1 = hash_agent(_agent(t1))
        h2 = hash_agent(_agent(t2))
        assert h1.transport != h2.transport
        assert h1.root != h2.root

    def test_hash_changes_when_config_changes(self):
        t1 = Transport(name="bus", type="nats", config=NatsConfig(jetstream=True))
        t2 = Transport(name="bus", type="nats", config=NatsConfig(jetstream=False))
        h1 = hash_agent(_agent(t1))
        h2 = hash_agent(_agent(t2))
        assert h1.transport != h2.transport
        assert h1.root != h2.root

    def test_hash_unchanged_for_byo_connection(self):
        # Same transport type/config, different BYO connection — portable.
        t1 = Transport(
            name="bus",
            type="nats",
            config=NatsConfig(),
            connection=TransportConnection(url_env="DEV_NATS_URL"),
        )
        t2 = Transport(
            name="bus",
            type="nats",
            config=NatsConfig(),
            connection=TransportConnection(url_env="PROD_NATS_URL"),
        )
        h1 = hash_agent(_agent(t1))
        h2 = hash_agent(_agent(t2))
        assert h1.transport == h2.transport
        assert h1.root == h2.root

    def test_hash_unchanged_for_transport_name(self):
        # The transport's `name` field is identity for references, not config.
        # Should not affect the agent's hash.
        t1 = Transport(name="bus-alpha", type="http")
        t2 = Transport(name="bus-beta", type="http")
        h1 = hash_agent(_agent(t1))
        h2 = hash_agent(_agent(t2))
        assert h1.transport == h2.transport
        assert h1.root == h2.root

    def test_default_http_synthesis_consistent(self):
        # An agent built with platform.transport=None gets default-http
        # synthesised; hash should match an explicit Transport(name="default-http", type="http").
        h1 = hash_agent(_agent(None))
        h2 = hash_agent(_agent(Transport(name="default-http", type="http")))
        assert h1.transport == h2.transport
        assert h1.root == h2.root

    def test_no_platform_agent_hashes_null_transport(self):
        # Edge case: agent without a platform. Hash must be stable, not error.
        agent = Agent(
            name="a",
            model=Model(
                name="m",
                provider=Provider(name="anthropic", type="anthropic", api_key_env="K"),
                model_name="claude-sonnet-4-20250514",
            ),
            platform=None,
        )
        tree = hash_agent(agent)
        # Transport section still present; computed as "null" hash.
        assert tree.transport is not None
        assert len(tree.transport) == 64
