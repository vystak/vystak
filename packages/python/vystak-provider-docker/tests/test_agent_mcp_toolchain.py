"""MCP toolchain sniffing for generated agent Dockerfiles."""

from vystak.schema.mcp import McpServer
from vystak_provider_docker.nodes.agent import mcp_toolchain_layers


def test_npx_command_installs_node():
    layers = mcp_toolchain_layers([McpServer(name="fs", command="npx")])
    assert "apt-get install -y nodejs npm" in layers


def test_uvx_command_installs_uv():
    layers = mcp_toolchain_layers([McpServer(name="fs", command="uvx")])
    assert "pip install --no-cache-dir uv" in layers


def test_both_toolchains_when_mixed():
    layers = mcp_toolchain_layers(
        [
            McpServer(name="a", command="npx"),
            McpServer(name="b", command="uvx"),
        ]
    )
    assert "nodejs npm" in layers
    assert "pip install --no-cache-dir uv" in layers


def test_plain_executable_needs_nothing():
    assert mcp_toolchain_layers([McpServer(name="x", command="my-mcp")]) == ""


def test_remote_servers_need_nothing():
    assert (
        mcp_toolchain_layers([McpServer(name="r", url="https://x.example.com")]) == ""
    )


def test_no_servers_no_layers():
    assert mcp_toolchain_layers([]) == ""


def test_only_toolchain_run_lines_emitted():
    """The removed `install` escape hatch must not resurface as RUN lines."""
    layers = mcp_toolchain_layers([McpServer(name="fs", command="npx")])
    run_lines = [line for line in layers.splitlines() if line.startswith("RUN ")]
    assert len(run_lines) == 1
