# Real Tool Loading Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Load real tool implementations from a `tools/` directory, package them for deployment, and fall back to stubs for missing tools.

**Architecture:** New `tools.py` module in the adapter handles discovery and validation. The adapter copies real tool files into the generated output as a `tools/` Python package with an auto-generated `__init__.py` that wraps functions with `@tool`. Templates updated to import real tools from the package and only inline stubs for missing ones.

**Tech Stack:** Python 3.11+, ast module for validation, pytest

---

### Task 1: Tool Discovery Module

**Files:**
- Create: `packages/python/agentstack-adapter-langchain/src/agentstack_adapter_langchain/tools.py`
- Create: `packages/python/agentstack-adapter-langchain/tests/test_tools.py`

- [ ] **Step 1: Write tests**

`packages/python/agentstack-adapter-langchain/tests/test_tools.py`:
```python
import ast as python_ast
from pathlib import Path

import pytest

from agentstack.schema.agent import Agent
from agentstack.schema.model import Model
from agentstack.schema.provider import Provider
from agentstack.schema.skill import Skill

from agentstack_adapter_langchain.tools import (
    discover_tools,
    generate_tools_init,
    get_tool_requirements,
    read_tool_file,
)


@pytest.fixture()
def agent_with_tools():
    return Agent(
        name="test-bot",
        model=Model(
            name="claude",
            provider=Provider(name="anthropic", type="anthropic"),
            model_name="claude-sonnet-4-20250514",
        ),
        skills=[
            Skill(name="weather", tools=["get_weather", "get_forecast"]),
            Skill(name="time", tools=["get_time"]),
        ],
    )


@pytest.fixture()
def tools_dir(tmp_path):
    """Create a tools directory with sample tool files."""
    tools = tmp_path / "tools"
    tools.mkdir()

    (tools / "get_weather.py").write_text(
        'import requests\n\n'
        'def get_weather(city: str) -> str:\n'
        '    """Get current weather for a city."""\n'
        '    return f"Weather in {city}: sunny"\n'
    )

    (tools / "get_time.py").write_text(
        'from datetime import datetime\n\n'
        'def get_time(timezone: str) -> str:\n'
        '    """Get current time in a timezone."""\n'
        '    return datetime.now().isoformat()\n'
    )

    return tools


class TestDiscoverTools:
    def test_all_found(self, agent_with_tools, tools_dir):
        found, missing = discover_tools(agent_with_tools, tools_dir.parent)
        assert "get_weather" in found
        assert "get_time" in found
        assert "get_forecast" in missing

    def test_none_found(self, agent_with_tools, tmp_path):
        found, missing = discover_tools(agent_with_tools, tmp_path)
        assert found == {}
        assert set(missing) == {"get_weather", "get_forecast", "get_time"}

    def test_no_tools_dir(self, agent_with_tools, tmp_path):
        found, missing = discover_tools(agent_with_tools, tmp_path)
        assert found == {}
        assert len(missing) == 3

    def test_mixed(self, agent_with_tools, tools_dir):
        found, missing = discover_tools(agent_with_tools, tools_dir.parent)
        assert len(found) == 2
        assert missing == ["get_forecast"]

    def test_no_tools_in_agent(self, tmp_path):
        agent = Agent(
            name="bot",
            model=Model(
                name="claude",
                provider=Provider(name="anthropic", type="anthropic"),
                model_name="claude-sonnet-4-20250514",
            ),
        )
        found, missing = discover_tools(agent, tmp_path)
        assert found == {}
        assert missing == []


class TestReadToolFile:
    def test_valid_file(self, tools_dir):
        content = read_tool_file(tools_dir / "get_weather.py", "get_weather")
        assert "def get_weather(" in content
        assert "import requests" in content

    def test_missing_function(self, tools_dir):
        (tools_dir / "bad_tool.py").write_text(
            'def something_else():\n    pass\n'
        )
        with pytest.raises(ValueError, match="get_weather"):
            read_tool_file(tools_dir / "bad_tool.py", "get_weather")

    def test_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            read_tool_file(tmp_path / "nonexistent.py", "nonexistent")


class TestGenerateToolsInit:
    def test_basic(self):
        code = generate_tools_init(["get_weather", "get_time"])
        assert "from tools.get_weather import get_weather" in code
        assert "from tools.get_time import get_time" in code
        assert "get_weather = tool(get_weather)" in code
        assert "get_time = tool(get_time)" in code
        assert "from langchain_core.tools import tool" in code

    def test_parseable(self):
        code = generate_tools_init(["get_weather", "get_time"])
        python_ast.parse(code)

    def test_empty(self):
        code = generate_tools_init([])
        python_ast.parse(code)

    def test_single(self):
        code = generate_tools_init(["get_weather"])
        assert "get_weather = tool(get_weather)" in code
        python_ast.parse(code)


class TestGetToolRequirements:
    def test_exists(self, tools_dir):
        (tools_dir / "requirements.txt").write_text("requests\nbeautifulsoup4\n")
        reqs = get_tool_requirements(tools_dir.parent)
        assert "requests" in reqs
        assert "beautifulsoup4" in reqs

    def test_missing(self, tmp_path):
        reqs = get_tool_requirements(tmp_path)
        assert reqs is None

    def test_no_tools_dir(self, tmp_path):
        reqs = get_tool_requirements(tmp_path)
        assert reqs is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/akolodkin/Developer/work/AgentsStack && uv run pytest packages/python/agentstack-adapter-langchain/tests/test_tools.py -v`

