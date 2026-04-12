# LangChain Adapter + Harness — Design Spec

## Overview

Build a LangChain/LangGraph framework adapter that implements the `FrameworkAdapter` ABC. Given an Agent schema, it generates deployable code: a LangGraph agent definition and a FastAPI harness server. This is the first framework adapter for AgentStack.

## Decisions

| Decision | Choice |
|----------|--------|
| Framework target | LangChain core + LangGraph |
| Generated output | Minimal + harness entrypoint (agent.py + server.py + requirements.txt) |
| HTTP framework | FastAPI |
| Streaming | Both — `/invoke` for request-response, `/stream` for SSE |
| Tool handling | Pass-through stubs — user replaces with real implementations |
| Code generation | String templates (f-strings/textwrap.dedent), no Jinja2 |

## Package Structure

```
packages/python/agentstack-adapter-langchain/
├── pyproject.toml
├── src/agentstack_adapter_langchain/
│   ├── __init__.py              # __version__, re-export LangChainAdapter
│   ├── adapter.py               # LangChainAdapter class
│   └── templates.py             # code generation template functions
└── tests/
    ├── test_adapter.py          # generate(), validate() tests
    └── test_templates.py        # template output + ast.parse() validity
```

## Dependencies

**Adapter package dependencies:**
- `agentstack` (core, workspace dep)

The adapter does NOT depend on LangChain. It generates code that uses LangChain. The generated `requirements.txt` lists the runtime dependencies.

## LangChainAdapter

```python
class LangChainAdapter(FrameworkAdapter):
    def generate(self, agent: Agent) -> GeneratedCode:
        """Generate LangGraph agent code + FastAPI harness."""

    def validate(self, agent: Agent) -> list[ValidationError]:
        """Validate that the agent can be deployed with LangChain."""
```

### generate()

Produces a `GeneratedCode` with three files:

- `agent.py` — LangGraph agent definition
- `server.py` — FastAPI harness entrypoint
- `requirements.txt` — runtime dependencies

Uses three internal template functions:
- `_generate_agent_py(agent: Agent) -> str`
- `_generate_server_py(agent: Agent) -> str`
- `_generate_requirements_txt(agent: Agent) -> str`

### validate()

Checks:
- Agent has a model with a supported provider (anthropic or openai)
- Model has a model_name
- Returns `ValidationError` list for any issues found

## Generated Files

### agent.py

The generated agent file:

1. Imports the appropriate LangChain chat model based on provider:
   - `provider.type == "anthropic"` → `from langchain_anthropic import ChatAnthropic`
   - `provider.type == "openai"` → `from langchain_openai import ChatOpenAI`

2. Creates the model with parameters from `Agent.model`:
   ```python
   model = ChatAnthropic(model="claude-sonnet-4-20250514", temperature=0.7)
   ```

3. Generates stub `@tool` functions for each tool in each skill:
   ```python
   @tool
   def lookup_order(order_id: str) -> str:
       """Look up an order by ID."""
       return f"Stub: lookup_order called with {order_id}"
   ```

4. Collects system prompt from all skills' `prompt` fields, concatenated.

5. Creates a LangGraph react agent:
   ```python
   agent = create_react_agent(model, tools, prompt=system_prompt)
   ```

### server.py

The generated FastAPI harness:

- `POST /invoke` — request-response
  - Input: `{"message": "user message", "session_id": "optional"}`
  - Calls `agent.invoke({"messages": [HumanMessage(content=message)]})`
  - Returns: `{"response": "agent response", "session_id": "..."}`

- `POST /stream` — SSE streaming
  - Same input format
  - Uses `agent.astream_events` to stream LangGraph events
  - Returns SSE stream: `data: {"token": "partial"}` per token, `data: {"done": true}` at end
  - Uses `sse-starlette` for SSE formatting

- `GET /health` — health check
  - Returns: `{"status": "ok", "agent": "agent-name", "version": "0.1.0"}`

- Configuration via environment variables:
  - `HOST` (default `0.0.0.0`)
  - `PORT` (default `8000`)
  - `AGENTSTACK_AGENT_NAME` (injected by harness)
  - Model API keys (e.g., `ANTHROPIC_API_KEY`) read by LangChain automatically

- Runs with uvicorn.

### requirements.txt

Generated based on the agent's model provider:

```
langchain-core>=0.3
langgraph>=0.2
fastapi>=0.115
uvicorn>=0.34
sse-starlette>=2.0
```

Plus provider-specific:
- `provider.type == "anthropic"` → `langchain-anthropic>=0.3`
- `provider.type == "openai"` → `langchain-openai>=0.3`

## Model Provider Mapping

| Provider type | LangChain class | Import | Package |
|--------------|----------------|--------|---------|
| `anthropic` | `ChatAnthropic` | `from langchain_anthropic import ChatAnthropic` | `langchain-anthropic` |
| `openai` | `ChatOpenAI` | `from langchain_openai import ChatOpenAI` | `langchain-openai` |
| anything else | — | — | `ValidationError` |

## Root Workspace Changes

Add to root `pyproject.toml`:
- `agentstack-adapter-langchain` in dev-dependencies
- `agentstack-adapter-langchain = { workspace = true }` in `tool.uv.sources`

## Testing Strategy

### test_adapter.py

- `test_generate_returns_generated_code` — verify `generate()` returns `GeneratedCode` with `agent.py`, `server.py`, `requirements.txt`
- `test_generate_entrypoint` — verify entrypoint is `server.py`
- `test_validate_valid_agent` — valid agent returns no errors
- `test_validate_unsupported_provider` — non-anthropic/openai provider returns error
- `test_validate_missing_model_name` — missing model_name returns error
- `test_generate_anthropic_model` — generated code imports `ChatAnthropic`
- `test_generate_openai_model` — generated code imports `ChatOpenAI`

### test_templates.py

- `test_agent_py_parseable` — generated `agent.py` passes `ast.parse()`
- `test_server_py_parseable` — generated `server.py` passes `ast.parse()`
- `test_agent_py_contains_tools` — tools from skills appear as `@tool` functions
- `test_agent_py_contains_system_prompt` — skill prompts appear in system message
- `test_agent_py_model_config` — model parameters (temperature, etc.) are injected
- `test_requirements_anthropic` — requirements include `langchain-anthropic` for anthropic provider
- `test_requirements_openai` — requirements include `langchain-openai` for openai provider

All tests validate generated code structure without actually running it (no LangChain dependency in test environment).

## What This Spec Does NOT Cover

- Tool loading from disk (convention-based or registry-based)
- MCP server integration in generated code
- Session/memory persistence in the harness
- Docker provider (Phase 3)
- CLI commands (Phase 3)
- Workspace support in generated code
- Authentication/authorization on harness endpoints
