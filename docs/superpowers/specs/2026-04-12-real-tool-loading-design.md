# Real Tool Loading — Design Spec

## Overview

Replace stub tool generation with real tool loading from a `tools/` directory. Users write plain Python functions in individual files, the adapter discovers them, wraps them with LangChain's `@tool` decorator, and packages them for deployment. Tools not found on disk fall back to stubs for backward compatibility.

## Decisions

| Decision | Choice |
|----------|--------|
| Tool location | `tools/` directory next to agent definition file |
| Missing tools | Fall back to stubs (backward compatible) |
| File convention | Plain Python function, no `@tool` decorator, no LangChain dependency |
| Function discovery | File name = function name (`tools/get_weather.py` → `get_weather`) |
| Packaging | Copy as `tools/` Python package in generated output |
| Dependencies | `tools/requirements.txt` merged into generated requirements |

## User's Project Layout

```
my-agent/
├── agentstack.yaml
└── tools/
    ├── get_weather.py       # real tool implementation
    ├── get_time.py          # real tool implementation
    └── requirements.txt     # tool dependencies (e.g., requests)
```

## Tool File Convention

A tool file is a plain Python file with one function matching the file name.

```python
# tools/get_weather.py
import requests

def get_weather(city: str) -> str:
    """Get current weather for a city."""
    response = requests.get(f"https://wttr.in/{city}?format=3")
    return response.text
```

Rules:
- File name is the tool name (`get_weather.py` → tool `get_weather`)
- Must contain a function with the same name as the file
- Function must have a docstring (used as LangChain tool description)
- Function must have type hints on parameters (used for LangChain tool schema)
- Any imports at top are the tool's dependencies
- No `@tool` decorator — the adapter adds it
- Helper functions prefixed with `_` are allowed but not exported

## Tool Loading Flow

When `agentstack apply` (or `generate`) runs:

1. CLI resolves the agent definition path and passes `base_dir` to the adapter
2. Adapter scans `base_dir/tools/` for each tool name in `agent.skills[].tools`
3. For each tool name (e.g., `get_weather`):
   - Look for `tools/get_weather.py`
   - If found: validate it contains a `get_weather` function, mark as "real"
   - If not found: mark as "stub"
4. Include real tool files in `GeneratedCode.files` as `tools/{name}.py`
5. Generate `tools/__init__.py` that wraps real tools with `@tool` and re-exports
6. Generate inline stubs in `agent.py` for missing tools (current behavior)
7. If `tools/requirements.txt` exists, merge contents into generated `requirements.txt`

## Generated Output

```
.agentstack/hello-agent/
├── agent.py
├── server.py
├── tools/
│   ├── __init__.py       # auto-generated: imports, wraps with @tool, exports
│   ├── get_weather.py    # copied from user's tools/
│   └── get_time.py       # copied from user's tools/
├── requirements.txt      # includes tool deps
├── Dockerfile
└── store.py              # (if SQLite)
```

### Generated `tools/__init__.py`

```python
"""Auto-generated tool exports."""

from langchain_core.tools import tool

from tools.get_weather import get_weather
from tools.get_time import get_time

get_weather = tool(get_weather)
get_time = tool(get_time)
```

`tool()` as a function preserves the original function's signature and docstring.

### Generated `agent.py`

For real tools, imports from `tools` package:
```python
from tools import get_weather, get_time
```

For stub tools (no file found), generates inline stubs as before:
```python
@tool
def missing_tool(input: str) -> str:
    """Missing Tool."""
    return f"Stub: missing_tool called with {input}"
```

Both real and stub tools are passed to `create_react_agent`.

## File Changes

### New file

```
packages/python/agentstack-adapter-langchain/src/agentstack_adapter_langchain/
└── tools.py              # tool discovery, reading, validation, __init__.py generation
```

**`tools.py` functions:**
- `discover_tools(agent, base_dir) -> tuple[dict[str, Path], list[str]]` — returns (found_tools: name→path, missing_tools: list of names)
- `read_tool_file(path, expected_name) -> str` — read and validate a tool file
- `generate_tools_init(found_tools) -> str` — generate `tools/__init__.py` content
- `get_tool_requirements(base_dir) -> str | None` — read `tools/requirements.txt` if exists

### Modified files

**`adapter.py`:**
- `generate(agent, base_dir=None)` — accepts optional base directory
- Calls tool discovery, includes real tool files and `tools/__init__.py` in output
- Merges tool requirements

**`templates.py`:**
- `generate_agent_py(agent, found_tools, stub_tools)` — imports real tools from `tools` package, generates inline stubs for missing ones
- `_generate_tool_stubs(stub_tools)` — updated to only generate stubs for missing tools

**CLI `apply.py`:**
- Passes `base_dir=path.parent` to `adapter.generate()`

### Test files

```
packages/python/agentstack-adapter-langchain/tests/
├── test_tools.py         # NEW — discovery, reading, validation, __init__.py gen
└── test_templates.py     # update — test with real tools vs stubs mixed
```

## Testing Strategy

### test_tools.py
- `test_discover_found` — tool file exists, returned in found dict
- `test_discover_missing` — tool file doesn't exist, returned in missing list
- `test_discover_mixed` — some found, some missing
- `test_read_tool_file` — reads file, validates function exists
- `test_read_tool_file_missing_function` — file exists but function name doesn't match
- `test_generate_tools_init` — correct imports and `tool()` wrapping
- `test_generate_tools_init_parseable` — generated `__init__.py` passes `ast.parse()`
- `test_get_tool_requirements` — reads requirements file
- `test_get_tool_requirements_missing` — returns None when no file

### test_templates.py (additions)
- `test_agent_py_with_real_tools` — imports from `tools` package
- `test_agent_py_with_mixed_tools` — real tools imported, stubs inlined
- `test_agent_py_with_real_tools_parseable` — passes `ast.parse()`

## What This Spec Does NOT Cover

- Tool testing framework (unit tests for tools)
- Tool versioning or registry
- Remote tool loading (from packages, URLs)
- Tool sandboxing or permission controls
- MCP server tools (separate feature)
