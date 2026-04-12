import pytest
import yaml

from agentstack_cli.loader import find_agent_file, load_agent_from_file


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
        path = tmp_path / "agentstack.yaml"
        path.write_text(yaml.dump(sample_agent_yaml))
        result = find_agent_file(search_dir=tmp_path)
        assert result == path

    def test_find_yml(self, tmp_path, sample_agent_yaml):
        path = tmp_path / "agentstack.yml"
        path.write_text(yaml.dump(sample_agent_yaml))
        result = find_agent_file(search_dir=tmp_path)
        assert result == path

    def test_find_py(self, tmp_path):
        path = tmp_path / "agentstack.py"
        path.write_text("agent = 'placeholder'")
        result = find_agent_file(search_dir=tmp_path)
        assert result == path

    def test_yaml_preferred_over_py(self, tmp_path, sample_agent_yaml):
        (tmp_path / "agentstack.yaml").write_text(yaml.dump(sample_agent_yaml))
        (tmp_path / "agentstack.py").write_text("agent = 'placeholder'")
        result = find_agent_file(search_dir=tmp_path)
        assert result.name == "agentstack.yaml"

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
        path = tmp_path / "agentstack.py"
        path.write_text("""\
from agentstack.schema.agent import Agent
from agentstack.schema.model import Model
from agentstack.schema.provider import Provider

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
