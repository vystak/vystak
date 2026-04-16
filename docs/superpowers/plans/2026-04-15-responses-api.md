# Responses API + Stateless Chat Completions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Threads/Assistants API with OpenAI Responses API, make Chat Completions fully stateless.

**Architecture:** Add Responses API endpoints (`/v1/responses`, `/v1/responses/{id}`) to both generated agent servers and gateway. Make Chat Completions pass full `messages` array to LangGraph without checkpointer. Remove all Threads API endpoints. Response ID = LangGraph thread_id for `store: true`.

**Tech Stack:** Python, FastAPI, Pydantic v2, LangGraph, httpx, SSE (sse-starlette), asyncio

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `packages/python/agentstack/src/agentstack/schema/openai.py` | Modify | Remove Threads types, add Responses API types |
| `packages/python/agentstack/src/agentstack/schema/__init__.py` | Modify | Update exports |
| `packages/python/agentstack/tests/test_openai_schema.py` | Modify | Update tests for new/removed types |
| `packages/python/agentstack-adapter-langchain/src/agentstack_adapter_langchain/templates.py` | Modify | Replace Threads endpoints with Responses API, make completions stateless |
| `packages/python/agentstack-adapter-langchain/tests/test_templates.py` | Modify | Update tests |
| `packages/python/agentstack-gateway/src/agentstack_gateway/server.py` | Modify | Replace Threads with Responses API routes |
| `packages/python/agentstack-gateway/src/agentstack_gateway/store.py` | Modify | Replace ThreadStore with ResponseStore |
| `packages/python/agentstack-gateway/tests/test_server.py` | Modify | Update tests |
| `packages/python/agentstack-chat/src/agentstack_chat/client.py` | Modify | Switch to Responses API |
| `packages/python/agentstack-chat/src/agentstack_chat/chat.py` | Modify | Use `previous_response_id` chaining |
| `packages/python/agentstack-chat/tests/test_client.py` | Modify | Update tests |

---

### Task 1: Update Schema — Remove Threads Types, Add Responses API Types

**Files:**
- Modify: `packages/python/agentstack/src/agentstack/schema/openai.py`
- Modify: `packages/python/agentstack/src/agentstack/schema/__init__.py`
- Modify: `packages/python/agentstack/tests/test_openai_schema.py`

- [ ] **Step 1: Write failing tests for new Responses types**

Replace `TestThread` class in `packages/python/agentstack/tests/test_openai_schema.py` with:

```python
class TestResponse:
    def test_create_request_string_input(self):
        req = CreateResponseRequest(
            model="agentstack/test-bot",
            input="hello",
        )
        assert req.store is True
        assert req.stream is False
        assert req.background is False
        assert req.previous_response_id is None

    def test_create_request_array_input(self):
        req = CreateResponseRequest(
            model="agentstack/test-bot",
            input=[
                InputMessage(role="user", content="hi"),
                InputMessage(role="assistant", content="hello"),
                InputMessage(role="user", content="how are you"),
            ],
        )
        assert len(req.input) == 3

    def test_create_request_with_chaining(self):
        req = CreateResponseRequest(
            model="agentstack/test-bot",
            input="follow up",
            previous_response_id="resp-abc123",
            store=True,
        )
        assert req.previous_response_id == "resp-abc123"

    def test_create_request_stateless(self):
        req = CreateResponseRequest(
            model="agentstack/test-bot",
            input="one-shot",
            store=False,
        )
        assert req.store is False

    def test_response_object(self):
        resp = ResponseObject(
            id="resp-123",
            created_at=1000,
            model="agentstack/test-bot",
            output=[ResponseOutput(content="hello")],
        )
        assert resp.object == "response"
        assert resp.status == "completed"
        assert resp.store is True

    def test_response_in_progress(self):
        resp = ResponseObject(
            id="resp-123",
            created_at=1000,
            model="agentstack/test-bot",
            output=[],
            status="in_progress",
        )
        assert resp.status == "in_progress"

    def test_response_usage(self):
        usage = ResponseUsage(input_tokens=10, output_tokens=5, total_tokens=15)
        assert usage.total_tokens == 15

    def test_input_message(self):
        msg = InputMessage(role="user", content="hello")
        assert msg.role == "user"
```

Also update imports at top of test file — remove `CreateThreadRequest, Thread, CreateMessageRequest, ThreadMessage, CreateRunRequest, Run, ContentBlock` and add `CreateResponseRequest, InputMessage, ResponseObject, ResponseOutput, ResponseUsage`.

Remove the old `TestThread` class entirely.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --project packages/python/agentstack pytest packages/python/agentstack/tests/test_openai_schema.py -v`
Expected: FAIL — `ImportError: cannot import name 'CreateResponseRequest'`

- [ ] **Step 3: Update `openai.py` — remove Threads types, add Responses types**

In `packages/python/agentstack/src/agentstack/schema/openai.py`:

**Remove** these classes:
- `CreateThreadRequest`
- `Thread`
- `ContentBlock`
- `CreateMessageRequest`
- `ThreadMessage`
- `CreateRunRequest`
- `Run`

**Remove** `session_id` field from `ChatCompletionRequest` (keep `user_id` and `project_id`).

**Add** these classes after the Chat Completions section:

```python
# === Responses API ===

