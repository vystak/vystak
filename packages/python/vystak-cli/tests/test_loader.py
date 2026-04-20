import pytest
import yaml
from vystak_cli.loader import (
    Definitions,
    find_agent_file,
    load_agent_from_file,
    load_definitions,
)


@pytest.fixture()
def sample_agent_yaml():
    return {
        "name": "test-bot",
        "model": {
            "name": "claude",
            "provider": {"name": "anthropic", "type": "anthropic"},
            "model_name": "claude-sonnet-4-20250514",
        },
    }


class TestFindAgentFile:
    def test_find_yaml(self, tmp_path, sample_agent_yaml):
        path = tmp_path / "vystak.yaml"
        path.write_text(yaml.dump(sample_agent_yaml))
        result = find_agent_file(search_dir=tmp_path)
        assert result == path

    def test_find_yml(self, tmp_path, sample_agent_yaml):
        path = tmp_path / "vystak.yml"
        path.write_text(yaml.dump(sample_agent_yaml))
        result = find_agent_file(search_dir=tmp_path)
        assert result == path

    def test_find_py(self, tmp_path):
        path = tmp_path / "vystak.py"
        path.write_text("agent = 'placeholder'")
        result = find_agent_file(search_dir=tmp_path)
        assert result == path

    def test_yaml_preferred_over_py(self, tmp_path, sample_agent_yaml):
        (tmp_path / "vystak.yaml").write_text(yaml.dump(sample_agent_yaml))
        (tmp_path / "vystak.py").write_text("agent = 'placeholder'")
        result = find_agent_file(search_dir=tmp_path)
        assert result.name == "vystak.yaml"

    def test_file_override(self, tmp_path, sample_agent_yaml):
        custom = tmp_path / "custom.yaml"
        custom.write_text(yaml.dump(sample_agent_yaml))
        result = find_agent_file(file=str(custom))
        assert result == custom

    def test_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            find_agent_file(search_dir=tmp_path)

    def test_override_not_found(self):
        with pytest.raises(FileNotFoundError):
            find_agent_file(file="/nonexistent/file.yaml")


class TestLoadAgentFromFile:
    def test_load_yaml(self, tmp_path, sample_agent_yaml):
        path = tmp_path / "agent.yaml"
        path.write_text(yaml.dump(sample_agent_yaml))
        agent = load_agent_from_file(path)
        assert agent.name == "test-bot"
        assert agent.model.model_name == "claude-sonnet-4-20250514"

    def test_load_py(self, tmp_path):
        path = tmp_path / "vystak.py"
        path.write_text("""\
from vystak.schema.agent import Agent
from vystak.schema.model import Model
from vystak.schema.provider import Provider

anthropic = Provider(name="anthropic", type="anthropic")
model = Model(name="claude", provider=anthropic, model_name="claude-sonnet-4-20250514")
agent = Agent(name="py-bot", model=model)
""")
        agent = load_agent_from_file(path)
        assert agent.name == "py-bot"

    def test_load_py_missing_agent_var(self, tmp_path):
        path = tmp_path / "bad.py"
        path.write_text("x = 1")
        with pytest.raises(ValueError, match="agent"):
            load_agent_from_file(path)


