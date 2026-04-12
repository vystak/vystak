import json
from pathlib import Path

import pytest
import yaml

from agentstack.schema.agent import Agent
from agentstack.schema.channel import Channel
from agentstack.schema.common import ChannelType
from agentstack.schema.loader import dump_agent, load_agent
from agentstack.schema.model import Model
from agentstack.schema.provider import Provider
from agentstack.schema.skill import Skill


@pytest.fixture()
def sample_agent_dict():
    return {
        "name": "test-bot",
        "model": {
            "name": "claude",
            "provider": {"name": "anthropic", "type": "anthropic"},
            "model_name": "claude-sonnet-4-20250514",
        },
        "skills": [{"name": "greeting", "tools": ["say_hello"]}],
        "channels": [{"name": "api", "type": "api"}],
    }


class TestLoadAgent:
    def test_load_yaml(self, tmp_path, sample_agent_dict):
        path = tmp_path / "agent.yaml"
        path.write_text(yaml.dump(sample_agent_dict))
        agent = load_agent(path)
        assert agent.name == "test-bot"
        assert agent.model.model_name == "claude-sonnet-4-20250514"
        assert len(agent.skills) == 1
        assert agent.channels[0].type == ChannelType.API

    def test_load_json(self, tmp_path, sample_agent_dict):
        path = tmp_path / "agent.json"
        path.write_text(json.dumps(sample_agent_dict))
        agent = load_agent(path)
        assert agent.name == "test-bot"

    def test_load_yml_extension(self, tmp_path, sample_agent_dict):
        path = tmp_path / "agent.yml"
        path.write_text(yaml.dump(sample_agent_dict))
        agent = load_agent(path)
        assert agent.name == "test-bot"

    def test_load_nonexistent_file(self):
        with pytest.raises(FileNotFoundError):
            load_agent("/nonexistent/path.yaml")

    def test_load_unsupported_extension(self, tmp_path):
        path = tmp_path / "agent.toml"
        path.write_text("")
        with pytest.raises(ValueError, match="Unsupported file format"):
            load_agent(path)


class TestDumpAgent:
    def test_dump_yaml(self, tmp_path):
        anthropic = Provider(name="anthropic", type="anthropic")
        model = Model(name="claude", provider=anthropic, model_name="claude-sonnet-4-20250514")
        agent = Agent(name="test-bot", model=model)
        path = tmp_path / "agent.yaml"
        dump_agent(agent, path)
        loaded = yaml.safe_load(path.read_text())
        assert loaded["name"] == "test-bot"

    def test_dump_json(self, tmp_path):
        anthropic = Provider(name="anthropic", type="anthropic")
        model = Model(name="claude", provider=anthropic, model_name="claude-sonnet-4-20250514")
        agent = Agent(name="test-bot", model=model)
        path = tmp_path / "agent.json"
        dump_agent(agent, path, format="json")
        loaded = json.loads(path.read_text())
        assert loaded["name"] == "test-bot"

    def test_roundtrip_yaml(self, tmp_path):
        anthropic = Provider(name="anthropic", type="anthropic")
        model = Model(name="claude", provider=anthropic, model_name="claude-sonnet-4-20250514")
        agent = Agent(
            name="test-bot",
            model=model,
            skills=[Skill(name="greeting", tools=["say_hello"])],
            channels=[Channel(name="api", type=ChannelType.API)],
        )
        path = tmp_path / "agent.yaml"
        dump_agent(agent, path)
        restored = load_agent(path)
        assert restored == agent