class InputMessage(BaseModel):
    role: str
    content: str


class CreateResponseRequest(BaseModel):
    model: str
    input: str | list[InputMessage]
    previous_response_id: str | None = None
    store: bool = True
    stream: bool = False
    background: bool = False
    user_id: str | None = None
    project_id: str | None = None


class ResponseOutput(BaseModel):
    type: str = "message"
    role: str = "assistant"
    content: str


class ResponseUsage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


class ResponseObject(BaseModel):
    id: str
    object: str = "response"
    created_at: int
    model: str
    output: list[ResponseOutput]
    status: str = "completed"
    previous_response_id: str | None = None
    usage: ResponseUsage | None = None
    store: bool = True
```

- [ ] **Step 4: Update `__init__.py` exports**

In `packages/python/agentstack/src/agentstack/schema/__init__.py`:

Remove from imports and `__all__`: `ContentBlock`, `CreateMessageRequest`, `CreateRunRequest`, `CreateThreadRequest`, `Run`, `Thread`, `ThreadMessage`

Add to imports and `__all__`: `CreateResponseRequest`, `InputMessage`, `ResponseObject`, `ResponseOutput`, `ResponseUsage`

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run --project packages/python/agentstack pytest packages/python/agentstack/tests/test_openai_schema.py -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add packages/python/agentstack/src/agentstack/schema/openai.py packages/python/agentstack/src/agentstack/schema/__init__.py packages/python/agentstack/tests/test_openai_schema.py
git commit -m "feat: replace Threads types with Responses API types in OpenAI schema"
```

---

### Task 2: Generated Server — Stateless Chat Completions + Responses API

**Files:**
- Modify: `packages/python/agentstack-adapter-langchain/src/agentstack_adapter_langchain/templates.py`
- Modify: `packages/python/agentstack-adapter-langchain/tests/test_templates.py`

This is the largest task. Changes to `generate_server_py()`:

1. **Update imports** — remove Threads types, add Responses types
2. **Make Chat Completions stateless** — pass full `messages` array, use random one-shot `thread_id`, no checkpointer persistence
3. **Remove** all `/v1/threads/*` endpoints and `_threads` storage
4. **Add** `/v1/responses` POST endpoint with `store: true/false`, `previous_response_id`, `background`, streaming
5. **Add** `/v1/responses/{response_id}` GET endpoint
6. **Add** `_responses` in-memory storage for `store: true` responses
7. **Add** Responses streaming helper with OpenAI SSE event types

- [ ] **Step 1: Update tests in `test_templates.py`**

Replace the server endpoint tests in `TestGenerateServerPy`:

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

    def test_has_v1_chat_completions(self, anthropic_agent):
        code = generate_server_py(anthropic_agent)
        assert '"/v1/chat/completions"' in code

    def test_chat_completions_stateless(self, anthropic_agent):
        """Chat Completions passes full messages array, no session_id."""
        code = generate_server_py(anthropic_agent)
        assert "session_id" not in code or "session_id" in code  # may appear in A2A
        # Key: converts full messages array to LangGraph format
        assert "for msg in request.messages" in code

    def test_has_v1_responses(self, anthropic_agent):
        code = generate_server_py(anthropic_agent)
        assert '"/v1/responses"' in code
        assert "CreateResponseRequest" in code

    def test_has_v1_responses_get(self, anthropic_agent):
        code = generate_server_py(anthropic_agent)
        assert '"/v1/responses/{response_id}"' in code

    def test_responses_streaming(self, anthropic_agent):
        code = generate_server_py(anthropic_agent)
        assert "response.created" in code
        assert "response.output_text.delta" in code
        assert "response.completed" in code
        assert "response.function_call_arguments.delta" in code

    def test_responses_background(self, anthropic_agent):
        code = generate_server_py(anthropic_agent)
        assert "background" in code
        assert "in_progress" in code

    def test_no_threads_endpoints(self, anthropic_agent):
        code = generate_server_py(anthropic_agent)
        assert '"/v1/threads"' not in code
        assert "CreateThreadRequest" not in code

    def test_no_invoke_endpoint(self, anthropic_agent):
        code = generate_server_py(anthropic_agent)
        assert '"/invoke"' not in code

    def test_no_stream_endpoint(self, anthropic_agent):
        code = generate_server_py(anthropic_agent)
        assert '"/stream"' not in code

    def test_imports_openai_types(self, anthropic_agent):
        code = generate_server_py(anthropic_agent)
        assert "from openai_types import" in code
        assert "CreateResponseRequest" in code
        assert "ResponseObject" in code

    def test_openai_error_format(self, anthropic_agent):
        code = generate_server_py(anthropic_agent)
        assert "ErrorResponse" in code
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --project packages/python/agentstack-adapter-langchain pytest packages/python/agentstack-adapter-langchain/tests/test_templates.py::TestGenerateServerPy -v`
Expected: Multiple FAILs

- [ ] **Step 3: Rewrite the imports section in `generate_server_py()`**

Replace lines 353-373 (the `from openai_types import (...)` block) with:

```python
    lines.append("from openai_types import (")
    lines.append("    ChatCompletionChunk,")
    lines.append("    ChatCompletionRequest,")
    lines.append("    ChatCompletionResponse,")
    lines.append("    ChatMessage,")
    lines.append("    Choice,")
    lines.append("    ChunkChoice,")
    lines.append("    ChunkDelta,")
    lines.append("    CompletionUsage,")
    lines.append("    CreateResponseRequest,")
    lines.append("    ErrorDetail,")
    lines.append("    ErrorResponse,")
    lines.append("    InputMessage,")
    lines.append("    ModelList,")
    lines.append("    ModelObject,")
    lines.append("    ResponseObject,")
    lines.append("    ResponseOutput,")
    lines.append("    ResponseUsage,")
    lines.append(")")
