"""Normalize ``list[McpServer]`` into concrete connection specs.

Framework-agnostic: no adapter or client dependencies. Each framework
template translates :class:`McpConnectionSpec` into whatever shape its MCP
client wants (LangChain's ``MultiServerMCPClient`` today; a future Mastra
adapter would emit TS config from the same specs at codegen time with
``secret_lookup=None`` to keep ``${secret.X}`` literal).
"""

from collections.abc import Callable
from dataclasses import dataclass, field

from vystak.schema.common import McpTransport
from vystak.schema.mcp import McpServer
from vystak.secrets.interpolate import interpolate


@dataclass(frozen=True)
class McpConnectionSpec:
    name: str
    transport: McpTransport  # always concrete
    # stdio
    command: str | None = None
    args: tuple[str, ...] = ()
    env: dict[str, str] = field(default_factory=dict)
    # remote
    url: str | None = None
    headers: dict[str, str] = field(default_factory=dict)


def normalize(
    servers: list[McpServer],
    secret_lookup: Callable[[str], str] | None = None,
) -> list[McpConnectionSpec]:
    """Infer transport, build connection specs, optionally interpolate secrets.

    ``secret_lookup=None`` preserves ``${secret.X}`` literals (useful for
    codegen-time consumers that emit framework code with their own secret
    machinery). With a lookup, refs in ``args``/``env``/``headers`` are
    substituted; a missing name raises ``KeyError`` from the lookup.
    """
    specs: list[McpConnectionSpec] = []
    for server in servers:
        transport = server.transport
        if transport is None:
            transport = (
                McpTransport.STDIO if server.command else McpTransport.STREAMABLE_HTTP
            )

        args: list[str] = server.args
        env: dict[str, str] = server.env
        headers: dict[str, str] = server.headers
        if secret_lookup is not None:
            args = interpolate(args, secret_lookup)
            env = interpolate(env, secret_lookup)
            headers = interpolate(headers, secret_lookup)

        specs.append(
            McpConnectionSpec(
                name=server.name,
                transport=transport,
                command=server.command,
                args=tuple(args),
                env=dict(env),
                url=server.url,
                headers=dict(headers),
            )
        )
    return specs
