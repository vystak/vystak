import pytest
from pydantic import ValidationError

from vystak.schema.agent import Agent
from vystak.schema.channel import Channel
from vystak.schema.common import ChannelType, McpTransport, WorkspaceType
from vystak.schema.mcp import McpServer
from vystak.schema.model import Model
from vystak.schema.platform import Platform
from vystak.schema.provider import Provider
from vystak.schema.resource import SessionStore
from vystak.schema.secret import Secret
from vystak.schema.service import Postgres, Redis, Sqlite
from vystak.schema.skill import Skill
from vystak.schema.workspace import Workspace


@pytest.fixture()
def anthropic():
    return Provider(name="anthropic", type="anthropic")


@pytest.fixture()
def sonnet(anthropic):
    return Model(name="sonnet", provider=anthropic, model_name="claude-sonnet-4-20250514")


class TestAgent:
    def test_minimal(self, sonnet):
        agent = Agent(name="bot", model=sonnet)
        assert agent.name == "bot"
        assert agent.model.model_name == "claude-sonnet-4-20250514"
        assert agent.skills == []
        assert agent.channels == []
        assert agent.mcp_servers == []
        assert agent.workspace is None
        assert agent.resources == []
        assert agent.secrets == []
        assert agent.platform is None

    def test_full_agent(self, sonnet):
        docker_provider = Provider(name="docker", type="docker")
        aws_provider = Provider(name="aws", type="aws")

        agent = Agent(
            name="support-bot",
            model=sonnet,
            skills=[
                Skill(name="refund-handling", tools=["lookup_order", "process_refund"]),
                Skill(name="order-tracking", tools=["get_order_status"]),
            ],
            channels=[
                Channel(name="api", type=ChannelType.API),
                Channel(name="slack", type=ChannelType.SLACK, config={"channel": "#support"}),
            ],
            mcp_servers=[
                McpServer(name="github", transport=McpTransport.STDIO, command="github-mcp"),
            ],
            workspace=Workspace(name="sandbox", type=WorkspaceType.SANDBOX, filesystem=True),
            guardrails={"max_response_length": 2000},
            resources=[
                SessionStore(name="sessions", provider=aws_provider, engine="redis"),
            ],
            secrets=[
                Secret(name="ANTHROPIC_API_KEY"),
            ],
            platform=Platform(name="local", type="docker", provider=docker_provider),
        )
        assert len(agent.skills) == 2
        assert len(agent.channels) == 2
        assert len(agent.mcp_servers) == 1
        assert agent.workspace.filesystem is True
        assert len(agent.resources) == 1
        assert len(agent.secrets) == 1
        assert agent.platform.type == "docker"

    def test_model_required(self):
        with pytest.raises(ValidationError):
            Agent(name="bot")

    def test_serialization_roundtrip(self, sonnet):
        agent = Agent(
            name="bot",
            model=sonnet,
            skills=[Skill(name="greeting", tools=["say_hello"])],
            channels=[Channel(name="api", type=ChannelType.API)],
        )
        data = agent.model_dump()
        restored = Agent.model_validate(data)
        assert restored == agent


class TestAgentServices:
    def test_sessions_field(self, sonnet):
        docker = Provider(name="docker", type="docker")
        agent = Agent(
            name="bot",
            model=sonnet,
            sessions=Postgres(provider=docker),
        )
        assert agent.sessions is not None
        assert agent.sessions.engine == "postgres"
        assert agent.sessions.name == "sessions"

    def test_memory_field(self, sonnet):
        docker = Provider(name="docker", type="docker")
        agent = Agent(
            name="bot",
            model=sonnet,
            memory=Postgres(provider=docker),
        )
        assert agent.memory is not None
        assert agent.memory.name == "memory"

    def test_services_list(self, sonnet):
        docker = Provider(name="docker", type="docker")
        agent = Agent(
            name="bot",
            model=sonnet,
            services=[Redis(name="cache", provider=docker)],
        )
        assert len(agent.services) == 1
        assert agent.services[0].engine == "redis"

    def test_defaults_none(self, sonnet):
        agent = Agent(name="bot", model=sonnet)
        assert agent.sessions is None
        assert agent.memory is None
        assert agent.services == []

    def test_auto_name_sessions(self, sonnet):
        docker = Provider(name="docker", type="docker")
        agent = Agent(name="bot", model=sonnet, sessions=Postgres(provider=docker))
        assert agent.sessions.name == "sessions"

    def test_auto_name_memory(self, sonnet):
        docker = Provider(name="docker", type="docker")
        agent = Agent(name="bot", model=sonnet, memory=Postgres(provider=docker))
        assert agent.memory.name == "memory"

    def test_explicit_name_preserved(self, sonnet):
        docker = Provider(name="docker", type="docker")
        agent = Agent(name="bot", model=sonnet, sessions=Postgres(name="my-db", provider=docker))
        assert agent.sessions.name == "my-db"

    def test_bring_your_own_sessions(self, sonnet):
        agent = Agent(
            name="bot",
            model=sonnet,
            sessions=Postgres(connection_string_env="DATABASE_URL"),
        )
        assert agent.sessions.is_managed is False

    def test_full_agent_with_services(self, sonnet):
        docker = Provider(name="docker", type="docker")
        agent = Agent(
            name="support-bot",
            model=sonnet,
            platform=Platform(name="local", type="docker", provider=docker),
            sessions=Postgres(provider=docker),
            memory=Postgres(provider=docker),
            services=[Redis(name="cache", provider=docker)],
            channels=[Channel(name="api", type=ChannelType.API)],
        )
        assert agent.sessions.engine == "postgres"
        assert agent.memory.engine == "postgres"
        assert len(agent.services) == 1

    def test_serialization_roundtrip_with_services(self, sonnet):
        docker = Provider(name="docker", type="docker")
        agent = Agent(
            name="bot",
            model=sonnet,
            sessions=Sqlite(provider=docker),
        )
        data = agent.model_dump()
        restored = Agent.model_validate(data)
        assert restored.sessions is not None
        assert restored.sessions.name == "sessions"
