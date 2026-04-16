import json

import pytest
import yaml
from vystak.schema.agent import Agent
from vystak.schema.channel import Channel
from vystak.schema.common import ChannelType
from vystak.schema.loader import dump_agent, load_agent
from vystak.schema.model import Model
from vystak.schema.provider import Provider
from vystak.schema.service import Postgres, Redis, Sqlite
from vystak.schema.skill import Skill


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


class TestLoadAgentWithServices:
    def test_load_sessions_postgres(self, tmp_path):
        data = {
            "name": "bot",
            "model": {
                "name": "claude",
                "provider": {"name": "anthropic", "type": "anthropic"},
                "model_name": "claude-sonnet-4-20250514",
            },
            "sessions": {
                "type": "postgres",
                "provider": {"name": "docker", "type": "docker"},
            },
        }
        path = tmp_path / "agent.yaml"
        path.write_text(yaml.dump(data))
        agent = load_agent(path)
        assert agent.sessions is not None
        assert isinstance(agent.sessions, Postgres)
        assert agent.sessions.engine == "postgres"
        assert agent.sessions.name == "sessions"

    def test_load_sessions_sqlite(self, tmp_path):
        data = {
            "name": "bot",
            "model": {
                "name": "claude",
                "provider": {"name": "anthropic", "type": "anthropic"},
                "model_name": "claude-sonnet-4-20250514",
            },
            "sessions": {
                "type": "sqlite",
                "provider": {"name": "docker", "type": "docker"},
            },
        }
        path = tmp_path / "agent.yaml"
        path.write_text(yaml.dump(data))
        agent = load_agent(path)
        assert isinstance(agent.sessions, Sqlite)

    def test_load_bring_your_own(self, tmp_path):
        data = {
            "name": "bot",
            "model": {
                "name": "claude",
                "provider": {"name": "anthropic", "type": "anthropic"},
                "model_name": "claude-sonnet-4-20250514",
            },
            "sessions": {
                "type": "postgres",
                "connection_string_env": "DATABASE_URL",
            },
        }
        path = tmp_path / "agent.yaml"
        path.write_text(yaml.dump(data))
        agent = load_agent(path)
        assert agent.sessions is not None
        assert agent.sessions.is_managed is False
        assert agent.sessions.connection_string_env == "DATABASE_URL"

    def test_load_services_list(self, tmp_path):
        data = {
            "name": "bot",
            "model": {
                "name": "claude",
                "provider": {"name": "anthropic", "type": "anthropic"},
                "model_name": "claude-sonnet-4-20250514",
            },
            "services": [
                {
                    "name": "cache",
                    "type": "redis",
                    "provider": {"name": "docker", "type": "docker"},
                },
            ],
        }
        path = tmp_path / "agent.yaml"
        path.write_text(yaml.dump(data))
        agent = load_agent(path)
        assert len(agent.services) == 1
        assert isinstance(agent.services[0], Redis)

    def test_load_old_format_still_works(self, tmp_path):
        data = {
            "name": "bot",
            "model": {
                "name": "claude",
                "provider": {"name": "anthropic", "type": "anthropic"},
                "model_name": "claude-sonnet-4-20250514",
            },
            "resources": [
                {
                    "name": "sessions",
                    "provider": {"name": "docker", "type": "docker"},
                    "engine": "postgres",
                },
            ],
        }
        path = tmp_path / "agent.yaml"
        path.write_text(yaml.dump(data))
        agent = load_agent(path)
        assert len(agent.resources) == 1
        assert agent.resources[0].engine == "postgres"

    def test_roundtrip_with_sessions(self, tmp_path):
        anthropic = Provider(name="anthropic", type="anthropic")
        model = Model(name="claude", provider=anthropic, model_name="claude-sonnet-4-20250514")
        docker = Provider(name="docker", type="docker")
        agent = Agent(
            name="bot",
            model=model,
            sessions=Postgres(provider=docker),
        )
        path = tmp_path / "agent.yaml"
        dump_agent(agent, path)
        restored = load_agent(path)
        assert restored.sessions is not None
        assert restored.sessions.engine == "postgres"
        assert restored.sessions.name == "sessions"
