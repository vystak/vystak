# OpenAI-Compatible API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace custom `/invoke` and `/stream` endpoints with OpenAI-compatible `/v1/chat/completions`, `/v1/models`, and `/v1/threads/*` endpoints on both agents and the gateway.

**Architecture:** Translation layer approach — add OpenAI-shaped route handlers to the generated agent `server.py` and the gateway `server.py`. These handlers call the same LangGraph internals (agents) or A2A protocol (gateway). Shared Pydantic types live in `agentstack.schema.openai`. Custom REST endpoints (`/invoke`, `/stream`) are removed; A2A stays.

**Tech Stack:** Python, FastAPI, Pydantic v2, LangGraph, httpx, SSE (sse-starlette)

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `packages/python/agentstack/src/agentstack/schema/openai.py` | Create | Shared OpenAI-compatible Pydantic models |
| `packages/python/agentstack/src/agentstack/schema/__init__.py` | Modify | Export new OpenAI types |
| `packages/python/agentstack/tests/test_openai_schema.py` | Create | Tests for OpenAI schema models |
| `packages/python/agentstack-adapter-langchain/src/agentstack_adapter_langchain/templates.py` | Modify | Replace `/invoke`+`/stream` with `/v1/*` routes in generated server code |
| `packages/python/agentstack-adapter-langchain/src/agentstack_adapter_langchain/a2a.py` | Modify | Add `models` field to agent card |
| `packages/python/agentstack-adapter-langchain/tests/test_templates.py` | Modify | Update tests for new endpoints |
| `packages/python/agentstack-adapter-langchain/tests/test_a2a.py` | Modify | Test `models` field in agent card |
| `packages/python/agentstack-gateway/src/agentstack_gateway/server.py` | Modify | Add `/v1/*` routes, remove `/invoke/*`, `/stream/*`, `/proxy/*` |
| `packages/python/agentstack-gateway/src/agentstack_gateway/store.py` | Modify | Add thread-agent binding storage |
| `packages/python/agentstack-gateway/tests/test_server.py` | Modify | Tests for new gateway endpoints, remove old endpoint tests |
| `packages/python/agentstack-chat/src/agentstack_chat/client.py` | Modify | Migrate to `/v1/chat/completions` |
| `packages/python/agentstack-chat/tests/test_client.py` | Create | Tests for migrated client |

---

### Task 1: Shared OpenAI Pydantic Models

**Files:**
- Create: `packages/python/agentstack/src/agentstack/schema/openai.py`
- Modify: `packages/python/agentstack/src/agentstack/schema/__init__.py`
- Create: `packages/python/agentstack/tests/test_openai_schema.py`

- [ ] **Step 1: Write the failing test for OpenAI schema models**

```python
# packages/python/agentstack/tests/test_openai_schema.py
"""Tests for OpenAI-compatible schema models."""

import time

import pytest

from agentstack.schema.openai import (
    ChatCompletionChunk,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatMessage,
    Choice,
    ChunkChoice,
    ChunkDelta,
    CompletionUsage,
    ContentBlock,
    CreateMessageRequest,
    CreateRunRequest,
    CreateThreadRequest,
    ErrorDetail,
    ErrorResponse,
    ModelList,
    ModelObject,
    Run,
    Thread,
    ThreadMessage,
)


class TestModelObject:
    def test_defaults(self):
        m = ModelObject(id="agentstack/test-bot", created=1000)
        assert m.id == "agentstack/test-bot"
        assert m.object == "model"
        assert m.owned_by == "agentstack"

    def test_model_list(self):
        ml = ModelList(data=[
            ModelObject(id="agentstack/a", created=1),
            ModelObject(id="agentstack/b", created=2),
        ])
        assert ml.object == "list"
        assert len(ml.data) == 2


class TestChatCompletion:
    def test_request_defaults(self):
        req = ChatCompletionRequest(
            model="agentstack/test-bot",
            messages=[ChatMessage(role="user", content="hi")],
        )
        assert req.stream is False
        assert req.session_id is None

    def test_request_with_extensions(self):
        req = ChatCompletionRequest(
            model="agentstack/test-bot",
            messages=[ChatMessage(role="user", content="hi")],
            session_id="s1",
            user_id="u1",
            project_id="p1",
        )
        assert req.session_id == "s1"

    def test_response_structure(self):
        resp = ChatCompletionResponse(
            id="chatcmpl-123",
            created=1000,
            model="agentstack/test-bot",
            choices=[Choice(message=ChatMessage(role="assistant", content="hello"))],
            usage=CompletionUsage(prompt_tokens=5, completion_tokens=3, total_tokens=8),
        )
        assert resp.object == "chat.completion"
        assert resp.choices[0].finish_reason == "stop"

    def test_chunk_structure(self):
        chunk = ChatCompletionChunk(
            id="chatcmpl-123",
            created=1000,
            model="agentstack/test-bot",
            choices=[ChunkChoice(delta=ChunkDelta(content="hi"))],
        )
        assert chunk.object == "chat.completion.chunk"
        assert chunk.choices[0].finish_reason is None


class TestThread:
    def test_create_request_optional_model(self):
        req = CreateThreadRequest()
        assert req.model is None

    def test_create_request_with_model(self):
        req = CreateThreadRequest(model="agentstack/test-bot")
        assert req.model == "agentstack/test-bot"

    def test_thread_object(self):
        t = Thread(id="thread-1", created_at=1000)
        assert t.object == "thread"

    def test_message(self):
        msg = ThreadMessage(
            id="msg-1",
            thread_id="thread-1",
            role="user",
            content=[ContentBlock(text="hello")],
            created_at=1000,
        )
        assert msg.object == "thread.message"

    def test_run(self):
        r = Run(
            id="run-1",
            thread_id="thread-1",
            model="agentstack/test-bot",
            status="completed",
            created_at=1000,
            completed_at=1001,
        )
        assert r.object == "thread.run"


class TestError:
    def test_error_response(self):
        err = ErrorResponse(error=ErrorDetail(
            message="Agent not found",
            type="invalid_request_error",
            param="model",
            code="model_not_found",
        ))
        assert err.error.code == "model_not_found"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd packages/python/agentstack && python -m pytest tests/test_openai_schema.py -v`
Expected: FAIL — `ImportError: cannot import name 'ChatCompletionRequest' from 'agentstack.schema.openai'`

- [ ] **Step 3: Implement the OpenAI schema models**

```python
# packages/python/agentstack/src/agentstack/schema/openai.py
"""OpenAI-compatible API schema models.

Shared Pydantic types used by both agent servers and the gateway
to implement OpenAI Chat Completions, Models, and Threads APIs.
"""

from pydantic import BaseModel


# === Models Resource ===

class ModelObject(BaseModel):
    id: str
    object: str = "model"
    created: int
    owned_by: str = "agentstack"


class ModelList(BaseModel):
    object: str = "list"
    data: list[ModelObject]


# === Chat Completions ===

class ChatMessage(BaseModel):
    role: str
    content: str | None = None


class ChatCompletionRequest(BaseModel):
    model: str
    messages: list[ChatMessage]
    stream: bool = False
    # Extension fields
    session_id: str | None = None
    user_id: str | None = None
    project_id: str | None = None


class CompletionUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class Choice(BaseModel):
    index: int = 0
    message: ChatMessage
    finish_reason: str = "stop"


class ChatCompletionResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: list[Choice]
    usage: CompletionUsage | None = None


class ChunkDelta(BaseModel):
    role: str | None = None
    content: str | None = None


class ChunkChoice(BaseModel):
    index: int = 0
    delta: ChunkDelta
    finish_reason: str | None = None


class ChatCompletionChunk(BaseModel):
    id: str
    object: str = "chat.completion.chunk"
    created: int
    model: str
    choices: list[ChunkChoice]
    x_agentstack: dict | None = None


# === Threads API ===

class CreateThreadRequest(BaseModel):
    model: str | None = None
    metadata: dict = {}


class Thread(BaseModel):
    id: str
    object: str = "thread"
    created_at: int
    metadata: dict = {}


class ContentBlock(BaseModel):
    type: str = "text"
    text: str


class CreateMessageRequest(BaseModel):
    role: str
    content: str


class ThreadMessage(BaseModel):
    id: str
    object: str = "thread.message"
    thread_id: str
    role: str
    content: list[ContentBlock]
    created_at: int


class CreateRunRequest(BaseModel):
    model: str
    stream: bool = False


class Run(BaseModel):
    id: str
    object: str = "thread.run"
    thread_id: str
    model: str
    status: str
    created_at: int
    completed_at: int | None = None


# === Error Response ===

class ErrorDetail(BaseModel):
    message: str
    type: str
    param: str | None = None
    code: str


class ErrorResponse(BaseModel):
    error: ErrorDetail
```

