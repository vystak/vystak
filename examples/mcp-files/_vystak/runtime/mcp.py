"""MCP server wiring via langchain-mcp-adapters.

Normalization (transport inference, secret interpolation) lives in
framework-agnostic ``vystak.mcp.config``; this wrapper only translates the
resulting specs into the dict shape ``MultiServerMCPClient`` wants.

The MultiServerMCPClient class is resolved at call time (not import time) so
that tests can monkey-patch a fake client onto this module before invoking
`attach_mcp_servers`. The package `langchain-mcp-adapters` is an optional
runtime dependency; without it the agent runs with no MCP tools.
"""

import sys
from typing import Any

from vystak.mcp.config import McpConnectionSpec, normalize
from vystak.schema.common import McpTransport
from vystak.secrets import get as lookup_secret


async def attach_mcp_servers(agent: Any) -> list[Any]:
    servers = getattr(agent, "mcp_servers", []) or []
    if not servers:
        return []

    client_cls = _resolve_client_cls()
    if client_cls is None:
        return []

    specs = normalize(servers, secret_lookup=lookup_secret)
    config = {s.name: _to_langchain_config(s) for s in specs}
    return await client_cls(config).get_tools()


def _to_langchain_config(s: McpConnectionSpec) -> dict:
    if s.transport == McpTransport.STDIO:
        return {
            "transport": "stdio",
            "command": s.command,
            "args": list(s.args),
            "env": dict(s.env),
        }
    return {
        "transport": s.transport.value,  # "sse" or "streamable_http"
        "url": s.url,
        "headers": dict(s.headers),
    }


def _resolve_client_cls() -> Any | None:
    """Look up MultiServerMCPClient on this module (allows test patching),
    falling back to importing it from the optional dependency."""
    module = sys.modules[__name__]
    cls = getattr(module, "MultiServerMCPClient", None)
    if cls is not None:
        return cls
    try:
        from langchain_mcp_adapters.client import MultiServerMCPClient
    except ImportError:
        return None
    return MultiServerMCPClient
