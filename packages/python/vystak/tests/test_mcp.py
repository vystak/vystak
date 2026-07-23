import pytest
from pydantic import ValidationError
from vystak.schema.common import McpTransport
from vystak.schema.mcp import McpServer


class TestMcpServerShapes:
    def test_stdio(self):
        mcp = McpServer(
            name="filesystem",
            command="npx",
            args=["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
        )
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
            url="https://mcp.example.com/mcp",
            headers={"Authorization": "Bearer token"},
        )
        assert mcp.headers["Authorization"] == "Bearer token"

    def test_with_env(self):
        mcp = McpServer(
            name="github",
            command="github-mcp",
            env={"GITHUB_TOKEN": "secret"},
        )
        assert mcp.env["GITHUB_TOKEN"] == "secret"

    def test_defaults_are_empty_collections(self):
        mcp = McpServer(name="fs", command="uvx")
        assert mcp.args == []
        assert mcp.env == {}
        assert mcp.headers == {}

    def test_serialization_roundtrip(self):
        mcp = McpServer(name="test", command="test-mcp")
        data = mcp.model_dump()
        restored = McpServer.model_validate(data)
        assert restored == mcp


class TestMcpServerValidation:
    def test_both_command_and_url_rejected(self):
        with pytest.raises(ValidationError, match="exactly one of 'command' or 'url'"):
            McpServer(name="bad", command="npx", url="https://x.example.com")

    def test_neither_command_nor_url_rejected(self):
        with pytest.raises(ValidationError, match="must set 'command'"):
            McpServer(name="bad")

    def test_whitespace_in_command_rejected(self):
        with pytest.raises(ValidationError, match="just the executable"):
            McpServer(name="bad", command="npx -y some-server /docs")

    def test_headers_without_url_rejected(self):
        with pytest.raises(ValidationError, match="'headers' only valid with 'url'"):
            McpServer(name="bad", command="npx", headers={"A": "b"})

    def test_env_without_command_rejected(self):
        with pytest.raises(ValidationError, match="'env' only valid with 'command'"):
            McpServer(name="bad", url="https://x.example.com", env={"A": "b"})

    def test_explicit_stdio_without_command_rejected(self):
        with pytest.raises(ValidationError, match="transport 'stdio' requires 'command'"):
            McpServer(
                name="bad", transport=McpTransport.STDIO, url="https://x.example.com"
            )

    def test_explicit_sse_without_url_rejected(self):
        with pytest.raises(ValidationError, match="transport 'sse' requires 'url'"):
            McpServer(name="bad", transport=McpTransport.SSE, command="npx")

    def test_explicit_streamable_http_without_url_rejected(self):
        with pytest.raises(
            ValidationError, match="transport 'streamable_http' requires 'url'"
        ):
            McpServer(name="bad", transport=McpTransport.STREAMABLE_HTTP, command="npx")

    def test_install_field_removed(self):
        with pytest.raises(ValidationError):
            McpServer(name="bad", command="npx", install="npm install -g x")


class TestTransportInference:
    def test_command_only_defaults_transport_none(self):
        """Inference happens in vystak.mcp.config.normalize, not the model;
        the model stores what the user wrote."""
        mcp = McpServer(name="fs", command="npx")
        assert mcp.transport is None

    def test_url_only_defaults_transport_none(self):
        mcp = McpServer(name="api", url="https://x.example.com")
        assert mcp.transport is None

    def test_explicit_sse_with_url_honored(self):
        mcp = McpServer(name="api", transport=McpTransport.SSE, url="https://x.example.com")
        assert mcp.transport == McpTransport.SSE