- [ ] **Step 4: Update `__init__.py` to export new types**

Add to the end of `packages/python/agentstack/src/agentstack/schema/__init__.py`:

```python
from agentstack.schema.openai import (
    ChatCompletionChunk,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatMessage,
    Choice,
    ChunkChoice,
    ChunkDelta,
    CompletionUsage,
    ContentBlock,
    CreateMessageRequest,
    CreateRunRequest,
    CreateThreadRequest,
    ErrorDetail,
    ErrorResponse,
    ModelList,
    ModelObject,
    Run,
    Thread,
    ThreadMessage,
)
```

Add these names to the `__all__` list as well.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd packages/python/agentstack && python -m pytest tests/test_openai_schema.py -v`
Expected: All 11 tests PASS

- [ ] **Step 6: Commit**

```bash
git add packages/python/agentstack/src/agentstack/schema/openai.py packages/python/agentstack/src/agentstack/schema/__init__.py packages/python/agentstack/tests/test_openai_schema.py
git commit -m "feat: add OpenAI-compatible Pydantic schema models"
```

---

### Task 2: Agent Card — Add `models` Field

**Files:**
- Modify: `packages/python/agentstack-adapter-langchain/src/agentstack_adapter_langchain/a2a.py`
- Modify: `packages/python/agentstack-adapter-langchain/tests/test_a2a.py`

- [ ] **Step 1: Write the failing test**

Add to `TestAgentCardCode` in `packages/python/agentstack-adapter-langchain/tests/test_a2a.py`:

```python
def test_models_field_in_card(self, agent):
    code = generate_agent_card_code(agent)
    assert '"models"' in code
    assert '"agentstack/test-bot"' in code
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd packages/python/agentstack-adapter-langchain && python -m pytest tests/test_a2a.py::TestAgentCardCode::test_models_field_in_card -v`
Expected: FAIL — `AssertionError: '"models"' not in code`

- [ ] **Step 3: Add `models` field to agent card generation**

In `packages/python/agentstack-adapter-langchain/src/agentstack_adapter_langchain/a2a.py`, in `generate_agent_card_code()`, add after the `"skills"` list closing `"    ],"`  (before the closing `"}"` of AGENT_CARD):

```python
    lines.append(f'    "models": ["agentstack/{agent.name}"],')
```

This goes after line 29 (`lines.append("    ],")`) and before line 30 (`lines.append("}")`).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd packages/python/agentstack-adapter-langchain && python -m pytest tests/test_a2a.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add packages/python/agentstack-adapter-langchain/src/agentstack_adapter_langchain/a2a.py packages/python/agentstack-adapter-langchain/tests/test_a2a.py
git commit -m "feat: add models field to A2A agent card"
```

---

### Task 3: Generated Server — Replace `/invoke` and `/stream` with `/v1/chat/completions`

**Files:**
- Modify: `packages/python/agentstack-adapter-langchain/src/agentstack_adapter_langchain/templates.py`
- Modify: `packages/python/agentstack-adapter-langchain/tests/test_templates.py`

This is the largest task. The `generate_server_py()` function (lines 322-663) needs to:
1. Remove `InvokeRequest`, `InvokeResponse`, `UsageInfo` model definitions
2. Remove `/invoke` and `/stream` route handlers
3. Add import of shared types from `agentstack.schema.openai`
4. Add `/v1/models`, `/v1/chat/completions`, `/v1/threads/*` route handlers

- [ ] **Step 1: Write failing tests for new endpoints in generated server code**

Replace the server-related tests in `packages/python/agentstack-adapter-langchain/tests/test_templates.py`. Add/modify `TestGenerateServerPy`:

```python
class TestGenerateServerPy:
    def test_parseable(self, anthropic_agent):
        code = generate_server_py(anthropic_agent)
        python_ast.parse(code)

    def test_has_health(self, anthropic_agent):
        code = generate_server_py(anthropic_agent)
        assert '"/health"' in code

    def test_has_v1_models(self, anthropic_agent):
        code = generate_server_py(anthropic_agent)
        assert '"/v1/models"' in code
        assert "agentstack/test-bot" in code

    def test_has_v1_chat_completions(self, anthropic_agent):
        code = generate_server_py(anthropic_agent)
        assert '"/v1/chat/completions"' in code

    def test_has_v1_threads(self, anthropic_agent):
        code = generate_server_py(anthropic_agent)
        assert '"/v1/threads"' in code
        assert '"/v1/threads/{thread_id}/messages"' in code
        assert '"/v1/threads/{thread_id}/runs"' in code

    def test_no_invoke_endpoint(self, anthropic_agent):
        code = generate_server_py(anthropic_agent)
        assert '"/invoke"' not in code

    def test_no_stream_endpoint(self, anthropic_agent):
        code = generate_server_py(anthropic_agent)
        assert '"/stream"' not in code

    def test_no_invoke_request_model(self, anthropic_agent):
        code = generate_server_py(anthropic_agent)
        assert "class InvokeRequest" not in code
        assert "class InvokeResponse" not in code

    def test_imports_openai_schema(self, anthropic_agent):
        code = generate_server_py(anthropic_agent)
        assert "from agentstack.schema.openai import" in code

    def test_chat_completions_streaming(self, anthropic_agent):
        code = generate_server_py(anthropic_agent)
        assert "chat.completion.chunk" in code
        assert "[DONE]" in code

    def test_openai_error_format(self, anthropic_agent):
        code = generate_server_py(anthropic_agent)
        assert "ErrorResponse" in code
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd packages/python/agentstack-adapter-langchain && python -m pytest tests/test_templates.py::TestGenerateServerPy -v`
Expected: Multiple FAIL — missing `/v1/models`, `/v1/chat/completions`, etc.

- [ ] **Step 3: Rewrite `generate_server_py()` in `templates.py`**

Replace the entire `generate_server_py()` function (lines 322-663). The function keeps the same structure (4 cases for persistent/MCP combinations) but replaces the endpoint generation:

