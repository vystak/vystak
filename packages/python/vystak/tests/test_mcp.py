import pytest
from pydantic import ValidationError
from vystak.schema.common import McpTransport
from vystak.schema.mcp import McpServer


class TestMcpServer:
    def test_stdio(self):
        mcp = McpServer(
            name="filesystem",
            transport=McpTransport.STDIO,
            command="npx",
            args=["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
        )
        assert mcp.transport == McpTransport.STDIO
        assert mcp.command == "npx"
        assert len(mcp.args) == 3

    def test_sse(self):
        mcp = McpServer(
            name="remote", transport=McpTransport.SSE, url="https://mcp.example.com/sse"
        )
        assert mcp.transport == McpTransport.SSE
        assert mcp.url == "https://mcp.example.com/sse"

    def test_streamable_http(self):
        mcp = McpServer(
            name="api",
            transport=McpTransport.STREAMABLE_HTTP,
            url="https://mcp.example.com/mcp",
            headers={"Authorization": "Bearer token"},
        )
        assert mcp.transport == McpTransport.STREAMABLE_HTTP

    def test_with_env(self):
        mcp = McpServer(
            name="github",
            transport=McpTransport.STDIO,
            command="github-mcp",
            env={"GITHUB_TOKEN": "secret"},
        )
        assert mcp.env["GITHUB_TOKEN"] == "secret"

    def test_transport_required(self):
        with pytest.raises(ValidationError):
            McpServer(name="test")

    def test_serialization_roundtrip(self):
        mcp = McpServer(name="test", transport=McpTransport.STDIO, command="test-mcp")
        data = mcp.model_dump()
        restored = McpServer.model_validate(data)
        assert restored == mcp