Expected: FAIL — module not found.

- [ ] **Step 3: Implement tools.py**

`packages/python/agentstack-adapter-langchain/src/agentstack_adapter_langchain/tools.py`:
```python
"""Tool file discovery, reading, and packaging."""

import ast as python_ast
from pathlib import Path

from agentstack.schema.agent import Agent


def discover_tools(agent: Agent, base_dir: Path) -> tuple[dict[str, Path], list[str]]:
    """Discover which tools have real implementations on disk.

    Returns:
        found: dict of tool_name -> file path for tools with implementations
        missing: list of tool names without implementations (will be stubs)
    """
    tools_dir = base_dir / "tools"
    found: dict[str, Path] = {}
    missing: list[str] = []

    # Collect all unique tool names from skills
    seen = set()
    all_tools = []
    for skill in agent.skills:
        for tool_name in skill.tools:
            if tool_name not in seen:
                seen.add(tool_name)
                all_tools.append(tool_name)

    for tool_name in all_tools:
        tool_path = tools_dir / f"{tool_name}.py"
        if tool_path.exists():
            found[tool_name] = tool_path
        else:
            missing.append(tool_name)

    return found, missing


def read_tool_file(path: Path, expected_name: str) -> str:
    """Read a tool file and validate it contains the expected function.

    Raises:
        FileNotFoundError: if the file doesn't exist
        ValueError: if the file doesn't contain a function with the expected name
    """
    if not path.exists():
        raise FileNotFoundError(f"Tool file not found: {path}")

    content = path.read_text()

    # Parse and check for the function
    tree = python_ast.parse(content)
    function_names = [
        node.name
        for node in python_ast.walk(tree)
        if isinstance(node, python_ast.FunctionDef)
    ]

    if expected_name not in function_names:
        raise ValueError(
            f"Tool file {path} does not contain a function named '{expected_name}'. "
            f"Found: {function_names}"
        )

    return content


def generate_tools_init(tool_names: list[str]) -> str:
    """Generate tools/__init__.py that imports and wraps tools with @tool."""
    lines = []
    lines.append('"""Auto-generated tool exports."""')
    lines.append("")

    if not tool_names:
        lines.append("")
        return "\n".join(lines)

    lines.append("from langchain_core.tools import tool")
    lines.append("")

    for name in tool_names:
        lines.append(f"from tools.{name} import {name}")

    lines.append("")

    for name in tool_names:
        lines.append(f"{name} = tool({name})")

    lines.append("")

    return "\n".join(lines)


def get_tool_requirements(base_dir: Path) -> str | None:
    """Read tools/requirements.txt if it exists."""
    req_path = base_dir / "tools" / "requirements.txt"
    if req_path.exists():
        return req_path.read_text().strip()
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/python/agentstack-adapter-langchain/tests/test_tools.py -v`

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/python/agentstack-adapter-langchain/
git commit -m "feat: add tool discovery and packaging module"
```

---

### Task 2: Update Adapter and Templates for Real Tools

**Files:**
- Modify: `packages/python/agentstack-adapter-langchain/src/agentstack_adapter_langchain/adapter.py`
- Modify: `packages/python/agentstack-adapter-langchain/src/agentstack_adapter_langchain/templates.py`

- [ ] **Step 1: Update adapter.py**

Replace `packages/python/agentstack-adapter-langchain/src/agentstack_adapter_langchain/adapter.py` with:

```python
"""LangChain/LangGraph framework adapter."""

