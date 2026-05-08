"""attach_mcp_servers — wire langchain-mcp-adapters from agent.mcp_servers."""

from unittest.mock import patch

import pytest
from _vystak.runtime.mcp import attach_mcp_servers


class _Mcp:
    def __init__(self, name, command=None, args=None, transport="stdio", url=None):
        self.name = name
        self.command = command
        self.args = args or []
        self.transport = transport
        self.url = url


def _agent(mcps):
    class _A:
        mcp_servers = mcps
    return _A()


@pytest.mark.asyncio
async def test_no_mcp_returns_empty_tool_list():
    tools = await attach_mcp_servers(_agent([]))
    assert tools == []


@pytest.mark.asyncio
async def test_mcp_servers_invoke_adapter_with_correct_config():
    captured = {}

    class FakeClient:
        def __init__(self, config):
            captured["config"] = config

        async def get_tools(self):
            return ["tool1", "tool2"]

    with patch("_vystak.runtime.mcp.MultiServerMCPClient", FakeClient, create=True):
        mcps = [_Mcp(name="files", command="mcp-fs", args=["/tmp"], transport="stdio")]
        tools = await attach_mcp_servers(_agent(mcps))
        assert tools == ["tool1", "tool2"]
        assert "files" in captured["config"]
        assert captured["config"]["files"]["command"] == "mcp-fs"
