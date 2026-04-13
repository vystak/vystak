# MCP Server Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire up MCP servers from the agent schema into generated code using `langchain-mcp-adapters`, so agents can connect to MCP tool servers alongside their regular tools.

**Architecture:** Add `install` field to McpServer schema. Adapter generates `MultiServerMCPClient` config and initializes it in the server lifespan. Docker provider includes install commands in the Dockerfile.

**Tech Stack:** Python 3.11+, langchain-mcp-adapters, pytest

---

### Task 1: Schema Change — Add `install` Field

**Files:**
- Modify: `packages/python/agentstack/src/agentstack/schema/mcp.py`

- [ ] **Step 1: Add install field to McpServer**

Replace `packages/python/agentstack/src/agentstack/schema/mcp.py`:

```python
"""McpServer model — MCP tool provider connections."""

from agentstack.schema.common import McpTransport, NamedModel


class McpServer(NamedModel):
    """An MCP server that provides tools to an agent."""

    transport: McpTransport
    command: str | None = None
    url: str | None = None
    args: list[str] | None = None
    env: dict | None = None
    headers: dict | None = None
    install: str | None = None
```

- [ ] **Step 2: Run tests to verify nothing breaks**

Run: `cd /Users/akolodkin/Developer/work/AgentsStack && uv run pytest packages/python/agentstack/tests/ -v`

Expected: all pass (install is optional, defaults to None).

- [ ] **Step 3: Commit**

```bash
git add packages/python/agentstack/
git commit -m "feat: add install field to McpServer schema"
```

---

### Task 2: Adapter — MCP Config Generation in agent.py

**Files:**
- Modify: `packages/python/agentstack-adapter-langchain/src/agentstack_adapter_langchain/templates.py`

- [ ] **Step 1: Add MCP helper function**

Add this function to `templates.py` after the existing helpers (after `_get_session_store`):

```python
def _has_mcp_servers(agent: Agent) -> bool:
    """Check if the agent has MCP servers configured."""
    return bool(agent.mcp_servers)


def _generate_mcp_config(agent: Agent) -> str:
    """Generate MCP_SERVERS dict for MultiServerMCPClient."""
    if not agent.mcp_servers:
        return ""

    lines = []
    lines.append("")
    lines.append("# MCP Server connections")
    lines.append("MCP_SERVERS = {")

    for mcp in agent.mcp_servers:
        lines.append(f'    "{mcp.name}": {{')

        # Transport mapping
        transport_map = {
            "stdio": "stdio",
            "sse": "sse",
            "streamable_http": "http",
        }
        transport = transport_map.get(mcp.transport.value, mcp.transport.value)
        lines.append(f'        "transport": "{transport}",')

        if mcp.command:
            lines.append(f'        "command": "{mcp.command}",')
        if mcp.args:
            args_str = ", ".join(f'"{a}"' for a in mcp.args)
            lines.append(f'        "args": [{args_str}],')
        if mcp.url:
            lines.append(f'        "url": "{mcp.url}",')
        if mcp.env:
            lines.append(f'        "env": {{')
            for k, v in mcp.env.items():
                lines.append(f'            "{k}": "{v}",')
            lines.append(f'        }},')
        if mcp.headers:
            lines.append(f'        "headers": {{')
            for k, v in mcp.headers.items():
                lines.append(f'            "{k}": "{v}",')
            lines.append(f'        }},')

        lines.append(f'    }},')

    lines.append("}")
    lines.append("")

    return "\n".join(lines)
```

- [ ] **Step 2: Update `generate_agent_py` — add MCP import and config**

In `generate_agent_py`, after the import section and before the model setup, add:

```python
    # MCP servers
    has_mcp = _has_mcp_servers(agent)
    if has_mcp:
        lines.append("from langchain_mcp_adapters.client import MultiServerMCPClient")
        lines.append(_generate_mcp_config(agent))
```

Add this after the existing imports (after the `from langgraph.prebuilt import create_react_agent` line).

- [ ] **Step 3: Update `create_agent` signature to accept `mcp_tools`**

For persistent agents, change `create_agent` signature:

Replace:
```python
        lines.append(f"def create_agent(checkpointer, store=None):")
```

With:
```python
        lines.append(f"def create_agent(checkpointer, store=None, mcp_tools=None):")
```

And update the body to merge mcp_tools:

Replace:
```python
            lines.append(f"    return create_react_agent(model, [{full_tools_list}], checkpointer=checkpointer, store=store, prompt=system_prompt)")
```

With:
```python
            lines.append(f"    all_tools = [{full_tools_list}]")
            lines.append(f"    if mcp_tools:")
            lines.append(f"        all_tools.extend(mcp_tools)")
            lines.append(f"    return create_react_agent(model, all_tools, checkpointer=checkpointer, store=store, prompt=system_prompt)")
```

Do this for all four branches (persistent+prompt, persistent+no-prompt, non-persistent+prompt, non-persistent+no-prompt).

For non-persistent agents with MCP, change from direct agent creation to a `create_agent` function:

```python
    if has_mcp and not (session_store and session_store.engine in ("postgres", "sqlite")):
        # Non-persistent but has MCP — need a create_agent function for lifespan
        if system_prompt:
            lines.append(f"def create_agent(mcp_tools=None):")
            lines.append(f"    all_tools = [{full_tools_list}]")
            lines.append(f"    if mcp_tools:")
            lines.append(f"        all_tools.extend(mcp_tools)")
            lines.append(f"    return create_react_agent(model, all_tools, checkpointer=memory, prompt=system_prompt)")
        else:
            lines.append(f"def create_agent(mcp_tools=None):")
            lines.append(f"    all_tools = [{full_tools_list}]")
            lines.append(f"    if mcp_tools:")
            lines.append(f"        all_tools.extend(mcp_tools)")
            lines.append(f"    return create_react_agent(model, all_tools, checkpointer=memory)")
        lines.append("")
        lines.append("agent = None  # created during server lifespan")
```

- [ ] **Step 4: Run adapter tests**

Run: `uv run pytest packages/python/agentstack-adapter-langchain/tests/ -v`

Fix any failures. Existing tests should pass since MCP is only added when `agent.mcp_servers` is non-empty.

- [ ] **Step 5: Commit**

```bash
git add packages/python/agentstack-adapter-langchain/
git commit -m "feat: generate MCP server config and tools integration in agent.py"
```

---

### Task 3: Adapter — MCP Client in server.py Lifespan

**Files:**
- Modify: `packages/python/agentstack-adapter-langchain/src/agentstack_adapter_langchain/templates.py`

- [ ] **Step 1: Update `generate_server_py` — import MCP_SERVERS when present**

In the persistent mode imports section, when MCP is present, add `MCP_SERVERS` to the import:

For persistent mode:
```python
    if has_mcp:
        lines.append("from agent import create_agent, DB_URI, MCP_SERVERS")
    else:
        lines.append("from agent import create_agent, DB_URI")
```

For non-persistent mode with MCP:
```python
    if has_mcp:
        lines.append("from agent import create_agent, MCP_SERVERS")
        lines.append("from langchain_mcp_adapters.client import MultiServerMCPClient")
    else:
        lines.append("from agent import agent")
```

Add `has_mcp = _has_mcp_servers(agent)` at the top of `generate_server_py`.

- [ ] **Step 2: Update lifespan — initialize MCP client**

For persistent mode with MCP, the lifespan wraps `MultiServerMCPClient`:

```python
    if uses_persistent and has_mcp:
        lines.append("    global _agent, _store, _task_manager, _mcp_client")
        lines.append(f"    async with {saver_class}.from_conn_string(DB_URI) as checkpointer, \\")
        lines.append(f"               {store_class}.from_conn_string(...) as store, \\")
        lines.append(f"               MultiServerMCPClient(MCP_SERVERS) as mcp_client:")
        lines.append("        await checkpointer.setup()")
        lines.append("        _store = store")
        lines.append("        _mcp_client = mcp_client")
        lines.append("        mcp_tools = await mcp_client.get_tools()")
        lines.append("        _agent = create_agent(checkpointer, store=store, mcp_tools=mcp_tools)")
```

For non-persistent mode with MCP (new lifespan):
```python
    if has_mcp and not uses_persistent:
        lines.append("from contextlib import asynccontextmanager")
        lines.append("from langchain_mcp_adapters.client import MultiServerMCPClient")
        lines.append("")
        lines.append("from agent import create_agent, MCP_SERVERS")
        lines.append("")
        lines.append("_agent = None")
        lines.append("_mcp_client = None")
        lines.append("")
        lines.append("@asynccontextmanager")
        lines.append("async def lifespan(app):")
        lines.append("    global _agent, _mcp_client")
        lines.append("    async with MultiServerMCPClient(MCP_SERVERS) as mcp_client:")
        lines.append("        _mcp_client = mcp_client")
        lines.append("        mcp_tools = await mcp_client.get_tools()")
        lines.append("        _agent = create_agent(mcp_tools=mcp_tools)")
        lines.append("        yield")
        lines.append("")
        lines.append('app = FastAPI(title="...", lifespan=lifespan)')
```