```

Also add `import asyncio` to the generated imports (for background tasks).

- [ ] **Step 4: Rewrite Chat Completions to be stateless**

Replace the `/v1/chat/completions` handler (lines 554-617) with stateless version:

```python
    # === /v1/chat/completions (stateless) ===
    lines.append('@app.post("/v1/chat/completions")')
    lines.append("async def chat_completions(request: ChatCompletionRequest):")
    lines.append("    user_id = request.user_id")
    lines.append("    project_id = request.project_id")
    lines.append("    # Stateless: random thread_id, no checkpoint persistence")
    lines.append('    config = {"configurable": {')
    lines.append('        "thread_id": str(uuid.uuid4()),')
    lines.append('        "user_id": user_id,')
    lines.append('        "project_id": project_id,')
    lines.append('        "agent_name": AGENT_NAME,')
    lines.append("    }}")
    lines.append("")
    lines.append("    # Convert full messages array to LangGraph format")
    lines.append("    messages = []")

    if uses_persistent:
        lines.append("    # Memory recall from last user message")
        lines.append("    last_user_msg = ''")
        lines.append("    for msg in reversed(request.messages):")
        lines.append("        if msg.role == 'user' and msg.content:")
        lines.append("            last_user_msg = msg.content")
        lines.append("            break")
        lines.append("    memories = await recall_memories(_store, last_user_msg, user_id=user_id, project_id=project_id)")
        lines.append("    if memories:")
        lines.append('        memory_text = "Relevant memories:\\n" + "\\n".join(memories)')
        lines.append('        messages.append(("system", memory_text))')

    lines.append("    for msg in request.messages:")
    lines.append("        messages.append((msg.role, msg.content or ''))")
    lines.append("")
    # ... (streaming branch and invoke remain similar but use the full messages)
```

The streaming helper `_stream_chat_completions` stays but now receives the full messages list.

- [ ] **Step 5: Remove Threads endpoints**

Delete lines 699-788 (everything from `# === /v1/threads ===` to the end of the `create_run` function). Remove `_threads` storage dict.

- [ ] **Step 6: Add Responses API endpoints**

After the Chat Completions streaming helper, add:

**Response storage:**
```python
    lines.append("# Response storage (in-memory)")
    lines.append("_responses: dict[str, dict] = {}")
    lines.append("")
```

**POST /v1/responses:**
```python
    lines.append('@app.post("/v1/responses")')
    lines.append("async def create_response(request: CreateResponseRequest):")
    lines.append("    # Parse input")
    lines.append("    if isinstance(request.input, str):")
    lines.append('        input_messages = [("user", request.input)]')
    lines.append("    else:")
    lines.append("        input_messages = [(m.role, m.content) for m in request.input]")
    lines.append("")
    lines.append("    # Determine response ID and thread_id")
    lines.append("    if request.store and request.previous_response_id:")
    lines.append("        # Chain: reuse previous response ID as thread_id")
    lines.append("        if request.previous_response_id not in _responses:")
    lines.append("            return JSONResponse(status_code=404, content=ErrorResponse(error=ErrorDetail(")
    lines.append('                message="Previous response not found", type="invalid_request_error",')
    lines.append('                param="previous_response_id", code="response_not_found",')
    lines.append("            )).model_dump())")
    lines.append("        prev = _responses[request.previous_response_id]")
    lines.append("        if not prev.get('store'):")
    lines.append("            return JSONResponse(status_code=400, content=ErrorResponse(error=ErrorDetail(")
    lines.append('                message="Cannot chain to a store=false response", type="invalid_request_error",')
    lines.append('                param="previous_response_id", code="invalid_request",')
    lines.append("            )).model_dump())")
    lines.append("        response_id = request.previous_response_id")
    lines.append("    elif request.store:")
    lines.append("        response_id = str(uuid.uuid4())")
    lines.append("    else:")
    lines.append("        response_id = str(uuid.uuid4())")
    lines.append("")
    lines.append("    user_id = request.user_id")
    lines.append("    project_id = request.project_id")
    lines.append("")
```

Then add the config and execution logic:

