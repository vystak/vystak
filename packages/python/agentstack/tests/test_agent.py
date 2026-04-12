import pytest
from pydantic import ValidationError

from agentstack.schema.agent import Agent
from agentstack.schema.channel import Channel
from agentstack.schema.common import ChannelType, McpTransport, WorkspaceType
from agentstack.schema.mcp import McpServer
from agentstack.schema.model import Model
from agentstack.schema.platform import Platform
from agentstack.schema.provider import Provider
from agentstack.schema.resource import SessionStore
from agentstack.schema.secret import Secret
from agentstack.schema.skill import Skill
from agentstack.schema.workspace import Workspace


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