Note: This is complex because there are 4 combinations: persistent/not x mcp/not. Be careful to handle all branches. READ the current `generate_server_py` carefully before making changes.

- [ ] **Step 3: Add `_mcp_client = None` to module-level globals**

When MCP is present, add `_mcp_client = None` alongside `_agent = None`.

- [ ] **Step 4: Run tests and verify generated code parses**

Run: `uv run pytest packages/python/agentstack-adapter-langchain/tests/ -v`

Also verify:
```bash
uv run python -c "
from agentstack.schema.agent import Agent
from agentstack.schema.model import Model
from agentstack.schema.provider import Provider
from agentstack.schema.mcp import McpServer
from agentstack.schema.common import McpTransport
from agentstack_adapter_langchain import LangChainAdapter
import ast

agent = Agent(
    name='mcp-test',
    model=Model(name='claude', provider=Provider(name='anthropic', type='anthropic'), model_name='claude-sonnet-4-20250514'),
    mcp_servers=[
        McpServer(name='filesystem', transport=McpTransport.STDIO, command='npx', args=['-y', '@modelcontextprotocol/server-filesystem', '/data']),
        McpServer(name='remote', transport=McpTransport.STREAMABLE_HTTP, url='http://example.com/mcp'),
    ],
)
adapter = LangChainAdapter()
code = adapter.generate(agent)
ast.parse(code.files['agent.py'])
ast.parse(code.files['server.py'])
print('Both parse OK')
print('MCP_SERVERS:', 'MCP_SERVERS' in code.files['agent.py'])
print('MultiServerMCPClient:', 'MultiServerMCPClient' in code.files['server.py'])
"
```

- [ ] **Step 5: Commit**

```bash
git add packages/python/agentstack-adapter-langchain/
git commit -m "feat: initialize MCP client in server lifespan, load MCP tools"
```

---

### Task 4: Adapter — Update requirements.txt

**Files:**
- Modify: `packages/python/agentstack-adapter-langchain/src/agentstack_adapter_langchain/templates.py`

- [ ] **Step 1: Update `generate_requirements_txt`**

Add `langchain-mcp-adapters` when MCP servers are present:

```python
    mcp_pkg = ""
    if agent.mcp_servers:
        mcp_pkg = "\nlangchain-mcp-adapters>=0.1"
```

Include `{mcp_pkg}` in the return template alongside `{checkpoint_pkg}` and `{tool_deps}`.

- [ ] **Step 2: Run tests**

Run: `uv run pytest packages/python/agentstack-adapter-langchain/tests/ -v`

- [ ] **Step 3: Commit**

```bash
git add packages/python/agentstack-adapter-langchain/
git commit -m "feat: add langchain-mcp-adapters to requirements when MCP servers present"
```

---

### Task 5: Docker Provider — Install Commands in Dockerfile

**Files:**
- Modify: `packages/python/agentstack-provider-docker/src/agentstack_provider_docker/provider.py`

- [ ] **Step 1: Update Dockerfile generation in `apply()`**

In the `apply()` method, after writing generated files and before building the image, generate a custom Dockerfile that includes MCP install commands:

Find the section that writes the Dockerfile:
```python
dockerfile_content = DOCKERFILE_TEMPLATE.format(
    entrypoint=self._generated_code.entrypoint
)
(build_dir / "Dockerfile").write_text(dockerfile_content)
```

Replace with:
```python
# Build Dockerfile with optional MCP install commands
mcp_installs = ""
if self._agent and self._agent.mcp_servers:
    install_cmds = []
    for mcp in self._agent.mcp_servers:
        if mcp.install:
            install_cmds.append(f"RUN {mcp.install}")
    if install_cmds:
        mcp_installs = "\n".join(install_cmds) + "\n"

dockerfile_content = (
    "FROM python:3.11-slim\n"
    "WORKDIR /app\n"
    f"{mcp_installs}"
    "COPY requirements.txt .\n"
    "RUN pip install --no-cache-dir -r requirements.txt\n"
    "COPY . .\n"
    f'CMD ["python", "{self._generated_code.entrypoint}"]\n'
)
(build_dir / "Dockerfile").write_text(dockerfile_content)
```