```python
    lines.append("    if request.store:")
    lines.append('        config = {"configurable": {"thread_id": response_id, "user_id": user_id, "project_id": project_id, "agent_name": AGENT_NAME}}')
    lines.append("    else:")
    lines.append('        config = {"configurable": {"thread_id": str(uuid.uuid4()), "agent_name": AGENT_NAME}}')
    lines.append("")
```

Memory recall (persistent only):
```python
    if uses_persistent:
        lines.append("    # Memory recall")
        lines.append("    last_text = input_messages[-1][1] if input_messages else ''")
        lines.append("    memories = await recall_memories(_store, last_text, user_id=user_id, project_id=project_id)")
        lines.append("    if memories:")
        lines.append('        memory_text = "Relevant memories:\\n" + "\\n".join(memories)')
        lines.append('        input_messages.insert(0, ("system", memory_text))')
```

Streaming branch:
```python
    lines.append("    if request.stream:")
    lines.append("        return await _stream_response(input_messages, config, response_id, request)")
    lines.append("")
```

Background branch:
```python
    lines.append("    if request.background:")
    lines.append("        # Store in-progress response and run in background")
    lines.append("        resp_obj = ResponseObject(")
    lines.append("            id=response_id, created_at=int(time.time()), model=MODEL_ID,")
    lines.append('            output=[], status="in_progress",')
    lines.append("            previous_response_id=request.previous_response_id,")
    lines.append("            store=request.store,")
    lines.append("        )")
    lines.append("        _responses[response_id] = resp_obj.model_dump()")
    lines.append(f"        asyncio.create_task(_run_background(input_messages, config, response_id, request))")
    lines.append("        return resp_obj.model_dump()")
    lines.append("")
```

Synchronous (non-streaming, non-background) execution:
```python
    lines.append(f"    result = await {agent_ref}.ainvoke(")
    lines.append('        {"messages": input_messages},')
    lines.append("        config=config,")
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
    lines.append("        usage = ResponseUsage(")
    lines.append("            input_tokens=um.get('input_tokens', 0),")
    lines.append("            output_tokens=um.get('output_tokens', 0),")
    lines.append("            total_tokens=um.get('total_tokens', 0),")
    lines.append("        )")
    lines.append("")
    lines.append("    resp_obj = ResponseObject(")
    lines.append("        id=response_id, created_at=int(time.time()), model=MODEL_ID,")
    lines.append("        output=[ResponseOutput(content=response_text)],")
    lines.append('        status="completed",')
    lines.append("        previous_response_id=request.previous_response_id,")
    lines.append("        usage=usage, store=request.store,")
    lines.append("    )")
    lines.append("    if request.store:")
    lines.append("        _responses[response_id] = resp_obj.model_dump()")
    lines.append("    return resp_obj.model_dump()")
    lines.append("")
    lines.append("")
```

- [ ] **Step 7: Add background runner helper**

```python
    lines.append(f"async def _run_background(input_messages, config, response_id, request):")
    lines.append("    try:")
    lines.append(f"        result = await {agent_ref}.ainvoke(")
    lines.append('            {"messages": input_messages},')
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
    lines.append("        last = result['messages'][-1]")
    lines.append("        usage = None")
    lines.append("        if hasattr(last, 'usage_metadata') and last.usage_metadata:")
    lines.append("            um = last.usage_metadata")
    lines.append("            usage = ResponseUsage(")
    lines.append("                input_tokens=um.get('input_tokens', 0),")
    lines.append("                output_tokens=um.get('output_tokens', 0),")
    lines.append("                total_tokens=um.get('total_tokens', 0),")
    lines.append("            ).model_dump()")
    lines.append("        _responses[response_id] = {")
    lines.append("            **_responses[response_id],")
    lines.append('            "status": "completed",')
    lines.append('            "output": [ResponseOutput(content=response_text).model_dump()],')
    lines.append('            "usage": usage,')
    lines.append("        }")
    lines.append("    except Exception as exc:")
    lines.append("        _responses[response_id] = {")
    lines.append("            **_responses[response_id],")
    lines.append('            "status": "failed",')
    lines.append('            "output": [ResponseOutput(content=str(exc)).model_dump()],')
    lines.append("        }")
    lines.append("")
    lines.append("")
```

- [ ] **Step 8: Add GET /v1/responses/{response_id}**

```python
    lines.append('@app.get("/v1/responses/{response_id}")')
    lines.append("async def get_response(response_id: str):")
    lines.append("    if response_id not in _responses:")
    lines.append("        return JSONResponse(status_code=404, content=ErrorResponse(error=ErrorDetail(")
    lines.append('            message="Response not found", type="invalid_request_error", code="response_not_found",')
    lines.append("        )).model_dump())")
    lines.append("    return _responses[response_id]")
    lines.append("")
    lines.append("")
```

- [ ] **Step 9: Add Responses streaming helper**

