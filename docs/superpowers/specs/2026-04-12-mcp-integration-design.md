# MCP Server Integration — Design Spec

## Overview

Wire up the `mcp_servers` schema field into generated agent code using `langchain-mcp-adapters`. Agents can connect to MCP servers via stdio (local subprocess) or SSE/HTTP (remote) transports, gaining their tools alongside regular tools.

## Decisions

| Decision | Choice |
|----------|--------|
| MCP client library | `langchain-mcp-adapters` (`MultiServerMCPClient`) |
| Provisioning | Transport determines: stdio = in-container, SSE/HTTP = external |
| Dependencies | User specifies `install` field on McpServer for Dockerfile |

## Schema Change

Add `install` field to `McpServer` in `packages/python/agentstack/src/agentstack/schema/mcp.py`:

```python
class McpServer(NamedModel):
    transport: McpTransport
    command: str | None = None
    url: str | None = None
    args: list[str] | None = None
    env: dict | None = None
    headers: dict | None = None
    install: str | None = None     # NEW — install command for Dockerfile
```

## Example YAML

```yaml
mcp_servers:
  - name: filesystem
    transport: stdio
    command: npx
    args: ["-y", "@modelcontextprotocol/server-filesystem", "/data"]
    install: "apt-get update && apt-get install -y nodejs npm"

  - name: sqlite-db
    transport: stdio
    command: mcp-server-sqlite
    args: ["--db-path", "/data/app.db"]
    install: "pip install mcp-server-sqlite"

  - name: remote-api
    transport: streamable_http
    url: "http://mcp-server.example.com/mcp"
    headers:
      Authorization: "Bearer token"
```

## Generated Code

### agent.py — MCP server config

When `agent.mcp_servers` is present, the adapter generates a `MCP_SERVERS` dict:

```python
from langchain_mcp_adapters.client import MultiServerMCPClient

MCP_SERVERS = {
    "filesystem": {
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem", "/data"],
    },
    "remote-api": {
        "transport": "http",
        "url": "http://mcp-server.example.com/mcp",
        "headers": {"Authorization": "Bearer token"},
    },
}
```

Transport mapping:
- `McpTransport.STDIO` → `"stdio"`
- `McpTransport.SSE` → `"sse"`
- `McpTransport.STREAMABLE_HTTP` → `"http"`

Fields included per transport:
- stdio: `command`, `args`, `env`
- sse: `url`, `headers`
- streamable_http: `url`, `headers`

`env` values that reference secrets (contain `${...}`) are resolved via `os.environ`.

### agent.py — create_agent gains mcp_tools

```python
def create_agent(checkpointer, store=None, mcp_tools=None):
    all_tools = [get_weather, get_time, save_memory, forget_memory]
    if mcp_tools:
        all_tools.extend(mcp_tools)
    return create_react_agent(model, all_tools, checkpointer=checkpointer, store=store, prompt=system_prompt)
```

When no MCP servers are defined, `mcp_tools` defaults to `None` and behavior is unchanged.

### server.py — lifespan initializes MCP client

For agents with MCP servers, the lifespan manages the MCP client lifecycle:

```python
from agent import MCP_SERVERS, create_agent, DB_URI

_mcp_client = None

@asynccontextmanager
async def lifespan(app):
    global _agent, _store, _mcp_client
    async with MultiServerMCPClient(MCP_SERVERS) as mcp_client:
        _mcp_client = mcp_client
        mcp_tools = await mcp_client.get_tools()
        # ... existing checkpointer/store init ...
        _agent = create_agent(checkpointer, store=store, mcp_tools=mcp_tools)
        yield
```

For agents without MCP servers, the lifespan is unchanged.

For non-persistent agents (no resources) with MCP servers, a lifespan is added (currently non-persistent agents don't use lifespan):

```python
@asynccontextmanager
async def lifespan(app):
    global _agent, _mcp_client
    async with MultiServerMCPClient(MCP_SERVERS) as mcp_client:
        _mcp_client = mcp_client
        mcp_tools = await mcp_client.get_tools()
        _agent = create_agent(mcp_tools=mcp_tools)
        yield
```

### requirements.txt

Adds `langchain-mcp-adapters>=0.1` when MCP servers are present.

### Dockerfile

Install commands from MCP servers are added before the regular pip install:

```dockerfile
FROM python:3.11-slim
WORKDIR /app
# MCP server installs
RUN apt-get update && apt-get install -y nodejs npm
RUN pip install mcp-server-sqlite
# Regular deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["python", "server.py"]
```

The Docker provider reads `agent.mcp_servers[].install` and prepends RUN commands to the Dockerfile template.

## File Changes

### Schema

`packages/python/agentstack/src/agentstack/schema/mcp.py`:
- Add `install: str | None = None` to `McpServer`

### Adapter templates

`packages/python/agentstack-adapter-langchain/src/agentstack_adapter_langchain/templates.py`:
- New helper: `_generate_mcp_config(agent)` — returns MCP_SERVERS dict code string
- Update `generate_agent_py`:
  - Import `MultiServerMCPClient` when MCP servers present
  - Add `MCP_SERVERS` dict
  - `create_agent` gains `mcp_tools=None` parameter
  - Merge `mcp_tools` into tool list
- Update `generate_server_py`:
  - Import `MCP_SERVERS` from agent when MCP servers present
  - Add `_mcp_client = None` global
  - Lifespan: `async with MultiServerMCPClient(MCP_SERVERS) as mcp_client`
  - Pass `mcp_tools` to `create_agent`
  - Non-persistent agents with MCP servers get a lifespan
- Update `generate_requirements_txt`:
  - Add `langchain-mcp-adapters>=0.1` when MCP servers present

### Docker provider

`packages/python/agentstack-provider-docker/src/agentstack_provider_docker/provider.py`:
- Update `DOCKERFILE_TEMPLATE` generation to include install commands from `agent.mcp_servers`

### Tests

`packages/python/agentstack-adapter-langchain/tests/test_templates.py`:
- `test_mcp_config_generated` — MCP_SERVERS dict in agent.py
- `test_mcp_import` — MultiServerMCPClient import
- `test_mcp_tools_in_create_agent` — mcp_tools parameter
- `test_mcp_lifespan` — MCP client in server lifespan
- `test_mcp_requirements` — langchain-mcp-adapters in requirements
- `test_no_mcp_unchanged` — no MCP servers = no changes
- `test_mcp_agent_parseable` — ast.parse()
- `test_mcp_server_parseable` — ast.parse()

## What This Spec Does NOT Cover

- MCP server provisioning as Docker containers (sidecar pattern)
- MCP server health checking
- MCP tool filtering (loading only specific tools from a server)
- MCP prompts and resources (only tools are loaded)
- Dynamic MCP server discovery
