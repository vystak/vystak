"""attach_mcp_servers — normalize agent.mcp_servers and wire the adapter.

Uses real McpServer schema objects (the wrapper delegates shape handling to
vystak.mcp.config.normalize) and a fake MultiServerMCPClient patched onto
the module.
"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from _vystak.runtime.mcp import attach_mcp_servers
from vystak.schema.common import McpTransport
from vystak.schema.mcp import McpServer


def _agent(mcps):
    return SimpleNamespace(mcp_servers=mcps)


def _fake_client(captured, tools):
    class FakeClient:
        def __init__(self, config):
            captured["config"] = config

        async def get_tools(self):
            return tools

    return FakeClient


@pytest.mark.asyncio
async def test_no_mcp_returns_empty_tool_list():
    tools = await attach_mcp_servers(_agent([]))
    assert tools == []


@pytest.mark.asyncio
async def test_stdio_forwards_command_args_env():
    captured = {}
    fake = _fake_client(captured, ["tool1"])
    with patch("_vystak.runtime.mcp.MultiServerMCPClient", fake, create=True):
        mcps = [
            McpServer(
                name="files",
                command="mcp-fs",
                args=["/tmp"],
                env={"LOG_LEVEL": "debug"},
            )
        ]
        tools = await attach_mcp_servers(_agent(mcps))
    assert tools == ["tool1"]
    assert captured["config"]["files"] == {
        "transport": "stdio",
        "command": "mcp-fs",
        "args": ["/tmp"],
        "env": {"LOG_LEVEL": "debug"},
    }


@pytest.mark.asyncio
async def test_remote_inferred_streamable_http_forwards_url_headers():
    captured = {}
    fake = _fake_client(captured, [])
    with patch("_vystak.runtime.mcp.MultiServerMCPClient", fake, create=True):
        mcps = [
            McpServer(
                name="api",
                url="https://mcp.example.com/mcp",
                headers={"X-Api-Version": "1"},
            )
        ]
        await attach_mcp_servers(_agent(mcps))
    assert captured["config"]["api"] == {
        "transport": "streamable_http",
        "url": "https://mcp.example.com/mcp",
        "headers": {"X-Api-Version": "1"},
    }


@pytest.mark.asyncio
async def test_remote_explicit_sse_honored():
    captured = {}
    fake = _fake_client(captured, [])
    with patch("_vystak.runtime.mcp.MultiServerMCPClient", fake, create=True):
        mcps = [
            McpServer(
                name="events",
                transport=McpTransport.SSE,
                url="https://mcp.example.com/sse",
            )
        ]
        await attach_mcp_servers(_agent(mcps))
    assert captured["config"]["events"]["transport"] == "sse"


@pytest.mark.asyncio
async def test_secret_refs_resolved_from_container_env(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "abc")
    captured = {}
    fake = _fake_client(captured, [])
    with patch("_vystak.runtime.mcp.MultiServerMCPClient", fake, create=True):
        mcps = [
            McpServer(
                name="gh",
                url="https://api.example.com/mcp",
                headers={"Authorization": "Bearer ${secret.GITHUB_TOKEN}"},
            )
        ]
        await attach_mcp_servers(_agent(mcps))
    assert captured["config"]["gh"]["headers"] == {"Authorization": "Bearer abc"}


def test_app_startup_attaches_mcp_tools():
    """build_agent_app must call attach_mcp_servers during lifespan and
    include the returned tools in the graph."""
    from _vystak.runtime.app_factory import build_agent_app
    from fastapi.testclient import TestClient
    from langchain_core.tools import tool
    from vystak.schema.agent import Agent
    from vystak.schema.model import Model
    from vystak.schema.provider import Provider

    @tool
    def fake_mcp_tool(query: str) -> str:
        """A fake MCP-provided tool."""
        return "ok"

    captured = {}
    fake = _fake_client(captured, [fake_mcp_tool])

    agent = Agent(
        name="mcp-bot",
        framework="langchain-python",
        default_model=Model(
            name="m",
            provider=Provider(name="anthropic", type="anthropic"),
            model_name="claude-sonnet-4-6",
        ),
        mcp_servers=[McpServer(name="files", command="fake-mcp")],
    )

    with patch("_vystak.runtime.mcp.MultiServerMCPClient", fake, create=True):
        app = build_agent_app(agent)
        with TestClient(app):
            pass

    assert "files" in captured["config"]
    assert app.state.mcp_tools == [fake_mcp_tool]