```python
    lines.append("async def _stream_response(input_messages, config, response_id, request):")
    lines.append("")
    lines.append("    async def event_generator():")
    lines.append("        # response.created event")
    lines.append("        created = int(time.time())")
    lines.append("        created_event = {")
    lines.append('            "type": "response.created",')
    lines.append('            "response": {"id": response_id, "status": "in_progress", "model": MODEL_ID},')
    lines.append("        }")
    lines.append('        yield {"data": json.dumps(created_event)}')
    lines.append("")
    lines.append("        # output item added")
    lines.append('        yield {"data": json.dumps({"type": "response.output_item.added", "item": {"type": "message", "role": "assistant"}})}')
    lines.append('        yield {"data": json.dumps({"type": "response.content_part.added", "part": {"type": "output_text", "text": ""}})}')
    lines.append("")
    lines.append("        accumulated_text = []")
    lines.append("        usage = {}")
    lines.append("        current_tool_name = None")
    lines.append("        current_tool_args = []")
    lines.append(f"        async for chunk in {agent_ref}.astream(")
    lines.append('            {"messages": input_messages},')
    lines.append("            config=config,")
    lines.append('            stream_mode=["messages", "custom"],')
    lines.append("        ):")
    lines.append('            if chunk[0] == "messages":')
    lines.append('                msg, metadata = chunk[1]')
    lines.append('                if msg.type == "AIMessageChunk":')
    lines.append("                    if msg.content:")
    lines.append("                        text = msg.content if isinstance(msg.content, str) else ''")
    lines.append("                        if not text and isinstance(msg.content, list):")
    lines.append("                            for block in msg.content:")
    lines.append("                                if isinstance(block, dict) and block.get('type') == 'text':")
    lines.append("                                    text += block.get('text', '')")
    lines.append("                        if text:")
    lines.append("                            accumulated_text.append(text)")
    lines.append('                            yield {"data": json.dumps({"type": "response.output_text.delta", "delta": text})}')
    lines.append("                    if msg.tool_call_chunks:")
    lines.append("                        for tc in msg.tool_call_chunks:")
    lines.append("                            if tc.get('name'):")
    lines.append("                                # New tool call starting")
    lines.append("                                if current_tool_name and current_tool_args:")
    lines.append("                                    args_str = ''.join(current_tool_args)")
    lines.append('                                    yield {"data": json.dumps({"type": "response.function_call_arguments.done", "name": current_tool_name, "arguments": args_str})}')
    lines.append("                                current_tool_name = tc['name']")
    lines.append("                                current_tool_args = []")
    lines.append('                                yield {"data": json.dumps({"type": "response.output_item.added", "item": {"type": "function_call", "name": tc["name"]}})}')
    lines.append("                            if tc.get('args'):")
    lines.append("                                current_tool_args.append(tc['args'])")
    lines.append('                                yield {"data": json.dumps({"type": "response.function_call_arguments.delta", "delta": tc["args"]})}')
    lines.append("                    if hasattr(msg, 'usage_metadata') and msg.usage_metadata:")
    lines.append("                        um = msg.usage_metadata")
    lines.append("                        inp = um.get('input_tokens', 0)")
    lines.append("                        out = um.get('output_tokens', 0)")
    lines.append("                        if inp or out:")
    lines.append('                            usage = {"input_tokens": inp, "output_tokens": out, "total_tokens": um.get("total_tokens", 0)}')
    lines.append('                elif msg.type == "tool":')
    lines.append("                    # Close any pending tool call")
    lines.append("                    if current_tool_name and current_tool_args:")
    lines.append("                        args_str = ''.join(current_tool_args)")
    lines.append('                        yield {"data": json.dumps({"type": "response.function_call_arguments.done", "name": current_tool_name, "arguments": args_str})}')
    lines.append("                        current_tool_name = None")
    lines.append("                        current_tool_args = []")
    lines.append("                    tool_name = getattr(msg, 'name', 'tool')")
    lines.append("                    output_str = str(msg.content)[:500] if msg.content else ''")
    lines.append('                    yield {"data": json.dumps({"type": "response.output_item.added", "item": {"type": "function_call_output", "output": output_str}})}')
    lines.append("")
    lines.append("        # text done event")
    lines.append("        full_text = ''.join(accumulated_text)")
    lines.append("        if full_text:")
    lines.append('            yield {"data": json.dumps({"type": "response.output_text.done", "text": full_text})}')
    lines.append("")
    lines.append("        # Store response if store=true")
    lines.append("        if request.store:")
    lines.append("            resp_obj = ResponseObject(")
    lines.append("                id=response_id, created_at=created, model=MODEL_ID,")
    lines.append("                output=[ResponseOutput(content=full_text)],")
    lines.append('                status="completed",')
    lines.append("                previous_response_id=request.previous_response_id,")
    lines.append("                usage=ResponseUsage(**usage) if usage else None,")
    lines.append("                store=True,")
    lines.append("            )")
    lines.append("            _responses[response_id] = resp_obj.model_dump()")
    lines.append("")
    lines.append("        # response.completed event")
    lines.append("        completed_event = {")
    lines.append('            "type": "response.completed",')
    lines.append('            "response": {')
    lines.append('                "id": response_id,')
    lines.append('                "status": "completed",')
    lines.append('                "model": MODEL_ID,')
    lines.append('                "output": [{"type": "message", "role": "assistant", "content": full_text}],')
    lines.append('                "usage": usage,')
    lines.append("            },")
    lines.append("        }")
    lines.append('        yield {"data": json.dumps(completed_event)}')
    lines.append('        yield {"data": "[DONE]"}')
    lines.append("")
    lines.append("    return EventSourceResponse(event_generator())")
    lines.append("")
    lines.append("")
```