```python
def generate_server_py(agent: Agent) -> str:
    """Generate a FastAPI harness server file."""
    session_store = _get_session_store(agent)
    uses_persistent = session_store and session_store.engine in ("postgres", "sqlite")
    has_mcp = _has_mcp_servers(agent)

    if uses_persistent:
        saver_class = "AsyncPostgresSaver" if session_store.engine == "postgres" else "AsyncSqliteSaver"
        saver_module = "postgres.aio" if session_store.engine == "postgres" else "sqlite.aio"
        store_class = "AsyncPostgresStore" if session_store.engine == "postgres" else "AsyncSqliteStore"
        if session_store.engine == "postgres":
            store_import = "from langgraph.store.postgres.aio import AsyncPostgresStore"
        else:
            store_import = "from store import AsyncSqliteStore"
        agent_ref = "_agent"
    else:
        agent_ref = "_agent"

    model_id = f"agentstack/{agent.name}"

    lines = []
    lines.append(f'"""AgentStack harness server for {agent.name}."""')
    lines.append("")
    lines.append("import json")
    lines.append("import os")
    lines.append("import time")
    lines.append("import uuid")
    lines.append("")
    lines.append("from fastapi import FastAPI, Request")
    lines.append("from fastapi.responses import JSONResponse")
    lines.append("from pydantic import BaseModel")
    lines.append("from sse_starlette.sse import EventSourceResponse")
    lines.append("")
    lines.append("from agentstack.schema.openai import (")
    lines.append("    ChatCompletionChunk,")
    lines.append("    ChatCompletionRequest,")
    lines.append("    ChatCompletionResponse,")
    lines.append("    ChatMessage,")
    lines.append("    Choice,")
    lines.append("    ChunkChoice,")
    lines.append("    ChunkDelta,")
    lines.append("    CompletionUsage,")
    lines.append("    ContentBlock,")
    lines.append("    CreateMessageRequest,")
    lines.append("    CreateRunRequest,")
    lines.append("    CreateThreadRequest,")
    lines.append("    ErrorDetail,")
    lines.append("    ErrorResponse,")
    lines.append("    ModelList,")
    lines.append("    ModelObject,")
    lines.append("    Run,")
    lines.append("    Thread,")
    lines.append("    ThreadMessage,")
    lines.append(")")
    lines.append("")

    # === Lifespan setup (same 4 cases as before) ===
    # [KEEP the existing lifespan generation code from lines 352-446 UNCHANGED]
    # This includes: persistent+MCP, persistent+no MCP, MCP only, neither

    if uses_persistent:
        lines.append("from contextlib import asynccontextmanager")
        lines.append(f"from langgraph.checkpoint.{saver_module} import {saver_class}")
        lines.append(store_import)
        if has_mcp:
            lines.append("from langchain_mcp_adapters.client import MultiServerMCPClient")
        lines.append("")
        if has_mcp:
            lines.append("from agent import create_agent, DB_URI, MCP_SERVERS")
        else:
            lines.append("from agent import create_agent, DB_URI")
        lines.append("")
        lines.append("")
        lines.append("_agent = None")
        lines.append("_store = None")
        if has_mcp:
            lines.append("_mcp_client = None")
        lines.append("")
        lines.append("")
        lines.append("@asynccontextmanager")
        lines.append("async def lifespan(app):")
        if has_mcp:
            lines.append("    global _agent, _store, _mcp_client")
        else:
            lines.append("    global _agent, _store")
        if has_mcp:
            lines.append("    _mcp_client = MultiServerMCPClient(MCP_SERVERS)")
            lines.append("    mcp_tools = await _mcp_client.get_tools()")
            if session_store.engine == "postgres":
                lines.append(f"    async with {saver_class}.from_conn_string(DB_URI) as checkpointer, \\")
                lines.append(f"               {store_class}.from_conn_string(DB_URI) as store:")
            else:
                lines.append(f"    async with {saver_class}.from_conn_string(DB_URI) as checkpointer, \\")
                lines.append(f"               {store_class}.from_conn_string(DB_URI.replace('.db', '_store.db')) as store:")
            lines.append("        await checkpointer.setup()")
            lines.append("        await store.setup()")
            lines.append("        _store = store")
            lines.append("        _agent = create_agent(checkpointer, store=store, mcp_tools=mcp_tools)")
            lines.append("        yield")
        else:
            if session_store.engine == "postgres":
                lines.append("    import asyncio as _asyncio")
                lines.append("    for _attempt in range(30):")
                lines.append("        try:")
                lines.append(f"            async with {saver_class}.from_conn_string(DB_URI) as checkpointer, \\")
                lines.append(f"                       {store_class}.from_conn_string(DB_URI) as store:")
                lines.append("                await checkpointer.setup()")
                lines.append("                await store.setup()")
                lines.append("                _store = store")
                lines.append("                _agent = create_agent(checkpointer, store=store)")
                lines.append("                yield")
                lines.append("                return")
                lines.append("        except Exception as _e:")
                lines.append("            if _attempt == 29:")
                lines.append("                raise")
                lines.append("            await _asyncio.sleep(2)")
            else:
                lines.append(f"    async with {saver_class}.from_conn_string(DB_URI) as checkpointer, \\")
                lines.append(f"               {store_class}.from_conn_string(DB_URI.replace('.db', '_store.db')) as store:")
                lines.append("        await checkpointer.setup()")
                lines.append("        await store.setup()")
                lines.append("        _store = store")
                lines.append("        _agent = create_agent(checkpointer, store=store)")
                lines.append("        yield")
        lines.append("")
        lines.append("")
        lines.append(f'app = FastAPI(title="{agent.name}", lifespan=lifespan)')
    elif has_mcp:
        lines.append("from contextlib import asynccontextmanager")
        lines.append("from langchain_mcp_adapters.client import MultiServerMCPClient")
        lines.append("")
        lines.append("from agent import create_agent, MCP_SERVERS")
        lines.append("")
        lines.append("")
        lines.append("_agent = None")
        lines.append("_mcp_client = None")
        lines.append("")
        lines.append("")
        lines.append("@asynccontextmanager")
        lines.append("async def lifespan(app):")
        lines.append("    global _agent, _mcp_client")
        lines.append("    _mcp_client = MultiServerMCPClient(MCP_SERVERS)")
        lines.append("    _agent = create_agent(mcp_tools=await _mcp_client.get_tools())")
        lines.append("    yield")
        lines.append("")
        lines.append("")
        lines.append(f'app = FastAPI(title="{agent.name}", lifespan=lifespan)')
    else:
        lines.append("from agent import agent")
        lines.append("_agent = agent  # alias for A2A handlers")
        lines.append("")
        lines.append(f'app = FastAPI(title="{agent.name}")')

    lines.append("")
    lines.append(f'AGENT_NAME = os.environ.get("AGENTSTACK_AGENT_NAME", "{agent.name}")')
    lines.append(f'MODEL_ID = "agentstack/{agent.name}"')
    lines.append('HOST = os.environ.get("HOST", "0.0.0.0")')
    lines.append('PORT = int(os.environ.get("PORT", "8000"))')
    lines.append("")
    lines.append("")

    # === Memory helpers (only for persistent stores, same as before) ===
    if uses_persistent:
        lines.append("async def recall_memories(store, message, user_id=None, project_id=None):")
        lines.append("    memories = []")
        lines.append("    if user_id:")
        lines.append('        results = await store.asearch(("user", user_id, "memories"), query=message, limit=5)')
        lines.append("        for item in results:")
        lines.append('            memories.append(f"[{item.key}] {item.value.get(\'data\', \'\')} (scope: user)")')
        lines.append("    if project_id:")
        lines.append('        results = await store.asearch(("project", project_id, "memories"), query=message, limit=5)')
        lines.append("        for item in results:")
        lines.append('            memories.append(f"[{item.key}] {item.value.get(\'data\', \'\')} (scope: project)")')
        lines.append('    results = await store.asearch(("global", "memories"), query=message, limit=5)')
        lines.append("    for item in results:")
        lines.append('        memories.append(f"[{item.key}] {item.value.get(\'data\', \'\')} (scope: global)")')
        lines.append("    return memories")
        lines.append("")
        lines.append("")
        lines.append("async def handle_memory_actions(store, messages, user_id=None, project_id=None):")
        lines.append("    import uuid as _uuid")
        lines.append("    for msg in messages:")
        lines.append("        if hasattr(msg, 'content') and isinstance(msg.content, str):")
        lines.append('            if msg.content.startswith("__SAVE_MEMORY__|"):')
        lines.append('                parts = msg.content.split("|", 2)')
        lines.append("                if len(parts) == 3:")
        lines.append("                    scope, content = parts[1], parts[2]")
        lines.append("                    memory_id = str(_uuid.uuid4())[:8]")
        lines.append('                    if scope == "user" and user_id:')
        lines.append('                        await store.aput(("user", user_id, "memories"), memory_id, {"data": content})')
        lines.append('                    elif scope == "project" and project_id:')
        lines.append('                        await store.aput(("project", project_id, "memories"), memory_id, {"data": content})')
        lines.append('                    elif scope == "global":')
        lines.append('                        await store.aput(("global", "memories"), memory_id, {"data": content})')
        lines.append('            elif msg.content.startswith("__FORGET_MEMORY__|"):')
        lines.append('                memory_id = msg.content.split("|", 1)[1]')
        lines.append("                if user_id:")
        lines.append('                    await store.adelete(("user", user_id, "memories"), memory_id)')
        lines.append("                if project_id:")
        lines.append('                    await store.adelete(("project", project_id, "memories"), memory_id)')
        lines.append('                await store.adelete(("global", "memories"), memory_id)')
        lines.append("")
        lines.append("")

    # === OpenAI Error Handler ===
    lines.append("@app.exception_handler(Exception)")
    lines.append("async def openai_error_handler(request: Request, exc: Exception):")
    lines.append('    if request.url.path.startswith("/v1/"):')
    lines.append("        return JSONResponse(")
    lines.append("            status_code=500,")
    lines.append('            content=ErrorResponse(error=ErrorDetail(')
    lines.append('                message=str(exc),')
    lines.append('                type="server_error",')
    lines.append('                code="internal_error",')
    lines.append("            )).model_dump(),")
    lines.append("        )")
    lines.append("    raise exc")
    lines.append("")
    lines.append("")

    # === /health (unchanged) ===
    lines.append('@app.get("/health")')
    lines.append("async def health():")
    lines.append('    return {"status": "ok", "agent": AGENT_NAME, "version": "0.1.0"}')
    lines.append("")
    lines.append("")

    # === /v1/models ===
    lines.append('@app.get("/v1/models")')
    lines.append("async def list_models():")
    lines.append("    return ModelList(data=[")
    lines.append("        ModelObject(id=MODEL_ID, created=int(time.time())),")
    lines.append("    ]).model_dump()")
    lines.append("")
    lines.append("")

    # === /v1/chat/completions (non-streaming) ===
    lines.append('@app.post("/v1/chat/completions")')
    lines.append("async def chat_completions(request: ChatCompletionRequest):")
    lines.append("    session_id = request.session_id or str(uuid.uuid4())")
    lines.append("    user_id = request.user_id")
    lines.append("    project_id = request.project_id")
    lines.append('    config = {"configurable": {')
    lines.append('        "thread_id": session_id,')
    lines.append('        "user_id": user_id,')
    lines.append('        "project_id": project_id,')
    lines.append('        "agent_name": AGENT_NAME,')
    lines.append("    }}")
    lines.append("")
    lines.append("    # Extract the last user message")
    lines.append("    last_msg = request.messages[-1].content or ''")
    lines.append("")

    if uses_persistent:
        lines.append("    memories = await recall_memories(_store, last_msg, user_id=user_id, project_id=project_id)")
        lines.append("    messages = []")
        lines.append("    if memories:")
        lines.append('        memory_text = "Relevant memories:\\n" + "\\n".join(memories)')
        lines.append('        messages.append(("system", memory_text))')
        lines.append('    messages.append(("user", last_msg))')
    else:
        lines.append('    messages = [("user", last_msg)]')

    lines.append("")
    lines.append("    if request.stream:")
    lines.append("        return await _stream_chat_completions(messages, config, session_id)")
    lines.append("")
    lines.append(f"    result = await {agent_ref}.ainvoke(")
    lines.append('        {"messages": messages},')
    lines.append('        config=config,')
    lines.append("    )")
    lines.append('    content = result["messages"][-1].content')
    lines.append("    if isinstance(content, list):")
    lines.append("        response_text = ''.join(")
    lines.append('            block.get("text", "") if isinstance(block, dict) else str(block)')
    lines.append("            for block in content")
    lines.append("        )")
    lines.append("    else:")
    lines.append("        response_text = str(content)")
    if uses_persistent:
        lines.append("    await handle_memory_actions(_store, result['messages'], user_id=user_id, project_id=project_id)")
    lines.append("")
    lines.append("    last = result['messages'][-1]")
    lines.append("    usage = None")
    lines.append("    if hasattr(last, 'usage_metadata') and last.usage_metadata:")
    lines.append("        um = last.usage_metadata")
    lines.append("        usage = CompletionUsage(")
    lines.append("            prompt_tokens=um.get('input_tokens', 0),")
    lines.append("            completion_tokens=um.get('output_tokens', 0),")
    lines.append("            total_tokens=um.get('total_tokens', 0),")
    lines.append("        )")
    lines.append("")
    lines.append("    return ChatCompletionResponse(")
    lines.append('        id=f"chatcmpl-{uuid.uuid4().hex[:12]}",')
    lines.append("        created=int(time.time()),")
    lines.append("        model=MODEL_ID,")
    lines.append("        choices=[Choice(message=ChatMessage(role='assistant', content=response_text))],")
    lines.append("        usage=usage,")
    lines.append("    ).model_dump()")
    lines.append("")
    lines.append("")

    # === Streaming helper ===
    lines.append("async def _stream_chat_completions(messages, config, session_id):")
    lines.append('    completion_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"')
    lines.append("")
    lines.append("    async def event_generator():")
    lines.append("        usage = {}")
    lines.append(f"        async for chunk in {agent_ref}.astream(")
    lines.append('            {"messages": messages},')
    lines.append('            config=config,')
    lines.append('            stream_mode=["messages", "custom"],')
    lines.append("        ):")
    lines.append('            if chunk[0] == "custom":')
    lines.append("                oai_chunk = ChatCompletionChunk(")
    lines.append("                    id=completion_id,")
    lines.append("                    created=int(time.time()),")
    lines.append("                    model=MODEL_ID,")
    lines.append("                    choices=[ChunkChoice(delta=ChunkDelta())],")
    lines.append("                    x_agentstack=chunk[1],")
    lines.append("                ).model_dump()")
    lines.append('                yield {"data": json.dumps(oai_chunk)}')
    lines.append('            elif chunk[0] == "messages":')
    lines.append('                msg, metadata = chunk[1]')
    lines.append('                if msg.type == "AIMessageChunk":')
    lines.append("                    if msg.content:")
    lines.append("                        text = msg.content if isinstance(msg.content, str) else ''")
    lines.append("                        if not text and isinstance(msg.content, list):")
    lines.append("                            for block in msg.content:")
    lines.append("                                if isinstance(block, dict) and block.get('type') == 'text':")
    lines.append("                                    text += block.get('text', '')")
    lines.append("                        if text:")
    lines.append("                            oai_chunk = ChatCompletionChunk(")
    lines.append("                                id=completion_id,")
    lines.append("                                created=int(time.time()),")
    lines.append("                                model=MODEL_ID,")
    lines.append("                                choices=[ChunkChoice(delta=ChunkDelta(content=text))],")
    lines.append("                            ).model_dump()")
    lines.append('                            yield {"data": json.dumps(oai_chunk)}')
    lines.append("                    if msg.tool_call_chunks:")
    lines.append("                        for tc in msg.tool_call_chunks:")
    lines.append("                            if tc.get('name'):")
    lines.append("                                oai_chunk = ChatCompletionChunk(")
    lines.append("                                    id=completion_id,")
    lines.append("                                    created=int(time.time()),")
    lines.append("                                    model=MODEL_ID,")
    lines.append("                                    choices=[ChunkChoice(delta=ChunkDelta())],")
    lines.append('                                    x_agentstack={"type": "tool_call_start", "tool": tc["name"]},')
    lines.append("                                ).model_dump()")
    lines.append('                                yield {"data": json.dumps(oai_chunk)}')
    lines.append("                    if hasattr(msg, 'usage_metadata') and msg.usage_metadata:")
    lines.append("                        um = msg.usage_metadata")
    lines.append("                        inp = um.get('input_tokens', 0)")
    lines.append("                        out = um.get('output_tokens', 0)")
    lines.append("                        if inp or out:")
    lines.append('                            usage = {"prompt_tokens": inp, "completion_tokens": out, "total_tokens": um.get("total_tokens", 0)}')
    lines.append('                elif msg.type == "tool":')
    lines.append("                    tool_name = getattr(msg, 'name', 'tool')")
    lines.append("                    output_str = str(msg.content)[:200] if msg.content else ''")
    lines.append("                    oai_chunk = ChatCompletionChunk(")
    lines.append("                        id=completion_id,")
    lines.append("                        created=int(time.time()),")
    lines.append("                        model=MODEL_ID,")
    lines.append("                        choices=[ChunkChoice(delta=ChunkDelta())],")
    lines.append('                        x_agentstack={"type": "tool_result", "tool": tool_name, "result": output_str},')
    lines.append("                    ).model_dump()")
    lines.append('                    yield {"data": json.dumps(oai_chunk)}')
    lines.append("        # Final chunk with finish_reason")
    lines.append("        final = ChatCompletionChunk(")
    lines.append("            id=completion_id,")
    lines.append("            created=int(time.time()),")
    lines.append("            model=MODEL_ID,")
    lines.append('            choices=[ChunkChoice(delta=ChunkDelta(), finish_reason="stop")],')
    lines.append("        ).model_dump()")
    lines.append('        yield {"data": json.dumps(final)}')
    lines.append('        yield {"data": "[DONE]"}')
    lines.append("")
    lines.append("    return EventSourceResponse(event_generator())")
    lines.append("")
    lines.append("")

    # === /v1/threads ===
    lines.append("# Thread storage (in-memory, keyed by thread_id)")
    lines.append("_threads: dict[str, dict] = {}")
    lines.append("")
    lines.append("")
    lines.append('@app.post("/v1/threads")')
    lines.append("async def create_thread(request: CreateThreadRequest):")
    lines.append("    thread_id = str(uuid.uuid4())")
    lines.append("    now = int(time.time())")
    lines.append("    thread = Thread(id=thread_id, created_at=now, metadata=request.metadata)")
    lines.append("    _threads[thread_id] = {'thread': thread.model_dump(), 'messages': [], 'model': request.model}")
    lines.append("    return thread.model_dump()")
    lines.append("")
    lines.append("")

    # === /v1/threads/{thread_id}/messages ===
    lines.append('@app.post("/v1/threads/{thread_id}/messages")')
    lines.append("async def add_thread_message(thread_id: str, request: CreateMessageRequest):")
    lines.append("    if thread_id not in _threads:")
    lines.append("        return JSONResponse(status_code=404, content=ErrorResponse(error=ErrorDetail(")
    lines.append('            message=f"Thread \'{thread_id}\' not found", type="invalid_request_error", code="thread_not_found",')
    lines.append("        )).model_dump())")
    lines.append("    msg_id = f'msg-{uuid.uuid4().hex[:12]}'")
    lines.append("    msg = ThreadMessage(")
    lines.append("        id=msg_id, thread_id=thread_id, role=request.role,")
    lines.append("        content=[ContentBlock(text=request.content)], created_at=int(time.time()),")
    lines.append("    )")
    lines.append("    _threads[thread_id]['messages'].append(msg.model_dump())")
    lines.append("    return msg.model_dump()")
    lines.append("")
    lines.append("")
    lines.append('@app.get("/v1/threads/{thread_id}/messages")')
    lines.append("async def list_thread_messages(thread_id: str):")
    lines.append("    if thread_id not in _threads:")
    lines.append("        return JSONResponse(status_code=404, content=ErrorResponse(error=ErrorDetail(")
    lines.append('            message=f"Thread \'{thread_id}\' not found", type="invalid_request_error", code="thread_not_found",')
    lines.append("        )).model_dump())")
    lines.append('    return {"object": "list", "data": _threads[thread_id]["messages"]}')
    lines.append("")
    lines.append("")

    # === /v1/threads/{thread_id}/runs ===
    lines.append('@app.post("/v1/threads/{thread_id}/runs")')
    lines.append("async def create_run(thread_id: str, request: CreateRunRequest):")
    lines.append("    if thread_id not in _threads:")
    lines.append("        return JSONResponse(status_code=404, content=ErrorResponse(error=ErrorDetail(")
    lines.append('            message=f"Thread \'{thread_id}\' not found", type="invalid_request_error", code="thread_not_found",')
    lines.append("        )).model_dump())")
    lines.append("    run_id = f'run-{uuid.uuid4().hex[:12]}'")
    lines.append("    now = int(time.time())")
    lines.append("    # Get last user message from thread")
    lines.append("    thread_msgs = _threads[thread_id]['messages']")
    lines.append("    user_msgs = [m for m in thread_msgs if m['role'] == 'user']")
    lines.append("    if not user_msgs:")
    lines.append("        return JSONResponse(status_code=400, content=ErrorResponse(error=ErrorDetail(")
    lines.append('            message="No user messages in thread", type="invalid_request_error", code="invalid_value",')
    lines.append("        )).model_dump())")
    lines.append("    last_content = user_msgs[-1]['content'][0]['text']")
    lines.append('    config = {"configurable": {"thread_id": thread_id, "agent_name": AGENT_NAME}}')
    lines.append("")
    lines.append("    try:")
    lines.append(f"        result = await {agent_ref}.ainvoke(")
    lines.append('            {"messages": [("user", last_content)]},')
    lines.append("            config=config,")
    lines.append("        )")
    lines.append('        content = result["messages"][-1].content')
    lines.append("        if isinstance(content, list):")
    lines.append("            response_text = ''.join(")
    lines.append('                block.get("text", "") if isinstance(block, dict) else str(block)')
    lines.append("                for block in content")
    lines.append("            )")
    lines.append("        else:")
    lines.append("            response_text = str(content)")
    lines.append("        # Store assistant response in thread")
    lines.append("        asst_msg = ThreadMessage(")
    lines.append(f"            id=f'msg-{{uuid.uuid4().hex[:12]}}', thread_id=thread_id, role='assistant',")
    lines.append("            content=[ContentBlock(text=response_text)], created_at=int(time.time()),")
    lines.append("        )")
    lines.append("        _threads[thread_id]['messages'].append(asst_msg.model_dump())")
    lines.append("        return Run(")
    lines.append("            id=run_id, thread_id=thread_id, model=MODEL_ID,")
    lines.append('            status="completed", created_at=now, completed_at=int(time.time()),')
    lines.append("        ).model_dump()")
    lines.append("    except Exception as exc:")
    lines.append("        return Run(")
    lines.append("            id=run_id, thread_id=thread_id, model=MODEL_ID,")
    lines.append('            status="failed", created_at=now,')
    lines.append("        ).model_dump()")
    lines.append("")
    lines.append("")

    # A2A Protocol (unchanged)
    lines.append(generate_task_manager_code())
    lines.append(generate_agent_card_code(agent))
    lines.append(generate_a2a_handler_code(agent))

    lines.append('if __name__ == "__main__":')
    lines.append("    import uvicorn")
    lines.append("")
    lines.append("    uvicorn.run(app, host=HOST, port=PORT)")
    lines.append("")

    return "\n".join(lines)
```