from pathlib import Path

from agentstack.providers.base import FrameworkAdapter, GeneratedCode, ValidationError
from agentstack.schema.agent import Agent

from agentstack_adapter_langchain.templates import (
    MODEL_PROVIDERS,
    _get_session_store,
    generate_agent_py,
    generate_requirements_txt,
    generate_server_py,
    generate_store_py,
)
from agentstack_adapter_langchain.tools import (
    discover_tools,
    generate_tools_init,
    get_tool_requirements,
    read_tool_file,
)


class LangChainAdapter(FrameworkAdapter):
    """Generates LangGraph agent code + FastAPI harness from an Agent schema."""

    def generate(self, agent: Agent, base_dir: Path | None = None) -> GeneratedCode:
        """Generate deployable LangGraph agent code."""
        # Discover real tools
        found_tools: dict[str, Path] = {}
        missing_tools: list[str] = []
        tool_reqs: str | None = None

        if base_dir:
            found_tools, missing_tools = discover_tools(agent, base_dir)
            tool_reqs = get_tool_requirements(base_dir)
        else:
            # No base_dir — all tools are stubs
            seen = set()
            for skill in agent.skills:
                for tool_name in skill.tools:
                    if tool_name not in seen:
                        seen.add(tool_name)
                        missing_tools.append(tool_name)

        files = {
            "agent.py": generate_agent_py(
                agent,
                found_tool_names=list(found_tools.keys()),
                stub_tool_names=missing_tools,
            ),
            "server.py": generate_server_py(agent),
            "requirements.txt": generate_requirements_txt(agent, tool_reqs),
        }

        # Include real tool files
        if found_tools:
            files["tools/__init__.py"] = generate_tools_init(list(found_tools.keys()))
            for name, path in found_tools.items():
                files[f"tools/{name}.py"] = read_tool_file(path, name)

        # Bundle AsyncSqliteStore for SQLite deployments
        session_store = _get_session_store(agent)
        if session_store and session_store.engine == "sqlite":
            files["store.py"] = generate_store_py()

        return GeneratedCode(files=files, entrypoint="server.py")

    def validate(self, agent: Agent) -> list[ValidationError]:
        """Validate that the agent can be deployed with LangChain."""
        errors = []

        provider_type = agent.model.provider.type
        if provider_type not in MODEL_PROVIDERS:
            supported = ", ".join(MODEL_PROVIDERS.keys())
            errors.append(
                ValidationError(
                    field="model.provider.type",
                    message=f"Unsupported provider '{provider_type}'. Supported: {supported}",
                )
            )

        return errors
```

- [ ] **Step 2: Update templates.py — modify `_generate_tool_stubs`**

Replace the existing `_generate_tool_stubs` function:

```python
def _generate_tool_stubs(stub_tool_names: list[str]) -> str:
    """Generate @tool stub functions for tools without real implementations."""
    tools = []
    for tool_name in stub_tool_names:
        docstring = tool_name.replace("_", " ").title() + "."
        stub = (
            f"@tool\n"
            f"def {tool_name}(input: str) -> str:\n"
            f'    """{docstring}"""\n'
            f'    return f"Stub: {tool_name} called with {{input}}"'
        )
        tools.append(stub)
    return "\n\n".join(tools)