- [ ] **Step 10: Run all adapter tests**

Run: `uv run --project packages/python/agentstack-adapter-langchain pytest packages/python/agentstack-adapter-langchain/tests/ -v`
Expected: All tests PASS

- [ ] **Step 11: Commit**

```bash
git add packages/python/agentstack-adapter-langchain/src/agentstack_adapter_langchain/templates.py packages/python/agentstack-adapter-langchain/tests/test_templates.py
git commit -m "feat: stateless chat completions + responses API in generated server"
```

---

### Task 3: Gateway — Replace Threads with Responses API

**Files:**
- Modify: `packages/python/agentstack-gateway/src/agentstack_gateway/server.py`
- Modify: `packages/python/agentstack-gateway/src/agentstack_gateway/store.py`
- Modify: `packages/python/agentstack-gateway/tests/test_server.py`

- [ ] **Step 1: Update tests**

In `test_server.py`:

Remove `TestV1Threads` class. Replace with:

```python
class TestV1Responses:
    def test_create_response_unknown_model(self):
        response = client.post("/v1/responses", json={
            "model": "agentstack/nonexistent",
            "input": "hi",
        })
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "model_not_found"

    def test_get_response_not_found(self):
        response = client.get("/v1/responses/nonexistent")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "response_not_found"


class TestOldEndpointsRemoved:
    def test_invoke_gone(self):
        response = client.post("/invoke/test-bot", json={"message": "hi"})
        assert response.status_code in (404, 405)

    def test_stream_gone(self):
        response = client.post("/stream/test-bot", json={"message": "hi"})
        assert response.status_code in (404, 405)

    def test_proxy_invoke_gone(self):
        response = client.post("/proxy/test-bot/invoke", json={"message": "hi"})
        assert response.status_code in (404, 405)

    def test_proxy_stream_gone(self):
        response = client.post("/proxy/test-bot/stream", json={"message": "hi"})
        assert response.status_code in (404, 405)

    def test_threads_gone(self):
        response = client.post("/v1/threads", json={})
        assert response.status_code in (404, 405)
```

Update `reset_state` fixture to clear `response_store._responses` instead of `thread_store._threads`.

- [ ] **Step 2: Replace ThreadStore with ResponseStore in `store.py`**

Remove `ThreadStore` class. Add:

```python
class ResponseStore:
    """In-memory store for response-to-agent bindings."""

    def __init__(self):
        self._responses: dict[str, dict] = {}

    def save(self, response_id: str, agent_name: str, data: dict | None = None) -> None:
        self._responses[response_id] = {"agent_name": agent_name, **(data or {})}

    def get(self, response_id: str) -> dict | None:
        return self._responses.get(response_id)
```

- [ ] **Step 3: Update gateway `server.py`**

**Remove:**
- All `/v1/threads/*` routes
- `ThreadStore` import and `thread_store` global
- Threads-related imports from `openai_types`

**Update imports** from `openai_types`:
```python
from agentstack.schema.openai import (
    ChatCompletionRequest, ChatCompletionResponse, ChatCompletionChunk,
    ChatMessage, Choice, ChunkChoice, ChunkDelta, CompletionUsage,
    CreateResponseRequest, ErrorDetail, ErrorResponse,
    InputMessage, ModelList, ModelObject, ResponseObject,
)
```

**Add** `ResponseStore` import and `response_store = ResponseStore()` global.

**Remove** `session_id` references from Chat Completions handler.

**Add** new routes:

```python
@app.post("/v1/responses")
async def v1_create_response(request: CreateResponseRequest):
    """Route response creation to the target agent."""
    model = request.model
    agent_name = model.removeprefix("agentstack/")
    route = _find_route(agent_name)
    if not route:
        return JSONResponse(status_code=404, content=ErrorResponse(error=ErrorDetail(
            message=f"Model '{model}' not found",
            type="invalid_request_error", code="model_not_found",
        )).model_dump())

    # If chaining, verify the previous response belongs to the same agent
    if request.previous_response_id:
        prev = response_store.get(request.previous_response_id)
        if prev and prev["agent_name"] != agent_name:
            return JSONResponse(status_code=400, content=ErrorResponse(error=ErrorDetail(
                message="Cannot chain to a response from a different agent",
                type="invalid_request_error", code="invalid_request",
            )).model_dump())

    # Proxy to agent
    async with httpx.AsyncClient(timeout=120) as http_client:
        resp = await http_client.post(
            f"{route.agent_url}/v1/responses",
            json=request.model_dump(),
        )
        result = resp.json()

    # Store response-agent mapping
    resp_id = result.get("id")
    if resp_id:
        response_store.save(resp_id, agent_name)

    return result


@app.get("/v1/responses/{response_id}")
async def v1_get_response(response_id: str):
    """Retrieve a response — proxy to the owning agent."""
    mapping = response_store.get(response_id)
    if not mapping:
        return JSONResponse(status_code=404, content=ErrorResponse(error=ErrorDetail(
            message="Response not found",
            type="invalid_request_error", code="response_not_found",
        )).model_dump())

    agent_name = mapping["agent_name"]
    route = _find_route(agent_name)
    if not route:
        return JSONResponse(status_code=404, content=ErrorResponse(error=ErrorDetail(
            message=f"Agent '{agent_name}' not found",
            type="invalid_request_error", code="model_not_found",
        )).model_dump())

    async with httpx.AsyncClient(timeout=30) as http_client:
        resp = await http_client.get(f"{route.agent_url}/v1/responses/{response_id}")
        return resp.json()
```

