from vystak.hash.tree import hash_agent, hash_channel
from vystak.schema.agent import Agent
from vystak.schema.channel import Channel
from vystak.schema.common import ChannelType, McpTransport, RuntimeMode, WorkspaceType
from vystak.schema.mcp import McpServer
from vystak.schema.model import Model
from vystak.schema.platform import Platform
from vystak.schema.provider import Provider
from vystak.schema.secret import Secret
from vystak.schema.service import Postgres, Redis
from vystak.schema.skill import Skill
from vystak.schema.workspace import Workspace


def make_agent(**overrides):
    anthropic = Provider(name="anthropic", type="anthropic")
    model = Model(name="claude", provider=anthropic, model_name="claude-sonnet-4-20250514")
    defaults = {"name": "bot", "model": model}
    defaults.update(overrides)
    return Agent(**defaults)


def make_platform(namespace: str = "default") -> Platform:
    docker = Provider(name="docker", type="docker")
    return Platform(name="local", type="docker", provider=docker, namespace=namespace)


class TestAgentHashTree:
    def test_deterministic(self):
        agent = make_agent()
        tree1 = hash_agent(agent)
        tree2 = hash_agent(agent)
        assert tree1.root == tree2.root

    def test_all_fields_populated(self):
        agent = make_agent()
        tree = hash_agent(agent)
        assert tree.brain
        assert tree.skills
        assert tree.mcp_servers
        assert tree.workspace
        assert tree.resources
        assert tree.secrets
        assert tree.root

    def test_model_change_changes_brain_and_root(self):
        agent1 = make_agent()
        anthropic = Provider(name="anthropic", type="anthropic")
        different_model = Model(
            name="opus", provider=anthropic, model_name="claude-opus-4-20250514"
        )
        agent2 = make_agent(model=different_model)
        tree1 = hash_agent(agent1)
        tree2 = hash_agent(agent2)
        assert tree1.brain != tree2.brain
        assert tree1.root != tree2.root
        assert tree1.skills == tree2.skills

    def test_skill_change_changes_skills_and_root(self):
        agent1 = make_agent(skills=[Skill(name="a", tools=["tool1"])])
        agent2 = make_agent(skills=[Skill(name="b", tools=["tool2"])])
        tree1 = hash_agent(agent1)
        tree2 = hash_agent(agent2)
        assert tree1.skills != tree2.skills
        assert tree1.root != tree2.root
        assert tree1.brain == tree2.brain

    def test_mcp_change_detected(self):
        agent1 = make_agent()
        agent2 = make_agent(
            mcp_servers=[McpServer(name="fs", transport=McpTransport.STDIO, command="fs-mcp")]
        )
        tree1 = hash_agent(agent1)
        tree2 = hash_agent(agent2)
        assert tree1.mcp_servers != tree2.mcp_servers

    def test_workspace_change_detected(self):
        agent1 = make_agent()
        agent2 = make_agent(
            workspace=Workspace(name="sandbox", type=WorkspaceType.SANDBOX, filesystem=True)
        )
        tree1 = hash_agent(agent1)
        tree2 = hash_agent(agent2)
        assert tree1.workspace != tree2.workspace

    def test_secret_change_detected(self):
        agent1 = make_agent(secrets=[Secret(name="KEY_A")])
        agent2 = make_agent(secrets=[Secret(name="KEY_B")])
        tree1 = hash_agent(agent1)
        tree2 = hash_agent(agent2)
        assert tree1.secrets != tree2.secrets


class TestAgentHashTreeServices:
    def test_sessions_change_detected(self):
        docker = Provider(name="docker", type="docker")
        agent1 = make_agent()
        agent2 = make_agent(sessions=Postgres(provider=docker))
        tree1 = hash_agent(agent1)
        tree2 = hash_agent(agent2)
        assert tree1.sessions != tree2.sessions
        assert tree1.root != tree2.root

    def test_memory_change_detected(self):
        docker = Provider(name="docker", type="docker")
        agent1 = make_agent()
        agent2 = make_agent(memory=Postgres(provider=docker))
        tree1 = hash_agent(agent1)
        tree2 = hash_agent(agent2)
        assert tree1.memory != tree2.memory
        assert tree1.root != tree2.root

    def test_services_change_detected(self):
        docker = Provider(name="docker", type="docker")
        agent1 = make_agent()
        agent2 = make_agent(services=[Redis(name="cache", provider=docker)])
        tree1 = hash_agent(agent1)
        tree2 = hash_agent(agent2)
        assert tree1.services != tree2.services
        assert tree1.root != tree2.root

    def test_sessions_vs_memory_different_hashes(self):
        docker = Provider(name="docker", type="docker")
        agent1 = make_agent(sessions=Postgres(provider=docker))
        agent2 = make_agent(memory=Postgres(provider=docker))
        tree1 = hash_agent(agent1)
        tree2 = hash_agent(agent2)
        assert tree1.root != tree2.root

    def test_compaction_change_changes_agent_hash(self):
        from vystak.schema.compaction import Compaction

        base = make_agent()
        with_compaction = base.model_copy(
            update={"compaction": Compaction(mode="conservative")}
        )
        aggressive = base.model_copy(
            update={"compaction": Compaction(mode="aggressive")}
        )

        h_base = hash_agent(base)
        h_cons = hash_agent(with_compaction)
        h_agg = hash_agent(aggressive)

        assert h_base.root != h_cons.root
        assert h_cons.root != h_agg.root
        assert h_base.root != h_agg.root