- [ ] **Step 4: Update existing tests that reference old endpoints**

In `test_templates.py`, update any tests that assert presence of `"/invoke"` or `"/stream"` or `InvokeRequest`/`InvokeResponse`. Replace them with the new assertions from Step 1. Also update `TestServerMemory` tests to verify memory recall/actions still work within the new `/v1/chat/completions` handler — the memory logic is identical, just called from a different route.

- [ ] **Step 5: Run all adapter tests**

Run: `cd packages/python/agentstack-adapter-langchain && python -m pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add packages/python/agentstack-adapter-langchain/src/agentstack_adapter_langchain/templates.py packages/python/agentstack-adapter-langchain/tests/test_templates.py
git commit -m "feat: replace /invoke and /stream with OpenAI-compatible /v1/ endpoints in generated server"
```

---

### Task 4: Gateway — Add `/v1/*` Routes and Remove Old Proxy Endpoints

**Files:**
- Modify: `packages/python/agentstack-gateway/src/agentstack_gateway/server.py`
- Modify: `packages/python/agentstack-gateway/src/agentstack_gateway/store.py`
- Modify: `packages/python/agentstack-gateway/tests/test_server.py`

- [ ] **Step 1: Write failing tests for new gateway endpoints**

Add to `packages/python/agentstack-gateway/tests/test_server.py`:

```python
class TestV1Models:
    def test_empty_models(self):
        response = client.get("/v1/models")
        assert response.status_code == 200
        data = response.json()
        assert data["object"] == "list"
        assert data["data"] == []

    def test_models_after_registration(self):
        client.post("/register", json={
            "name": "test-bot",
            "url": "http://test-bot:8000",
        })
        response = client.get("/v1/models")
        data = response.json()
        assert len(data["data"]) == 1
        assert data["data"][0]["id"] == "agentstack/test-bot"
        assert data["data"][0]["object"] == "model"
        assert data["data"][0]["owned_by"] == "agentstack"


class TestV1ChatCompletions:
    def test_unknown_model_returns_404(self):
        response = client.post("/v1/chat/completions", json={
            "model": "agentstack/nonexistent",
            "messages": [{"role": "user", "content": "hi"}],
        })
        assert response.status_code == 404
        data = response.json()
        assert data["error"]["code"] == "model_not_found"

    def test_missing_model_prefix(self):
        """Model field must start with agentstack/."""
        response = client.post("/v1/chat/completions", json={
            "model": "nonexistent",
            "messages": [{"role": "user", "content": "hi"}],
        })
        assert response.status_code == 404


class TestV1Threads:
    def test_create_thread(self):
        response = client.post("/v1/threads", json={})
        assert response.status_code == 200
        data = response.json()
        assert data["object"] == "thread"
        assert "id" in data

    def test_create_thread_with_model(self):
        client.post("/register", json={
            "name": "test-bot",
            "url": "http://test-bot:8000",
        })
        response = client.post("/v1/threads", json={"model": "agentstack/test-bot"})
        assert response.status_code == 200

    def test_thread_not_found(self):
        response = client.get("/v1/threads/nonexistent/messages")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "thread_not_found"


class TestOldEndpointsRemoved:
    def test_invoke_removed(self):
        response = client.post("/invoke/test-bot", json={"message": "hi"})
        assert response.status_code == 404 or response.status_code == 405

    def test_stream_removed(self):
        response = client.post("/stream/test-bot", json={"message": "hi"})
        assert response.status_code == 404 or response.status_code == 405

    def test_proxy_invoke_removed(self):
        response = client.post("/proxy/test-bot/invoke", json={"message": "hi"})
        assert response.status_code == 404 or response.status_code == 405

    def test_proxy_stream_removed(self):
        response = client.post("/proxy/test-bot/stream", json={"message": "hi"})
        assert response.status_code == 404 or response.status_code == 405
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd packages/python/agentstack-gateway && python -m pytest tests/test_server.py -v`
Expected: Multiple FAIL — no `/v1/models` route, old endpoints still exist