- [ ] **Step 2: Run provider tests**

Run: `uv run pytest packages/python/agentstack-provider-docker/tests/ -v`

- [ ] **Step 3: Commit**

```bash
git add packages/python/agentstack-provider-docker/
git commit -m "feat: include MCP install commands in generated Dockerfile"
```

---

### Task 6: Tests and Verification

**Files:**
- Modify: `packages/python/agentstack-adapter-langchain/tests/test_templates.py`

- [ ] **Step 1: Add MCP test fixtures and tests**

Append to `test_templates.py`:

```python
from agentstack.schema.mcp import McpServer
from agentstack.schema.common import McpTransport


@pytest.fixture()
def mcp_agent(anthropic_provider):
    return Agent(
        name="mcp-bot",
        model=Model(name="claude", provider=anthropic_provider, model_name="claude-sonnet-4-20250514"),
        mcp_servers=[
            McpServer(name="filesystem", transport=McpTransport.STDIO, command="npx", args=["-y", "@modelcontextprotocol/server-filesystem", "/data"]),
            McpServer(name="remote", transport=McpTransport.STREAMABLE_HTTP, url="http://example.com/mcp", headers={"Authorization": "Bearer token"}),
        ],
    )


@pytest.fixture()
def mcp_agent_with_resources(anthropic_provider):
    docker_provider = Provider(name="docker", type="docker")
    return Agent(
        name="mcp-pg-bot",
        model=Model(name="claude", provider=anthropic_provider, model_name="claude-sonnet-4-20250514"),
        mcp_servers=[
            McpServer(name="filesystem", transport=McpTransport.STDIO, command="npx", args=["-y", "@modelcontextprotocol/server-filesystem"]),
        ],
        resources=[SessionStore(name="sessions", provider=docker_provider, engine="postgres")],
    )


class TestMCPIntegration:
    def test_mcp_config_generated(self, mcp_agent):
        code = generate_agent_py(mcp_agent)
        assert "MCP_SERVERS" in code
        assert '"filesystem"' in code
        assert '"remote"' in code

    def test_mcp_transport_mapping(self, mcp_agent):
        code = generate_agent_py(mcp_agent)
        assert '"transport": "stdio"' in code
        assert '"transport": "http"' in code

    def test_mcp_import(self, mcp_agent):
        code = generate_agent_py(mcp_agent)
        assert "MultiServerMCPClient" in code

    def test_mcp_tools_in_create_agent(self, mcp_agent):
        code = generate_agent_py(mcp_agent)
        assert "mcp_tools" in code

    def test_mcp_lifespan_in_server(self, mcp_agent):
        code = generate_server_py(mcp_agent)
        assert "MultiServerMCPClient" in code
        assert "mcp_tools" in code

    def test_mcp_requirements(self, mcp_agent):
        reqs = generate_requirements_txt(mcp_agent)
        assert "langchain-mcp-adapters" in reqs

    def test_no_mcp_unchanged(self, openai_agent):
        code = generate_agent_py(openai_agent)
        assert "MCP_SERVERS" not in code
        assert "MultiServerMCPClient" not in code

    def test_mcp_agent_parseable(self, mcp_agent):
        code = generate_agent_py(mcp_agent)
        python_ast.parse(code)

    def test_mcp_server_parseable(self, mcp_agent):
        code = generate_server_py(mcp_agent)
        python_ast.parse(code)

    def test_mcp_with_resources_agent_parseable(self, mcp_agent_with_resources):
        code = generate_agent_py(mcp_agent_with_resources)
        python_ast.parse(code)
        assert "MCP_SERVERS" in code
        assert "mcp_tools" in code

    def test_mcp_with_resources_server_parseable(self, mcp_agent_with_resources):
        code = generate_server_py(mcp_agent_with_resources)
        python_ast.parse(code)
        assert "MultiServerMCPClient" in code
```

- [ ] **Step 2: Run all tests**

Run: `just test-python`

Expected: all pass.

- [ ] **Step 3: Commit**

```bash
git add packages/python/agentstack-adapter-langchain/tests/
git commit -m "test: add MCP integration tests for templates"
```