class TestChannelHashTree:
    def test_deterministic(self):
        ch = Channel(name="slack", type=ChannelType.SLACK, platform=make_platform())
        tree1 = hash_channel(ch)
        tree2 = hash_channel(ch)
        assert tree1.root == tree2.root

    def test_agents_change_detected(self):
        agent_a = make_agent(name="agent-a")
        agent_b = make_agent(name="agent-b")
        ch1 = Channel(
            name="slack",
            type=ChannelType.SLACK,
            platform=make_platform(),
            agents=[agent_a],
        )
        ch2 = Channel(
            name="slack",
            type=ChannelType.SLACK,
            platform=make_platform(),
            agents=[agent_b],
        )
        tree1 = hash_channel(ch1)
        tree2 = hash_channel(ch2)
        assert tree1.routes != tree2.routes
        assert tree1.root != tree2.root

    def test_runtime_mode_change_detected(self):
        ch1 = Channel(name="voice", type=ChannelType.VOICE, platform=make_platform())
        ch2 = Channel(
            name="voice",
            type=ChannelType.VOICE,
            platform=make_platform(),
            runtime_mode=RuntimeMode.PER_SESSION,
        )
        tree1 = hash_channel(ch1)
        tree2 = hash_channel(ch2)
        assert tree1.runtime != tree2.runtime
        assert tree1.root != tree2.root

    def test_config_change_detected(self):
        ch1 = Channel(
            name="slack",
            type=ChannelType.SLACK,
            platform=make_platform(),
            config={"bot_token_secret": "A"},
        )
        ch2 = Channel(
            name="slack",
            type=ChannelType.SLACK,
            platform=make_platform(),
            config={"bot_token_secret": "B"},
        )
        tree1 = hash_channel(ch1)
        tree2 = hash_channel(ch2)
        assert tree1.config != tree2.config
        assert tree1.root != tree2.root

    def test_secrets_change_detected(self):
        from vystak.schema.secret import Secret

        ch1 = Channel(
            name="slack",
            type=ChannelType.SLACK,
            platform=make_platform(),
            secrets=[Secret(name="SLACK_BOT_TOKEN")],
        )
        ch2 = Channel(
            name="slack",
            type=ChannelType.SLACK,
            platform=make_platform(),
            secrets=[Secret(name="SLACK_APP_TOKEN")],
        )
        tree1 = hash_channel(ch1)
        tree2 = hash_channel(ch2)
        assert tree1.secrets != tree2.secrets
        assert tree1.root != tree2.root


def test_adding_subagent_changes_caller_root_hash():
    from vystak.hash.tree import hash_agent
    from vystak.schema.agent import Agent
    from vystak.schema.model import Model
    from vystak.schema.provider import Provider

    p = Provider(name="p", type="anthropic")
    m = Model(name="m", provider=p, model_name="claude-sonnet-4-20250514")
    weather = Agent(name="weather-agent", model=m)
    bare = Agent(name="assistant-agent", model=m)
    with_peer = Agent(name="assistant-agent", model=m, subagents=[weather])

    assert hash_agent(bare).root != hash_agent(with_peer).root


def test_reordering_subagents_does_not_change_caller_hash():
    from vystak.hash.tree import hash_agent
    from vystak.schema.agent import Agent
    from vystak.schema.model import Model
    from vystak.schema.provider import Provider

    p = Provider(name="p", type="anthropic")
    m = Model(name="m", provider=p, model_name="claude-sonnet-4-20250514")
    weather = Agent(name="weather-agent", model=m)
    time = Agent(name="time-agent", model=m)
    a = Agent(name="assistant", model=m, subagents=[weather, time])
    b = Agent(name="assistant", model=m, subagents=[time, weather])

    assert hash_agent(a).root == hash_agent(b).root


def test_peer_hash_unchanged_when_added_as_subagent():
    """Adding a peer to a caller does not affect the peer's own hash."""
    from vystak.hash.tree import hash_agent
    from vystak.schema.agent import Agent
    from vystak.schema.model import Model
    from vystak.schema.provider import Provider

    p = Provider(name="p", type="anthropic")
    m = Model(name="m", provider=p, model_name="claude-sonnet-4-20250514")
    weather = Agent(name="weather-agent", model=m)
    weather_alone_root = hash_agent(weather).root

    # Build a caller that references it; weather's own hash must not change.
    _assistant = Agent(name="assistant", model=m, subagents=[weather])
    assert hash_agent(weather).root == weather_alone_root
