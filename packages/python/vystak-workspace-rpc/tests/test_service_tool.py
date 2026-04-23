"""Tests for tool.* service — user-defined tools discovery + invocation."""

import pytest
from vystak_workspace_rpc.services.tool import register_tool


def _build_server(tools_dir):
    from vystak_workspace_rpc.server import JsonRpcServer

    srv = JsonRpcServer()
    register_tool(srv, tools_dir)
    return srv


@pytest.mark.asyncio
async def test_tool_invoke_simple(tmp_path):
    tools = tmp_path / "tools"
    tools.mkdir()
    (tools / "greet.py").write_text(
        "def greet(name: str) -> str:\n    return f'hello {name}'\n"
    )
    srv = _build_server(tools)
    result = await srv._handlers["tool.invoke"]({
        "name": "greet", "args": {"name": "world"}
    })
    assert result == "hello world"


@pytest.mark.asyncio
async def test_tool_invoke_returns_dict(tmp_path):
    tools = tmp_path / "tools"
    tools.mkdir()
    (tools / "calc.py").write_text(
        "def calc(x: int, y: int) -> dict:\n    return {'sum': x+y, 'prod': x*y}\n"
    )
    srv = _build_server(tools)
    result = await srv._handlers["tool.invoke"]({
        "name": "calc", "args": {"x": 3, "y": 4}
    })
    assert result == {"sum": 7, "prod": 12}


@pytest.mark.asyncio
async def test_tool_invoke_unknown_raises(tmp_path):
    tools = tmp_path / "tools"
    tools.mkdir()
    srv = _build_server(tools)
    with pytest.raises(FileNotFoundError, match="nope.py"):
        await srv._handlers["tool.invoke"]({"name": "nope", "args": {}})


@pytest.mark.asyncio
async def test_tool_list(tmp_path):
    tools = tmp_path / "tools"
    tools.mkdir()
    (tools / "a.py").write_text("def a(): return 1\n")
    (tools / "b.py").write_text("def b(): return 2\n")
    (tools / "__init__.py").write_text("")  # should not appear in list
    srv = _build_server(tools)
    result = await srv._handlers["tool.list"]({})
    names = {t["name"] for t in result}
    assert names == {"a", "b"}


@pytest.mark.asyncio
async def test_tool_invoke_tool_raising_propagates(tmp_path):
    tools = tmp_path / "tools"
    tools.mkdir()
    (tools / "oops.py").write_text(
        "def oops():\n    raise ValueError('user-error')\n"
    )
    srv = _build_server(tools)
    with pytest.raises(ValueError, match="user-error"):
        await srv._handlers["tool.invoke"]({"name": "oops", "args": {}})
