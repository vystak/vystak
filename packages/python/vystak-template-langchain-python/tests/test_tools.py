"""load_user_tools — import @tool functions from tools/<name>.py."""

from _vystak.runtime.tools import load_user_tools


def _agent_with_tool_names(names):
    from vystak.schema.skill import Skill

    class _A:
        skills = [Skill(name="s1", tools=names)]
    return _A()


def test_load_returns_empty_when_no_tools_dir(tmp_path):
    agent = _agent_with_tool_names([])
    tools = load_user_tools(agent, tmp_path / "missing")
    assert tools == []


def test_load_imports_tool_function(tmp_path):
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir()
    (tools_dir / "__init__.py").write_text("")
    (tools_dir / "weather.py").write_text(
        "from langchain_core.tools import tool\n"
        "@tool\n"
        "def weather(city: str) -> str:\n"
        "    '''Get the weather.'''\n"
        "    return f'sunny in {city}'\n"
    )
    agent = _agent_with_tool_names(["weather"])
    tools = load_user_tools(agent, tools_dir)
    assert len(tools) == 1
    assert tools[0].name == "weather"


def test_load_skips_tools_not_in_skills(tmp_path):
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir()
    (tools_dir / "__init__.py").write_text("")
    (tools_dir / "unused.py").write_text(
        "from langchain_core.tools import tool\n"
        "@tool\n"
        "def unused() -> str:\n"
        "    '''.'''\n"
        "    return 'x'\n"
    )
    agent = _agent_with_tool_names(["other"])
    tools = load_user_tools(agent, tools_dir)
    assert tools == []
