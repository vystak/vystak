"""McpServer model — MCP tool provider connections."""

from vystak.schema.common import McpTransport, NamedModel


class McpServer(NamedModel):
    """An MCP server that provides tools to an agent."""

    transport: McpTransport
    command: str | None = None
    url: str | None = None
    args: list[str] | None = None
    env: dict | None = None
    headers: dict | None = None
    install: str | None = None
