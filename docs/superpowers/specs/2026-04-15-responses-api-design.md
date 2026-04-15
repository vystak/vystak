# Responses API + Stateless Chat Completions Design

**Date:** 2026-04-15
**Status:** Draft

## Overview

Evolve AgentStack's OpenAI-compatible API layer to follow the industry direction: stateless Chat Completions + stateful Responses API. Replace the Threads/Assistants API (which OpenAI is deprecating in August 2026) with the Responses API. Make Chat Completions fully stateless.

## Goals

1. **Stateless Chat Completions** — Client sends full `messages` array. No session, no checkpointer. Memory recall/save still available via `user_id`/`project_id`.
2. **Stateful Responses API** — `previous_response_id` chaining backed by LangGraph checkpointers. `store: true/false` toggle. Background execution. Streaming with OpenAI-standard SSE events.
3. **Remove Threads API** — Clean break, no backwards compatibility layer.

## Non-Goals

- Built-in tools (web search, code interpreter) — AgentStack uses MCP for this
- Full OpenAI Responses API surface (annotations, reasoning, file outputs)
- Backwards compatibility with Threads/Assistants API

## Architecture

### Approach: Translation Layer in Gateway + Agent Server

Same pattern as the existing OpenAI migration. Add Responses API routes to both the generated agent `server.py` and the gateway. Responses map directly to LangGraph `thread_id` for `store: true`, bypass checkpointer for `store: false`.

### Endpoint Summary

**Agent-level:**

| Endpoint | Method | State | Purpose |
|----------|--------|-------|---------|
| `/v1/models` | GET | — | Single-entry ModelList (unchanged) |
| `/v1/chat/completions` | POST | Stateless | Full messages array, no checkpointer |
| `/v1/responses` | POST | Stateful | `previous_response_id` chaining, `store: true/false` |
| `/v1/responses/{response_id}` | GET | — | Retrieve response (for background polling) |
| `/health` | GET | — | Unchanged |
| `/.well-known/agent.json` | GET | — | Unchanged |
| `/a2a` | POST | — | Unchanged |

**Gateway-level:**

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/v1/models` | GET | Aggregates registered agents (unchanged) |
| `/v1/chat/completions` | POST | Routes by `model` via A2A. Stateless. |
| `/v1/responses` | POST | Routes by `model`. Proxies to agent's `/v1/responses`. |
| `/v1/responses/{response_id}` | GET | Looks up agent from response mapping, proxies. |
| All existing registration/routing endpoints | * | Unchanged |

**Removed from both agent and gateway:**
- `POST /v1/threads`
- `GET /v1/threads/{thread_id}/messages`
- `POST /v1/threads/{thread_id}/messages`
- `POST /v1/threads/{thread_id}/runs`

## Shared Types (`openai_types.py`)

### Remove

- `CreateThreadRequest`, `Thread`, `CreateMessageRequest`, `ThreadMessage`, `CreateRunRequest`, `Run`

### Add

```python
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

### Modify

`ChatCompletionRequest` — remove `session_id`, keep `user_id` and `project_id`.

## Chat Completions — Stateless

### Flow (Agent)

1. Receive `ChatCompletionRequest` with full `messages` array
2. If `user_id`/`project_id` provided and persistent store available, recall memories and prepend as system message
3. Convert all messages to LangGraph format: `[("system", ...), ("user", ...), ("assistant", ...), ...]`
4. Invoke `graph.ainvoke({"messages": messages})` with a random one-shot `thread_id` (no checkpoint persisted)
5. If persistent store, process memory actions (save/forget)
6. Return `ChatCompletionResponse`

### Flow (Gateway)