- [ ] **Step 3: Add thread storage to `store.py`**

Add a `ThreadStore` section to `packages/python/agentstack-gateway/src/agentstack_gateway/store.py`. This stores thread-agent bindings. Add after the `MemoryRegistrationStore` class (after line 113):

```python
class ThreadStore:
    """In-memory store for thread-to-agent bindings."""

    def __init__(self):
        self._threads: dict[str, dict] = {}

    def create(self, thread_id: str, model: str | None = None, metadata: dict | None = None) -> dict:
        import time
        thread = {
            "id": thread_id,
            "object": "thread",
            "created_at": int(time.time()),
            "metadata": metadata or {},
            "model": model,
        }
        self._threads[thread_id] = thread
        return thread

    def get(self, thread_id: str) -> dict | None:
        return self._threads.get(thread_id)

    def bind_model(self, thread_id: str, model: str) -> None:
        if thread_id in self._threads:
            self._threads[thread_id]["model"] = model
```

- [ ] **Step 4: Rewrite gateway `server.py`**

In `packages/python/agentstack-gateway/src/agentstack_gateway/server.py`:

**Remove** (lines 255-379):
- `proxy_invoke()`, `proxy_stream()`, `proxy_a2a()` stays, `proxy_health()`, `proxy_agent_invoke()`, `proxy_agent_stream()`

Actually keep `proxy_a2a()` (lines 292-302) — A2A proxy stays.

**Remove specifically:**
- Lines 255-270: `POST /invoke/{agent_name}` 
- Lines 273-289: `POST /stream/{agent_name}`
- Lines 332-379: All `/proxy/{agent_name}/*` routes

**Add** new imports and routes. At the top, add:

```python
import time
import uuid

from agentstack.schema.openai import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatCompletionChunk,
    ChatMessage,
    Choice,
    ChunkChoice,
    ChunkDelta,
    CompletionUsage,
    CreateThreadRequest,
    ErrorDetail,
    ErrorResponse,
    ModelList,
    ModelObject,
    Thread,
)
from agentstack_gateway.store import ThreadStore
```

Add `thread_store = ThreadStore()` as a global next to `router` and `providers`.

**Add new routes** (after the `/agents` endpoint):