```

- [ ] **Step 3: Update templates.py — modify `generate_agent_py` signature and tool section**

Update the function signature:
```python
def generate_agent_py(agent: Agent, found_tool_names: list[str] | None = None, stub_tool_names: list[str] | None = None) -> str:
```

Replace the tool collection section (the part that builds `tool_stubs`, `tool_names`, `tools_list`):

```python
    if found_tool_names is None:
        found_tool_names = []
    if stub_tool_names is None:
        stub_tool_names = []

    # Build stubs for missing tools
    tool_stubs = _generate_tool_stubs(stub_tool_names)

    # All tool names (real + stub + memory)
    all_tool_names = found_tool_names + stub_tool_names
    tools_list = ", ".join(all_tool_names) if all_tool_names else ""
```

In the code generation section, add the real tool import before stubs:

After the model setup and before the tool stubs, add:
```python
    # Import real tools from tools/ package
    if found_tool_names:
        lines.append("")
        lines.append("# Tools (loaded from tools/ directory)")
        imports = ", ".join(found_tool_names)
        lines.append(f"from tools import {imports}")
```

Keep the stub section but only emit it for stub tools:
```python
    if tool_stubs:
        lines.append("")
        lines.append("# Tool stubs (no implementation found)")
        lines.append(tool_stubs)
```

Make sure `from langchain_core.tools import tool` is only imported when there are stubs (real tools get `@tool` from `tools/__init__.py`). Update the import logic:

```python
    if stub_tool_names:
        lines.append("from langchain_core.tools import tool")
```

But keep the existing logic that also adds this import when `session_store` is present (for memory tools).

- [ ] **Step 4: Update templates.py — modify `generate_requirements_txt` signature**

```python
def generate_requirements_txt(agent: Agent, tool_reqs: str | None = None) -> str:
    """Generate a requirements.txt based on the agent's model provider."""
    provider_type = agent.model.provider.type
    provider_pkg = PROVIDER_PACKAGES.get(provider_type, PROVIDER_PACKAGES["anthropic"])

    session_store = _get_session_store(agent)
    checkpoint_pkg = ""
    if session_store and session_store.engine == "postgres":
        checkpoint_pkg = "\nlanggraph-checkpoint-postgres>=2.0\npsycopg[binary]>=3.0"
    elif session_store and session_store.engine == "sqlite":
        checkpoint_pkg = "\nlanggraph-checkpoint-sqlite>=2.0\naiosqlite>=0.20"

    tool_deps = ""
    if tool_reqs:
        tool_deps = "\n" + tool_reqs

    return dedent(f"""\
        langchain-core>=0.3
        langgraph>=0.2
        {provider_pkg}
        fastapi>=0.115
        uvicorn>=0.34
        sse-starlette>=2.0{checkpoint_pkg}{tool_deps}
    """)
```

- [ ] **Step 5: Run all adapter tests**

Run: `uv run pytest packages/python/agentstack-adapter-langchain/tests/ -v`

Some existing tests may fail because `generate_agent_py` signature changed. Fix them by adding `found_tool_names=[]` and `stub_tool_names=[list of tool names from the fixture agent]` to calls that now need them, OR by relying on the defaults (None → treated as empty lists, which means all tools from skills become stubs via the old path).

Actually, the defaults handle this: `found_tool_names=None` and `stub_tool_names=None` means the function should fall back to extracting tools from the agent's skills and treating them all as stubs. Update the function:

```python
    if found_tool_names is None and stub_tool_names is None:
        # Legacy path: all tools from skills are stubs
        seen = set()
        stub_tool_names = []
        for skill in agent.skills:
            for tool_name in skill.tools:
                if tool_name not in seen:
                    seen.add(tool_name)
                    stub_tool_names.append(tool_name)
        found_tool_names = []