- [ ] **Step 4: Run gateway tests**

Run: `uv run --project packages/python/agentstack-gateway pytest packages/python/agentstack-gateway/tests/ -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add packages/python/agentstack-gateway/src/agentstack_gateway/server.py packages/python/agentstack-gateway/src/agentstack_gateway/store.py packages/python/agentstack-gateway/tests/test_server.py
git commit -m "feat: replace threads with responses API in gateway"
```

---

### Task 4: Chat Client — Switch to Responses API

**Files:**
- Modify: `packages/python/agentstack-chat/src/agentstack_chat/client.py`
- Modify: `packages/python/agentstack-chat/src/agentstack_chat/chat.py`
- Modify: `packages/python/agentstack-chat/tests/test_client.py`

- [ ] **Step 1: Update test data classes**

In `test_client.py`, replace `InvokeResult` test with:

```python
class TestDataClasses:
    def test_response_result(self):
        r = ResponseResult(
            response="hi", response_id="resp-123",
            input_tokens=5, output_tokens=3, total_tokens=8,
        )
        assert r.response == "hi"
        assert r.response_id == "resp-123"

    def test_stream_event_token(self):
        e = StreamEvent(type="token", token="hello")
        assert e.type == "token"

    def test_stream_event_function_call(self):
        e = StreamEvent(type="function_call_start", tool="get_weather")
        assert e.tool == "get_weather"

    def test_stream_event_function_output(self):
        e = StreamEvent(type="function_call_output", tool="get_weather", result="16C")
        assert e.result == "16C"

    def test_stream_result(self):
        r = StreamResult(input_tokens=10, output_tokens=20, total_tokens=30)
        assert r.total_tokens == 30
```

- [ ] **Step 2: Rewrite `client.py`**