```python
@app.get("/v1/models")
async def v1_models():
    """List all registered agents as OpenAI-compatible models."""
    models = []
    for route in router.list_routes():
        models.append(ModelObject(
            id=f"agentstack/{route.agent_name}",
            created=int(time.mktime(time.strptime(route.registered_at, "%Y-%m-%dT%H:%M:%S"))) if route.registered_at else int(time.time()),
            owned_by="agentstack",
        ))
    return ModelList(object="list", data=models).model_dump()


@app.post("/v1/chat/completions")
async def v1_chat_completions(request: ChatCompletionRequest):
    """Route chat completion to the target agent via A2A."""
    # Parse model to get agent name
    model = request.model
    agent_name = model.removeprefix("agentstack/") if model.startswith("agentstack/") else model
    route = _find_route(agent_name)
    if not route:
        return JSONResponse(status_code=404, content=ErrorResponse(error=ErrorDetail(
            message=f"Model '{model}' not found",
            type="invalid_request_error",
            param="model",
            code="model_not_found",
        )).model_dump())

    # Extract last user message
    last_msg = request.messages[-1].content or ""
    session_id = request.session_id or str(uuid.uuid4())
    metadata = {
        "trace_id": str(uuid.uuid4()),
        "user_id": request.user_id,
        "project_id": request.project_id,
    }

    if request.stream:
        return await _proxy_stream_completions(route, agent_name, last_msg, session_id, metadata, model)

    # Non-streaming: A2A tasks/send
    a2a_request = {
        "jsonrpc": "2.0",
        "method": "tasks/send",
        "id": 1,
        "params": {
            "id": session_id,
            "sessionId": session_id,
            "message": {"role": "user", "parts": [{"text": last_msg}]},
            "metadata": metadata,
        },
    }
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(f"{route.agent_url}/a2a", json=a2a_request)
            result = resp.json()
            router.mark_online(agent_name)
    except Exception as e:
        router.mark_offline(agent_name, str(e))
        return JSONResponse(status_code=503, content=ErrorResponse(error=ErrorDetail(
            message=f"Agent '{agent_name}' is not responding: {e}",
            type="server_error",
            code="agent_unavailable",
        )).model_dump())

    # Extract response text from A2A result
    a2a_result = result.get("result", {})
    status_msg = a2a_result.get("status", {}).get("message", {})
    parts = status_msg.get("parts", [])
    response_text = " ".join(p.get("text", "") for p in parts if "text" in p)

    return ChatCompletionResponse(
        id=f"chatcmpl-{uuid.uuid4().hex[:12]}",
        created=int(time.time()),
        model=model,
        choices=[Choice(message=ChatMessage(role="assistant", content=response_text))],
    ).model_dump()


async def _proxy_stream_completions(route, agent_name, text, session_id, metadata, model):
    """Proxy streaming via A2A tasks/sendSubscribe, translate to OpenAI chunks."""
    a2a_request = {
        "jsonrpc": "2.0",
        "method": "tasks/sendSubscribe",
        "id": 1,
        "params": {
            "id": session_id,
            "sessionId": session_id,
            "message": {"role": "user", "parts": [{"text": text}]},
            "metadata": metadata,
        },
    }
    completion_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"

    async def event_generator():
        try:
            async with httpx.AsyncClient(timeout=120) as http_client:
                async with http_client.stream("POST", f"{route.agent_url}/a2a", json=a2a_request) as resp:
                    async for line in resp.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        data_str = line[6:]
                        try:
                            data = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue
                        a2a_result = data.get("result", {})
                        artifact = a2a_result.get("artifact", {})
                        parts = artifact.get("parts", [])
                        text_content = "".join(p.get("text", "") for p in parts if "text" in p)
                        if text_content:
                            oai_chunk = ChatCompletionChunk(
                                id=completion_id,
                                created=int(time.time()),
                                model=model,
                                choices=[ChunkChoice(delta=ChunkDelta(content=text_content))],
                            ).model_dump()
                            yield {"data": json.dumps(oai_chunk)}
                        if a2a_result.get("final"):
                            break
            router.mark_online(agent_name)
        except Exception as e:
            router.mark_offline(agent_name, str(e))
        # Final chunk
        final = ChatCompletionChunk(
            id=completion_id,
            created=int(time.time()),
            model=model,
            choices=[ChunkChoice(delta=ChunkDelta(), finish_reason="stop")],
        ).model_dump()
        yield {"data": json.dumps(final)}
        yield {"data": "[DONE]"}

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.post("/v1/threads")
async def v1_create_thread(request: CreateThreadRequest):
    """Create a new thread."""
    thread_id = str(uuid.uuid4())
    thread = thread_store.create(thread_id, model=request.model, metadata=request.metadata)
    return {k: v for k, v in thread.items() if k != "model"}


@app.get("/v1/threads/{thread_id}/messages")
async def v1_list_thread_messages(thread_id: str):
    """List messages in a thread — proxies to the bound agent."""
    thread = thread_store.get(thread_id)
    if not thread:
        return JSONResponse(status_code=404, content=ErrorResponse(error=ErrorDetail(
            message=f"Thread '{thread_id}' not found",
            type="invalid_request_error",
            code="thread_not_found",
        )).model_dump())
    model = thread.get("model")
    if not model:
        return JSONResponse(status_code=400, content=ErrorResponse(error=ErrorDetail(
            message="Thread not bound to a model",
            type="invalid_request_error",
            code="thread_not_bound",
        )).model_dump())
    agent_name = model.removeprefix("agentstack/")
    route = _find_route(agent_name)
    if not route:
        return JSONResponse(status_code=404, content=ErrorResponse(error=ErrorDetail(
            message=f"Model '{model}' not found",
            type="invalid_request_error",
            code="model_not_found",
        )).model_dump())
    async with httpx.AsyncClient(timeout=30) as http_client:
        resp = await http_client.get(f"{route.agent_url}/v1/threads/{thread_id}/messages")
        return resp.json()


@app.post("/v1/threads/{thread_id}/runs")
async def v1_create_run(thread_id: str, request: CreateRunRequest):
    """Create a run on a thread — proxies to the bound agent."""
    thread = thread_store.get(thread_id)
    if not thread:
        return JSONResponse(status_code=404, content=ErrorResponse(error=ErrorDetail(
            message=f"Thread '{thread_id}' not found",
            type="invalid_request_error",
            code="thread_not_found",
        )).model_dump())
    # Bind model on first run if not already bound
    if not thread.get("model"):
        thread_store.bind_model(thread_id, request.model)
    agent_name = request.model.removeprefix("agentstack/")
    route = _find_route(agent_name)
    if not route:
        return JSONResponse(status_code=404, content=ErrorResponse(error=ErrorDetail(
            message=f"Model '{request.model}' not found",
            type="invalid_request_error",
            code="model_not_found",
        )).model_dump())
    async with httpx.AsyncClient(timeout=120) as http_client:
        resp = await http_client.post(
            f"{route.agent_url}/v1/threads/{thread_id}/runs",
            json=request.model_dump(),
        )
        return resp.json()
```

- [ ] **Step 5: Run all gateway tests**

Run: `cd packages/python/agentstack-gateway && python -m pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add packages/python/agentstack-gateway/src/agentstack_gateway/server.py packages/python/agentstack-gateway/src/agentstack_gateway/store.py packages/python/agentstack-gateway/tests/test_server.py
git commit -m "feat: add OpenAI-compatible /v1/ endpoints to gateway, remove old proxy routes"
```

---

### Task 5: Chat Client — Migrate to `/v1/chat/completions`

**Files:**
- Modify: `packages/python/agentstack-chat/src/agentstack_chat/client.py`
- Create: `packages/python/agentstack-chat/tests/test_client.py`

- [ ] **Step 1: Write failing tests for the migrated client**

```python
# packages/python/agentstack-chat/tests/test_client.py
"""Tests for the OpenAI-compatible chat client."""

import json

import pytest

from agentstack_chat.client import (
    InvokeResult,
    StreamEvent,
    StreamResult,
    invoke,
    list_models,
    stream_events,
)


class TestInvokeResult:
    def test_fields(self):
        r = InvokeResult(response="hi", session_id="s1", input_tokens=5, output_tokens=3, total_tokens=8)
        assert r.response == "hi"
        assert r.total_tokens == 8


class TestStreamEvent:
    def test_token_event(self):
        e = StreamEvent(type="token", token="hello")
        assert e.type == "token"

    def test_tool_event(self):
        e = StreamEvent(type="tool_call_start", tool="search")
        assert e.tool == "search"


class TestListModels:
    @pytest.mark.asyncio
    async def test_list_models_returns_ids(self, httpx_mock):
        httpx_mock.add_response(
            url="http://localhost:8080/v1/models",
            json={"object": "list", "data": [
                {"id": "agentstack/bot-a", "object": "model", "created": 1, "owned_by": "agentstack"},
            ]},
        )
        models = await list_models("http://localhost:8080")
        assert len(models) == 1
        assert models[0]["id"] == "agentstack/bot-a"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd packages/python/agentstack-chat && python -m pytest tests/test_client.py -v`
Expected: FAIL — `ImportError: cannot import name 'list_models' from 'agentstack_chat.client'`