1. Parse `model` field to resolve agent
2. Send A2A `tasks/send` with the full messages (or proxy directly to agent's `/v1/chat/completions`)
3. Translate response back to `ChatCompletionResponse`

## Responses API — Stateful

### Response ID = Thread ID

The `id` field of a `ResponseObject` doubles as the LangGraph `thread_id`. When `store: true`:
- First response in a chain: generate new UUID, use as both response ID and thread_id
- Subsequent responses: `previous_response_id` IS the `thread_id` to continue

### Flow: `store: true` (Agent)

1. If `previous_response_id` provided, use it as `thread_id` (checkpointer has history)
2. If not, generate new UUID — becomes both `response_id` and `thread_id`
3. Parse `input`: string → single user message, array → multiple messages
4. Memory recall via `user_id`/`project_id` if available
5. `graph.ainvoke()` with `config={"configurable": {"thread_id": response_id}}`
6. Memory save if applicable
7. Store response in local response store (for `GET /v1/responses/{id}`)
8. Return `ResponseObject` with `id` = thread_id

### Flow: `store: false` (Agent)

1. Parse input same as above
2. Pass messages directly to `graph.ainvoke()` without checkpointer (random one-shot thread_id)
3. Still generate a response ID for return value
4. Do NOT persist to response store — `GET /v1/responses/{id}` will return 404
5. `previous_response_id` chaining to this response will return 400

### Flow: `background: true` (Agent)

1. Generate response ID
2. Store initial response with `status: "in_progress"` in response store
3. Launch `asyncio.create_task()` to run the agent
4. Return `ResponseObject` immediately with `status: "in_progress"`
5. Background task updates response store on completion: `status: "completed"`, `output`, `usage`
6. Client polls `GET /v1/responses/{id}` until `status` is `"completed"` or `"failed"`

### Flow (Gateway)

1. Parse `model` field to resolve agent
2. If `previous_response_id` provided, look up `response_id → agent_name` mapping to verify routing consistency
3. Proxy request to agent's `POST /v1/responses`
4. Store `response_id → agent_name` mapping for the returned response ID
5. For `GET /v1/responses/{id}`, look up agent from mapping and proxy

### Response-Agent Mapping (Gateway)

Gateway stores `response_id → agent_name` in its existing `RegistrationStore` pattern (in-memory for now, SQLite-backed for persistence). Same approach as the ThreadStore it replaces.

```python
class ResponseStore:
    """In-memory store for response-to-agent bindings."""

    def __init__(self):
        self._responses: dict[str, dict] = {}

    def save(self, response_id: str, agent_name: str, data: dict) -> None:
        self._responses[response_id] = {"agent_name": agent_name, **data}

    def get(self, response_id: str) -> dict | None:
        return self._responses.get(response_id)
```

## Streaming Format

Follows OpenAI Responses API SSE spec:

### Response lifecycle

```
data: {"type": "response.created", "response": {"id": "resp-...", "status": "in_progress"}}
```

### Content text streaming

```
data: {"type": "response.output_item.added", "item": {"type": "message", "role": "assistant"}}
data: {"type": "response.content_part.added", "part": {"type": "output_text", "text": ""}}
data: {"type": "response.output_text.delta", "delta": "Hello"}
data: {"type": "response.output_text.delta", "delta": " world"}
data: {"type": "response.output_text.done", "text": "Hello world"}
```

### Function/tool calls

```
data: {"type": "response.output_item.added", "item": {"type": "function_call", "name": "get_weather"}}
data: {"type": "response.function_call_arguments.delta", "delta": "{\"city\":"}
data: {"type": "response.function_call_arguments.delta", "delta": "\"Tokyo\"}"}
data: {"type": "response.function_call_arguments.done", "arguments": "{\"city\":\"Tokyo\"}"}
```

### Function/tool results

```
data: {"type": "response.output_item.added", "item": {"type": "function_call_output", "output": "16C, light rain"}}
```

### Response complete

```
data: {"type": "response.completed", "response": {"id": "resp-...", "status": "completed", "output": [...], "usage": {...}}}
data: [DONE]
```

### LangGraph event mapping

| LangGraph Event | Responses SSE Event |
|----------------|---------------------|
| `AIMessageChunk.content` (text) | `response.output_text.delta` |
| `AIMessageChunk.tool_call_chunks` (name) | `response.output_item.added` (function_call) |
| `AIMessageChunk.tool_call_chunks` (args) | `response.function_call_arguments.delta` |
| Tool call complete | `response.function_call_arguments.done` |
| `ToolMessage` | `response.output_item.added` (function_call_output) |
| Stream end | `response.completed` + `[DONE]` |

## Chat Client Changes

### `client.py`

- `invoke()` → calls `POST /v1/responses` with `store: true`, returns response including `id`
- `stream_events()` → calls `POST /v1/responses` with `stream: true`, parses new SSE event types
- New: `get_response(url, response_id)` → `GET /v1/responses/{id}`
- `list_models()`, `health()`, `gateway_routes()` → unchanged

### `chat.py` REPL

- Replace `_session_id` with `_previous_response_id`
- Each turn: send with `previous_response_id` pointing to last response's `id`
- `/new` command resets `_previous_response_id` to `None`
- Parse new SSE event types for streaming display

### StreamEvent updates

New event types: `"function_call_start"`, `"function_call_args"`, `"function_call_output"` alongside existing `"token"`, `"done"`.

## Error Handling

All `/v1/` endpoints return OpenAI-format errors:

```json
{
  "error": {
    "message": "Response not found",
    "type": "invalid_request_error",
    "param": "previous_response_id",
    "code": "response_not_found"
  }
}
```

| Scenario | HTTP Status | `code` |
|----------|------------|--------|
| Unknown model/agent | 404 | `model_not_found` |
| Response not found | 404 | `response_not_found` |
| `previous_response_id` not found | 404 | `response_not_found` |
| Chaining to `store: false` response | 400 | `invalid_request` |
| Missing required field | 400 | `invalid_value` |
| Agent unhealthy/offline | 503 | `agent_unavailable` |
| Internal error | 500 | `internal_error` |

## Migration Impact

- **Breaking change**: Threads API endpoints removed. Clients using threads must switch to Responses API.
- **Breaking change**: Chat Completions `session_id` field removed. Clients relying on server-side session state must switch to Responses API.
- **Chat client**: Updated in the same release — uses Responses API for multi-turn.
- **A2A**: Unchanged — agent-to-agent communication unaffected.
- **Existing deployments**: `agentstack apply --force` regenerates server code with new endpoints.