```

This ensures backward compatibility with existing tests.

- [ ] **Step 6: Commit**

```bash
git add packages/python/agentstack-adapter-langchain/
git commit -m "feat: load real tools from tools/ directory, fall back to stubs"
```

---

### Task 3: Update CLI to Pass base_dir

**Files:**
- Modify: `packages/python/agentstack-cli/src/agentstack_cli/commands/apply.py`
- Modify: `packages/python/agentstack-cli/src/agentstack_cli/commands/plan.py`

- [ ] **Step 1: Update apply.py**

Change the `adapter.generate(agent)` call to pass `base_dir`:

```python
    click.echo("Generating code... ", nl=False)
    code = adapter.generate(agent, base_dir=path.parent)
    click.echo("OK")
```

- [ ] **Step 2: Update plan.py (optional — for info display)**

No changes needed — plan doesn't generate code. But it could show discovered tools. Skip for now.

- [ ] **Step 3: Run CLI tests**

Run: `uv run pytest packages/python/agentstack-cli/tests/ -v`

Expected: all tests PASS (existing tests don't use base_dir, adapter falls back to stubs).

- [ ] **Step 4: Commit**

```bash
git add packages/python/agentstack-cli/
git commit -m "feat: pass base_dir to adapter for tool discovery"
```

---

### Task 4: Update Example with Real Tools

**Files:**
- Create: `examples/hello-agent/tools/get_weather.py`
- Create: `examples/hello-agent/tools/get_time.py`
- Create: `examples/hello-agent/tools/requirements.txt`

- [ ] **Step 1: Create real tool implementations**

`examples/hello-agent/tools/get_weather.py`:
```python
import json
from urllib.request import urlopen


def get_weather(city: str) -> str:
    """Get current weather for a city using wttr.in."""
    try:
        url = f"https://wttr.in/{city}?format=j1"
        with urlopen(url) as response:
            data = json.loads(response.read())
            current = data["current_condition"][0]
            temp_c = current["temp_C"]
            desc = current["weatherDesc"][0]["value"]
            humidity = current["humidity"]
            return f"{city}: {desc}, {temp_c}°C, humidity {humidity}%"
    except Exception as e:
        return f"Could not get weather for {city}: {e}"
```

`examples/hello-agent/tools/get_time.py`:
```python
from datetime import datetime, timezone


def get_time(location: str = "UTC") -> str:
    """Get the current UTC time. Location parameter is accepted but UTC is always returned."""
    now = datetime.now(timezone.utc)
    return f"Current UTC time: {now.strftime('%Y-%m-%d %H:%M:%S UTC')}"
```

`examples/hello-agent/tools/requirements.txt`:
```
# No extra deps needed — get_weather uses stdlib urllib
```

- [ ] **Step 2: Verify preview shows real tools**

Run: `uv run python examples/hello-agent/preview.py`

Expected: generated `agent.py` shows `from tools import get_weather, get_time` instead of stub functions. Generated output should include `tools/get_weather.py`, `tools/get_time.py`, and `tools/__init__.py`.

- [ ] **Step 3: Commit**

```bash
git add examples/hello-agent/tools/
git commit -m "feat: add real tool implementations for hello-agent example"
```

---

### Task 5: Full Verification

- [ ] **Step 1: Run all Python tests**

Run: `just test-python`

Expected: all tests pass.

- [ ] **Step 2: Run linting**

Run: `uv run ruff check packages/python/agentstack-adapter-langchain/`

Fix any errors.

- [ ] **Step 3: Deploy and test with real tools**

```bash
cd examples/hello-agent
source .env && export ANTHROPIC_API_KEY
agentstack apply
```

Then test the real tools:
```bash
curl -X POST http://localhost:8080/invoke \
  -H "Content-Type: application/json" \
  -d '{"message": "What is the weather in London?"}'

curl -X POST http://localhost:8080/invoke \
  -H "Content-Type: application/json" \
  -d '{"message": "What time is it?"}'
```

Expected: agent calls real tool implementations and returns actual weather data / time.

- [ ] **Step 4: Destroy**

```bash
agentstack destroy --name hello-agent
```