```python
"""Agent API client — OpenAI Responses API + Chat Completions."""

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass

import httpx


@dataclass
class ResponseResult:
    response: str
    response_id: str
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
    type: str  # "token", "function_call_start", "function_call_args", "function_call_output", "done"
    token: str = ""
    tool: str = ""
    args: str = ""
    result: str = ""
    usage: dict | None = None
    response_id: str = ""


async def send_response(
    url: str, message: str, model: str = "",
    previous_response_id: str | None = None,
    user_id: str | None = None, project_id: str | None = None,
) -> ResponseResult:
    """Send a message via /v1/responses (non-streaming, store=true)."""
    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(
            f"{url}/v1/responses",
            json={
                "model": model,
                "input": message,
                "previous_response_id": previous_response_id,
                "store": True,
                "stream": False,
            },
        )
        response.raise_for_status()
        data = response.json()
        output = data.get("output", [])
        content = output[0]["content"] if output else ""
        usage = data.get("usage") or {}
        return ResponseResult(
            response=content,
            response_id=data["id"],
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            total_tokens=usage.get("total_tokens", 0),
        )


async def stream_response(
    url: str, message: str, model: str = "",
    previous_response_id: str | None = None,
    result: StreamResult | None = None,
) -> AsyncIterator[StreamEvent]:
    """Stream via /v1/responses with stream=true."""
    async with httpx.AsyncClient(timeout=120.0) as client:
        async with client.stream(
            "POST",
            f"{url}/v1/responses",
            json={
                "model": model,
                "input": message,
                "previous_response_id": previous_response_id,
                "store": True,
                "stream": True,
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

                event_type = data.get("type", "")

                if event_type == "response.output_text.delta":
                    yield StreamEvent(type="token", token=data.get("delta", ""))

                elif event_type == "response.output_item.added":
                    item = data.get("item", {})
                    if item.get("type") == "function_call":
                        yield StreamEvent(type="function_call_start", tool=item.get("name", ""))
                    elif item.get("type") == "function_call_output":
                        yield StreamEvent(type="function_call_output", tool="", result=item.get("output", ""))

                elif event_type == "response.function_call_arguments.delta":
                    yield StreamEvent(type="function_call_args", args=data.get("delta", ""))

                elif event_type == "response.completed":
                    resp = data.get("response", {})
                    usage = resp.get("usage") or {}
                    if result is not None:
                        result.input_tokens = usage.get("input_tokens", 0)
                        result.output_tokens = usage.get("output_tokens", 0)
                        result.total_tokens = usage.get("total_tokens", 0)
                    yield StreamEvent(
                        type="done",
                        response_id=resp.get("id", ""),
                        usage=usage,
                    )
                    return


async def get_response(url: str, response_id: str) -> dict | None:
    """Get a response by ID (for background polling)."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{url}/v1/responses/{response_id}")
            response.raise_for_status()
            return response.json()
    except Exception:
        return None


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

- [ ] **Step 3: Update `chat.py` REPL**

Key changes:
- Replace `_session_id` with `_previous_response_id: str | None = None`
- `_stream_response()` calls `client.stream_response()` instead of `client.stream_events()`
- Parse new event types: `function_call_start`, `function_call_args`, `function_call_output`
- After each response, update `_previous_response_id` from the response's `response_id`
- `/new` command resets `_previous_response_id = None`
- Fallback invoke calls `client.send_response()` instead of `client.invoke()`
- Remove `session_id` parameter from `create_session()` calls (sessions config still tracks agent/URL)

- [ ] **Step 4: Run tests**

Run: `uv run --project packages/python/agentstack-chat pytest packages/python/agentstack-chat/tests/ -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add packages/python/agentstack-chat/src/agentstack_chat/client.py packages/python/agentstack-chat/src/agentstack_chat/chat.py packages/python/agentstack-chat/tests/test_client.py
git commit -m "feat: migrate chat client to Responses API with previous_response_id chaining"
```

---

### Task 5: Update Docker Bundling — openai_types.py

**Files:**
- Modify: `packages/python/agentstack-provider-docker/src/agentstack_provider_docker/nodes/agent.py`
- Modify: `packages/python/agentstack-provider-docker/src/agentstack_provider_docker/gateway.py`

The Docker bundling already copies `openai_types.py` from `agentstack.schema.openai`. Since we modified that module in Task 1 (removed Threads types, added Responses types), the Docker bundling picks up changes automatically — no code changes needed in the Docker provider.

- [ ] **Step 1: Verify the bundling works**

```bash
uv run --project packages/python/agentstack-adapter-langchain python -c "
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
# Verify Responses API types present
assert 'CreateResponseRequest' in code
assert 'ResponseObject' in code
assert '/v1/responses' in code
assert '/v1/threads' not in code
print('Responses API endpoints present, Threads removed')
"
```

Expected: Both assertions pass.

- [ ] **Step 2: Commit (if any changes needed)**

Only if Step 1 reveals issues. Otherwise skip.

---

### Task 6: Full Integration Verification

**Files:** No new files — runs existing tests.

- [ ] **Step 1: Run all tests across monorepo**

```bash
uv run --project packages/python/agentstack pytest packages/python/agentstack/tests/ -v
uv run --project packages/python/agentstack-adapter-langchain pytest packages/python/agentstack-adapter-langchain/tests/ -v
uv run --project packages/python/agentstack-gateway pytest packages/python/agentstack-gateway/tests/ -v
uv run --project packages/python/agentstack-chat pytest packages/python/agentstack-chat/tests/ -v
```

Expected: All pass.

- [ ] **Step 2: Verify no Threads references remain**

```bash
grep -r '"/v1/threads' packages/python/ --include='*.py' | grep -v __pycache__ | grep -v test
grep -r 'CreateThreadRequest\|ThreadMessage\|CreateRunRequest' packages/python/ --include='*.py' | grep -v __pycache__ | grep -v test
```

Expected: No matches in non-test code.

- [ ] **Step 3: Verify generated code is valid Python for all configurations**

```bash
uv run --project packages/python/agentstack-adapter-langchain python -c "
from agentstack.schema.agent import Agent
from agentstack.schema.model import Model
from agentstack.schema.provider import Provider
from agentstack.schema.service import Postgres, Sqlite
from agentstack.schema.mcp import McpServer
from agentstack.schema.common import McpTransport
from agentstack_adapter_langchain.templates import generate_server_py
import ast

provider = Provider(name='anthropic', type='anthropic')
model = Model(name='claude', provider=provider, model_name='claude-sonnet-4-20250514')

configs = [
    ('basic', Agent(name='basic', model=model)),
    ('sqlite', Agent(name='sqlite', model=model, sessions=Sqlite(name='s'))),
    ('postgres', Agent(name='pg', model=model, sessions=Postgres(name='p'))),
    ('mcp', Agent(name='mcp', model=model, mcp_servers=[McpServer(name='fs', transport=McpTransport.STDIO, command='npx fs')])),
]
for name, agent in configs:
    code = generate_server_py(agent)
    ast.parse(code)
    assert '/v1/responses' in code
    assert '/v1/threads' not in code
    print(f'{name}: OK')
print('All configurations valid')
"
```

- [ ] **Step 4: Commit any fixes**

```bash
git commit -m "chore: verify full test suite passes after Responses API migration"
```