class TestLoadDefinitions:
    def test_single_agent_yaml(self, tmp_path, sample_agent_yaml):
        path = tmp_path / "agent.yaml"
        path.write_text(yaml.dump(sample_agent_yaml))
        defs = load_definitions([path])
        assert isinstance(defs, Definitions)
        assert len(defs.agents) == 1
        assert defs.agents[0].name == "test-bot"
        assert defs.channels == []

    def test_multi_agent_yaml(self, tmp_path):
        data = {
            "providers": {"anthropic": {"type": "anthropic"}},
            "platforms": {},
            "models": {
                "claude": {"provider": "anthropic", "model_name": "claude-sonnet-4-20250514"}
            },
            "agents": [
                {"name": "a", "model": "claude"},
                {"name": "b", "model": "claude"},
            ],
        }
        path = tmp_path / "vystak.yaml"
        path.write_text(yaml.dump(data))
        defs = load_definitions([path])
        assert len(defs.agents) == 2

    def test_multi_yaml_with_channels(self, tmp_path):
        data = {
            "providers": {
                "anthropic": {"type": "anthropic"},
                "docker": {"type": "docker"},
            },
            "platforms": {
                "local": {"type": "docker", "provider": "docker", "namespace": "dev"},
            },
            "models": {
                "claude": {"provider": "anthropic", "model_name": "claude-sonnet-4-20250514"},
            },
            "agents": [
                {"name": "bot", "model": "claude", "platform": "local"},
            ],
            "channels": [
                {
                    "name": "slack",
                    "type": "slack",
                    "platform": "local",
                    "routes": [{"match": {}, "agent": "bot"}],
                },
            ],
        }
        path = tmp_path / "vystak.yaml"
        path.write_text(yaml.dump(data))
        defs = load_definitions([path])
        assert len(defs.agents) == 1
        assert len(defs.channels) == 1
        assert defs.channels[0].canonical_name == "slack.channels.dev"
        assert defs.channels[0].platform is defs.agents[0].platform

    def test_python_multi_agent(self, tmp_path):
        path = tmp_path / "vystak.py"
        path.write_text(
            "from vystak.schema.agent import Agent\n"
            "from vystak.schema.model import Model\n"
            "from vystak.schema.provider import Provider\n"
            "anthropic = Provider(name='anthropic', type='anthropic')\n"
            "model = Model(name='claude', provider=anthropic, "
            "model_name='claude-sonnet-4-20250514')\n"
            "bot_a = Agent(name='bot-a', model=model)\n"
            "bot_b = Agent(name='bot-b', model=model)\n"
        )
        defs = load_definitions([path])
        assert len(defs.agents) == 2
        names = {a.name for a in defs.agents}
        assert names == {"bot-a", "bot-b"}

    def test_python_with_channel(self, tmp_path):
        path = tmp_path / "vystak.py"
        path.write_text(
            "from vystak.schema.agent import Agent\n"
            "from vystak.schema.channel import Channel\n"
            "from vystak.schema.common import ChannelType\n"
            "from vystak.schema.model import Model\n"
            "from vystak.schema.platform import Platform\n"
            "from vystak.schema.provider import Provider\n"
            "docker = Provider(name='docker', type='docker')\n"
            "anthropic = Provider(name='anthropic', type='anthropic')\n"
            "platform = Platform(name='local', type='docker', provider=docker)\n"
            "model = Model(name='claude', provider=anthropic, "
            "model_name='claude-sonnet-4-20250514')\n"
            "bot = Agent(name='bot', model=model, platform=platform)\n"
            "api = Channel(name='api', type=ChannelType.API, platform=platform)\n"
        )
        defs = load_definitions([path])
        assert len(defs.agents) == 1
        assert len(defs.channels) == 1
        assert defs.channels[0].name == "api"

    def test_multiple_yaml_files(self, tmp_path):
        for name in ("a", "b"):
            data = {
                "name": f"bot-{name}",
                "model": {
                    "name": "claude",
                    "provider": {"name": "anthropic", "type": "anthropic"},
                    "model_name": "claude-sonnet-4-20250514",
                },
            }
            (tmp_path / f"{name}.yaml").write_text(yaml.dump(data))
        defs = load_definitions([tmp_path / "a.yaml", tmp_path / "b.yaml"])
        assert len(defs.agents) == 2

    def test_directory_path(self, tmp_path):
        subdir = tmp_path / "weather"
        subdir.mkdir()
        data = {
            "name": "weather-bot",
            "model": {
                "name": "claude",
                "provider": {"name": "anthropic", "type": "anthropic"},
                "model_name": "claude-sonnet-4-20250514",
            },
        }
        (subdir / "vystak.yaml").write_text(yaml.dump(data))
        defs = load_definitions([subdir])
        assert len(defs.agents) == 1
        assert defs.agents[0].name == "weather-bot"

    def test_base_config_merged(self, tmp_path):
        base = {
            "providers": {
                "azure": {"type": "azure", "config": {"location": "eastus2"}},
                "anthropic": {"type": "anthropic"},
            },
            "platforms": {"aca": {"type": "container-apps", "provider": "azure"}},
            "models": {
                "claude": {"provider": "anthropic", "model_name": "claude-sonnet-4-20250514"}
            },
        }
        (tmp_path / "vystak.base.yaml").write_text(yaml.dump(base))

        subdir = tmp_path / "bot"
        subdir.mkdir()
        agent_data = {
            "name": "bot",
            "model": "claude",
            "platform": "aca",
        }
        (subdir / "vystak.yaml").write_text(yaml.dump(agent_data))

        defs = load_definitions([subdir], base_dir=tmp_path)
        assert len(defs.agents) == 1
        assert defs.agents[0].platform.provider.config["location"] == "eastus2"
