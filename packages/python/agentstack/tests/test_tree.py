from agentstack.hash.tree import AgentHashTree, hash_agent
from agentstack.schema.agent import Agent
from agentstack.schema.channel import Channel
from agentstack.schema.common import ChannelType, McpTransport, WorkspaceType
from agentstack.schema.mcp import McpServer
from agentstack.schema.model import Model
from agentstack.schema.provider import Provider
from agentstack.schema.secret import Secret
from agentstack.schema.service import Postgres, Redis
from agentstack.schema.skill import Skill
from agentstack.schema.workspace import Workspace


def make_agent(**overrides):
    anthropic = Provider(name="anthropic", type="anthropic")
    model = Model(name="claude", provider=anthropic, model_name="claude-sonnet-4-20250514")
    defaults = {"name": "bot", "model": model}
    defaults.update(overrides)
    return Agent(**defaults)


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
        assert tree.channels
        assert tree.workspace
        assert tree.resources
        assert tree.secrets
        assert tree.root

    def test_model_change_changes_brain_and_root(self):
        agent1 = make_agent()
        anthropic = Provider(name="anthropic", type="anthropic")
        different_model = Model(name="opus", provider=anthropic, model_name="claude-opus-4-20250514")
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

    def test_channel_change_detected(self):
        agent1 = make_agent(channels=[Channel(name="api", type=ChannelType.API)])
        agent2 = make_agent(channels=[Channel(name="slack", type=ChannelType.SLACK)])
        tree1 = hash_agent(agent1)
        tree2 = hash_agent(agent2)
        assert tree1.channels != tree2.channels

    def test_mcp_change_detected(self):
        agent1 = make_agent()
        agent2 = make_agent(mcp_servers=[McpServer(name="fs", transport=McpTransport.STDIO, command="fs-mcp")])
        tree1 = hash_agent(agent1)
        tree2 = hash_agent(agent2)
        assert tree1.mcp_servers != tree2.mcp_servers

    def test_workspace_change_detected(self):
        agent1 = make_agent()
        agent2 = make_agent(workspace=Workspace(name="sandbox", type=WorkspaceType.SANDBOX, filesystem=True))
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