- [ ] **Step 3: Rewrite `client.py` to use OpenAI-compatible endpoints**

```python
# packages/python/agentstack-chat/src/agentstack_chat/client.py
"""Agent API client — OpenAI-compatible endpoints."""

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass

import httpx


@dataclass
class InvokeResult:
    response: str
    session_id: str
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


@dataclass
class StreamResult:
    """Collected after streaming completes."""
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


@dataclass
class StreamEvent:
    """A single event from the stream."""
    type: str  # "token", "tool_call_start", "tool_result", "done"
    token: str = ""
    tool: str = ""
    result: str = ""
    usage: dict | None = None


async def invoke(url: str, message: str, session_id: str, model: str = "") -> InvokeResult:
    """Send a message via /v1/chat/completions (non-streaming)."""
    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(
            f"{url}/v1/chat/completions",
            json={
                "model": model,
                "messages": [{"role": "user", "content": message}],
                "stream": False,
                "session_id": session_id,
            },
        )
        response.raise_for_status()
        data = response.json()
        content = data["choices"][0]["message"]["content"] or ""
        usage = data.get("usage") or {}
        return InvokeResult(
            response=content,
            session_id=session_id,
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            total_tokens=usage.get("total_tokens", 0),
        )


async def stream_events(
    url: str, message: str, session_id: str, result: StreamResult | None = None, model: str = ""
) -> AsyncIterator[StreamEvent]:
    """Stream via /v1/chat/completions with stream=true."""
    async with httpx.AsyncClient(timeout=120.0) as client:
        async with client.stream(
            "POST",
            f"{url}/v1/chat/completions",
            json={
                "model": model,
                "messages": [{"role": "user", "content": message}],
                "stream": True,
                "session_id": session_id,
            },
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data_str = line[6:]
                if data_str == "[DONE]":
                    yield StreamEvent(type="done")
                    return
                try:
                    data = json.loads(data_str)
                except json.JSONDecodeError:
                    continue

                choices = data.get("choices", [])
                if not choices:
                    continue
                delta = choices[0].get("delta", {})
                finish_reason = choices[0].get("finish_reason")

                # Extension events (tool calls, sub-agent activity)
                x = data.get("x_agentstack")
                if x:
                    event_type = x.get("type", "")
                    if event_type == "tool_call_start":
                        yield StreamEvent(type="tool_call_start", tool=x.get("tool", ""))
                    elif event_type == "tool_result":
                        yield StreamEvent(type="tool_result", tool=x.get("tool", ""), result=x.get("result", ""))
                    continue

                # Content tokens
                content = delta.get("content")
                if content:
                    yield StreamEvent(type="token", token=content)

                if finish_reason == "stop":
                    yield StreamEvent(type="done")
                    return


async def list_models(url: str) -> list[dict]:
    """Get available models from /v1/models."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{url}/v1/models")
            response.raise_for_status()
            return response.json().get("data", [])
    except Exception:
        return []


async def health(url: str) -> dict | None:
    """Check agent health."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{url}/health")
            response.raise_for_status()
            return response.json()
    except Exception:
        return None


async def gateway_routes(gateway_url: str) -> list[dict]:
    """Get all routes from a gateway."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{gateway_url}/routes")
            response.raise_for_status()
            return response.json()
    except Exception:
        return []


async def gateway_health(gateway_url: str) -> dict | None:
    """Check gateway health."""
    return await health(gateway_url)
```

- [ ] **Step 4: Run tests**

Run: `cd packages/python/agentstack-chat && python -m pytest tests/test_client.py -v`
Expected: All tests PASS (note: the httpx_mock test requires `pytest-httpx` — add to test dependencies if not present)

- [ ] **Step 5: Commit**

```bash
git add packages/python/agentstack-chat/src/agentstack_chat/client.py packages/python/agentstack-chat/tests/test_client.py
git commit -m "feat: migrate chat client to OpenAI-compatible /v1/chat/completions"
```

---

### Task 6: Update Generated Requirements

**Files:**
- Modify: `packages/python/agentstack-adapter-langchain/src/agentstack_adapter_langchain/templates.py`
- Modify: `packages/python/agentstack-adapter-langchain/tests/test_templates.py`

The generated `requirements.txt` needs to include `agentstack` as a dependency since the generated server now imports `from agentstack.schema.openai import ...`.

- [ ] **Step 1: Write failing test**

Add to `TestGenerateRequirementsTxt` in `test_templates.py`:

```python
def test_includes_agentstack_core(self, anthropic_agent):
    reqs = generate_requirements_txt(anthropic_agent)
    assert "agentstack" in reqs
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd packages/python/agentstack-adapter-langchain && python -m pytest tests/test_templates.py::TestGenerateRequirementsTxt::test_includes_agentstack_core -v`
Expected: FAIL

- [ ] **Step 3: Add `agentstack` to generated requirements**

In `templates.py`, in `generate_requirements_txt()` (line 686-693), add `agentstack>=0.1` to the template string:

```python
    return dedent(f"""\
        langchain-core>=0.3
        langgraph>=0.2
        {provider_pkg}
        fastapi>=0.115
        uvicorn>=0.34
        sse-starlette>=2.0
        agentstack>=0.1{checkpoint_pkg}{mcp_pkg}{tool_deps}
    """)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd packages/python/agentstack-adapter-langchain && python -m pytest tests/test_templates.py::TestGenerateRequirementsTxt -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add packages/python/agentstack-adapter-langchain/src/agentstack_adapter_langchain/templates.py packages/python/agentstack-adapter-langchain/tests/test_templates.py
git commit -m "feat: include agentstack core in generated requirements for OpenAI schema imports"
```

---

### Task 7: Full Integration Verification

**Files:** No new files — runs existing tests across all packages.

- [ ] **Step 1: Run all tests across the monorepo**

```bash
cd /Users/akolodkin/Developer/work/AgentsStack
just test-python
```

Or individually:

```bash
cd packages/python/agentstack && python -m pytest tests/ -v
cd packages/python/agentstack-adapter-langchain && python -m pytest tests/ -v
cd packages/python/agentstack-gateway && python -m pytest tests/ -v
cd packages/python/agentstack-chat && python -m pytest tests/ -v
```

Expected: All tests PASS across all packages.

- [ ] **Step 2: Verify generated server code is valid Python**

```bash
cd packages/python/agentstack-adapter-langchain && python -c "
from agentstack.schema.agent import Agent
from agentstack.schema.model import Model
from agentstack.schema.provider import Provider
from agentstack.schema.skill import Skill
from agentstack.schema.service import Sqlite
from agentstack_adapter_langchain.templates import generate_server_py
import ast
agent = Agent(
    name='test-bot',
    model=Model(name='claude', provider=Provider(name='anthropic', type='anthropic'), model_name='claude-sonnet-4-20250514'),
    skills=[Skill(name='tools', tools=['search'])],
    sessions=Sqlite(name='sessions'),
)
code = generate_server_py(agent)
ast.parse(code)
print('Generated server code is valid Python')
"
```

Expected: `Generated server code is valid Python`

- [ ] **Step 3: Verify no references to old endpoints remain**

```bash
cd /Users/akolodkin/Developer/work/AgentsStack
grep -r '"/invoke"' packages/python/ --include='*.py' | grep -v test | grep -v __pycache__
grep -r '"/stream"' packages/python/ --include='*.py' | grep -v test | grep -v __pycache__
```

Expected: No matches (old endpoints fully removed from non-test code). Test files may still reference them in "removed" assertions.

- [ ] **Step 4: Commit any final fixes**

If any tests failed, fix and commit. Otherwise, no action needed.

- [ ] **Step 5: Final commit**

```bash
git add -A
git commit -m "chore: verify full test suite passes after OpenAI API migration"
```
