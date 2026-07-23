"""McpServer model — MCP tool provider connections.

Claude-style config: users set ``command``/``args``/``env`` for local stdio
servers or ``url``/``headers`` for remote ones; ``transport`` is optional and
inferred from shape by ``vystak.mcp.config.normalize`` (command → stdio,
url → streamable_http) unless set explicitly.
"""

from typing import Self

from pydantic import ConfigDict, model_validator

from vystak.schema.common import McpTransport, NamedModel


class McpServer(NamedModel):
    """An MCP server that provides tools to an agent."""

    # Forbid unknown fields so configs still using the removed ``install``
    # field (or typos) fail with a clean validation error.
    model_config = ConfigDict(extra="forbid")

    # Local stdio process
    command: str | None = None  # executable only, e.g. "npx", "uvx", "docker"
    args: list[str] = []
    env: dict[str, str] = {}

    # Remote HTTP/SSE
    url: str | None = None
    headers: dict[str, str] = {}

    # Optional override; otherwise inferred from shape at normalize time.
    transport: McpTransport | None = None

    @model_validator(mode="after")
    def _validate_shape(self) -> Self:
        if self.command and self.url:
            raise ValueError(
                f"mcp_servers[{self.name}]: set exactly one of 'command' or 'url'"
            )
        if not self.command and not self.url:
            raise ValueError(
                f"mcp_servers[{self.name}]: must set 'command' (stdio) or 'url' (remote)"
            )
        if self.command and " " in self.command:
            raise ValueError(
                f"mcp_servers[{self.name}].command must be just the executable "
                f"(got {self.command!r}); pass arguments via 'args'"
            )
        if self.headers and not self.url:
            raise ValueError(
                f"mcp_servers[{self.name}]: 'headers' only valid with 'url'"
            )
        if self.env and not self.command:
            raise ValueError(
                f"mcp_servers[{self.name}]: 'env' only valid with 'command'"
            )
        if self.transport is not None:
            if self.transport == McpTransport.STDIO and not self.command:
                raise ValueError(
                    f"mcp_servers[{self.name}]: transport 'stdio' requires 'command'"
                )
            if (
                self.transport in (McpTransport.SSE, McpTransport.STREAMABLE_HTTP)
                and not self.url
            ):
                raise ValueError(
                    f"mcp_servers[{self.name}]: transport "
                    f"'{self.transport.value}' requires 'url'"
                )
        return self
