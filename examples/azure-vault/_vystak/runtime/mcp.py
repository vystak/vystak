"""MCP server wiring via langchain-mcp-adapters.

The MultiServerMCPClient class is resolved at call time (not import time) so
that tests can monkey-patch a fake client onto this module before invoking
`attach_mcp_servers`. The package `langchain-mcp-adapters` is an optional
runtime dependency.
"""

import sys
from typing import Any


async def attach_mcp_servers(agent: Any) -> list[Any]:
    mcps = getattr(agent, "mcp_servers", []) or []
    if not mcps:
        return []

    client_cls = _resolve_client_cls()
    if client_cls is None:
        return []

    config: dict[str, dict] = {}
    for m in mcps:
        if m.transport == "stdio":
            config[m.name] = {
                "transport": "stdio",
                "command": m.command,
                "args": m.args,
            }
        elif m.transport in ("sse", "http"):
            config[m.name] = {"transport": m.transport, "url": m.url}

    client = client_cls(config)
    return await client.get_tools()


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
