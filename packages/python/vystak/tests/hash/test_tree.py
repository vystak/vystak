"""Hash-tree tests for transport integration."""

from vystak.hash.tree import hash_agent, hash_channel, hash_generated_code
from vystak.providers.base import GeneratedCode
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


class TestCodegenHashing:
    """Codegen output digest contributes to root so codegen-only changes
    (e.g. turn_core.py / a2a.py source edits) bump the deploy hash even when
    the Agent schema hasn't moved."""

    def _code(self, **files: str) -> GeneratedCode:
        return GeneratedCode(files=dict(files), entrypoint="server.py")

    def test_codegen_section_present_with_default(self):
        tree = hash_agent(_agent())
        assert hasattr(tree, "codegen")
        assert len(tree.codegen) == 64

    def test_default_is_null_hash_when_codegen_omitted(self):
        # Backwards compat: callers that don't pass codegen_hash get the
        # canonical null section, identical to the old single-section build.
        tree_a = hash_agent(_agent())
        tree_b = hash_agent(_agent(), codegen_hash=None)
        assert tree_a.codegen == tree_b.codegen
        assert tree_a.root == tree_b.root

    def test_codegen_change_changes_root(self):
        digest_a = hash_generated_code(self._code(**{"server.py": "v1"}))
        digest_b = hash_generated_code(self._code(**{"server.py": "v2"}))
        assert digest_a != digest_b
        tree_a = hash_agent(_agent(), codegen_hash=digest_a)
        tree_b = hash_agent(_agent(), codegen_hash=digest_b)
        assert tree_a.codegen != tree_b.codegen
        assert tree_a.root != tree_b.root

    def test_codegen_same_content_same_hash(self):
        digest_a = hash_generated_code(self._code(**{"server.py": "x"}))
        digest_b = hash_generated_code(self._code(**{"server.py": "x"}))
        assert digest_a == digest_b

    def test_hash_generated_code_handles_none(self):
        # Schema-only callers pass None; helper returns null hash.
        assert len(hash_generated_code(None)) == 64

    def test_hash_generated_code_handles_empty_files(self):
        empty = GeneratedCode(files={}, entrypoint="server.py")
        assert hash_generated_code(empty) == hash_generated_code(None)

    def test_hash_generated_code_filename_order_independent(self):
        d1 = hash_generated_code(self._code(**{"a.py": "1", "b.py": "2"}))
        # Different insertion order — must produce same digest.
        d2 = hash_generated_code(GeneratedCode(
            files={"b.py": "2", "a.py": "1"}, entrypoint="server.py",
        ))
        assert d1 == d2

    def test_channel_codegen_threads_through(self):
        from vystak.schema.channel import Channel
        from vystak.schema.common import ChannelType

        platform = Platform(
            name="main",
            type="docker",
            provider=Provider(name="docker", type="docker"),
        )
        channel = Channel(
            name="ch", type=ChannelType.SLACK, platform=platform,
        )
        digest_a = hash_generated_code(self._code(**{"server.py": "v1"}))
        digest_b = hash_generated_code(self._code(**{"server.py": "v2"}))
        tree_a = hash_channel(channel, codegen_hash=digest_a)
        tree_b = hash_channel(channel, codegen_hash=digest_b)
        assert tree_a.codegen != tree_b.codegen
        assert tree_a.root != tree_b.root
