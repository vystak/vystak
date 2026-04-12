import ast as python_ast
from pathlib import Path

import pytest

from agentstack.schema.agent import Agent
from agentstack.schema.model import Model
from agentstack.schema.provider import Provider
from agentstack.schema.skill import Skill

from agentstack_adapter_langchain.tools import (
    discover_tools,
    generate_tools_init,
    get_tool_requirements,
    read_tool_file,
)


@pytest.fixture()
def agent_with_tools():
    return Agent(
        name="test-bot",
        model=Model(
            name="claude",
            provider=Provider(name="anthropic", type="anthropic"),
            model_name="claude-sonnet-4-20250514",
        ),
        skills=[
            Skill(name="weather", tools=["get_weather", "get_forecast"]),
            Skill(name="time", tools=["get_time"]),
        ],
    )


@pytest.fixture()
def tools_dir(tmp_path):
    tools = tmp_path / "tools"
    tools.mkdir()
    (tools / "get_weather.py").write_text(
        'import requests\n\ndef get_weather(city: str) -> str:\n'
        '    """Get current weather for a city."""\n'
        '    return f"Weather in {city}: sunny"\n'
    )
    (tools / "get_time.py").write_text(
        'from datetime import datetime\n\ndef get_time(timezone: str) -> str:\n'
        '    """Get current time in a timezone."""\n'
        '    return datetime.now().isoformat()\n'
    )
    return tools


class TestDiscoverTools:
    def test_all_found(self, agent_with_tools, tools_dir):
        found, missing = discover_tools(agent_with_tools, tools_dir.parent)
        assert "get_weather" in found
        assert "get_time" in found
        assert "get_forecast" in missing

    def test_none_found(self, agent_with_tools, tmp_path):
        found, missing = discover_tools(agent_with_tools, tmp_path)
        assert found == {}
        assert set(missing) == {"get_weather", "get_forecast", "get_time"}

    def test_mixed(self, agent_with_tools, tools_dir):
        found, missing = discover_tools(agent_with_tools, tools_dir.parent)
        assert len(found) == 2
        assert missing == ["get_forecast"]

    def test_no_tools_in_agent(self, tmp_path):
        agent = Agent(
            name="bot",
            model=Model(name="claude", provider=Provider(name="anthropic", type="anthropic"), model_name="claude-sonnet-4-20250514"),
        )
        found, missing = discover_tools(agent, tmp_path)
        assert found == {}
        assert missing == []


class TestReadToolFile:
    def test_valid_file(self, tools_dir):
        content = read_tool_file(tools_dir / "get_weather.py", "get_weather")
        assert "def get_weather(" in content

    def test_missing_function(self, tools_dir):
        (tools_dir / "bad_tool.py").write_text('def something_else():\n    pass\n')
        with pytest.raises(ValueError, match="get_weather"):
            read_tool_file(tools_dir / "bad_tool.py", "get_weather")

    def test_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            read_tool_file(tmp_path / "nonexistent.py", "nonexistent")


class TestGenerateToolsInit:
    def test_basic(self):
        code = generate_tools_init(["get_weather", "get_time"])
        assert "from tools.get_weather import get_weather" in code
        assert "get_weather = tool(get_weather)" in code
        assert "from langchain_core.tools import tool" in code

    def test_parseable(self):
        code = generate_tools_init(["get_weather", "get_time"])
        python_ast.parse(code)

    def test_empty(self):
        code = generate_tools_init([])
        python_ast.parse(code)


class TestGetToolRequirements:
    def test_exists(self, tools_dir):
        (tools_dir / "requirements.txt").write_text("requests\nbeautifulsoup4\n")
        reqs = get_tool_requirements(tools_dir.parent)
        assert "requests" in reqs

    def test_missing(self, tmp_path):
        assert get_tool_requirements(tmp_path) is None
