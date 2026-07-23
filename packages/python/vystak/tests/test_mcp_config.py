"""Tests for vystak.mcp.config — framework-agnostic MCP normalization."""

import pytest
from vystak.mcp.config import McpConnectionSpec, normalize
from vystak.schema.common import McpTransport
from vystak.schema.mcp import McpServer


def test_one_spec_per_server():
    servers = [
        McpServer(name="fs", command="npx"),
        McpServer(name="api", url="https://x.example.com"),
    ]
    specs = normalize(servers)
    assert [s.name for s in specs] == ["fs", "api"]
    assert all(isinstance(s, McpConnectionSpec) for s in specs)


def test_transport_inferred_stdio_from_command():
    (spec,) = normalize([McpServer(name="fs", command="uvx", args=["some-mcp"])])
    assert spec.transport == McpTransport.STDIO
    assert spec.command == "uvx"
    assert spec.args == ("some-mcp",)


def test_transport_inferred_streamable_http_from_url():
    (spec,) = normalize([McpServer(name="api", url="https://x.example.com/mcp")])
    assert spec.transport == McpTransport.STREAMABLE_HTTP
    assert spec.url == "https://x.example.com/mcp"


def test_explicit_transport_honored():
    (spec,) = normalize(
        [McpServer(name="api", transport=McpTransport.SSE, url="https://x.example.com")]
    )
    assert spec.transport == McpTransport.SSE


def test_stdio_spec_has_no_remote_fields():
    (spec,) = normalize([McpServer(name="fs", command="npx")])
    assert spec.url is None
    assert spec.headers == {}


def test_http_spec_has_no_stdio_fields():
    (spec,) = normalize([McpServer(name="api", url="https://x.example.com")])
    assert spec.command is None
    assert spec.env == {}
    assert spec.args == ()


def test_literals_preserved_without_lookup():
    (spec,) = normalize(
        [
            McpServer(
                name="gh",
                url="https://x.example.com",
                headers={"Authorization": "Bearer ${secret.GITHUB_TOKEN}"},
            )
        ]
    )
    assert spec.headers["Authorization"] == "Bearer ${secret.GITHUB_TOKEN}"


def test_lookup_substitutes_refs_in_args_env_headers():
    def lookup(name):
        return {"TOKEN": "tok", "PATH_ARG": "/docs"}[name]

    stdio, remote = normalize(
        [
            McpServer(
                name="fs",
                command="npx",
                args=["${secret.PATH_ARG}"],
                env={"GITHUB_TOKEN": "${secret.TOKEN}"},
            ),
            McpServer(
                name="gh",
                url="https://x.example.com",
                headers={"Authorization": "Bearer ${secret.TOKEN}"},
            ),
        ],
        secret_lookup=lookup,
    )
    assert stdio.args == ("/docs",)
    assert stdio.env == {"GITHUB_TOKEN": "tok"}
    assert remote.headers == {"Authorization": "Bearer tok"}


def test_missing_secret_raises():
    def lookup(name):
        raise KeyError(name)

    with pytest.raises(KeyError):
        normalize(
            [McpServer(name="fs", command="npx", env={"T": "${secret.X}"})],
            secret_lookup=lookup,
        )
