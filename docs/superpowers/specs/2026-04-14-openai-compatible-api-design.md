# OpenAI-Compatible API Migration

**Date:** 2026-04-14
**Status:** Draft

## Overview

Migrate AgentsStack to expose OpenAI-compatible API endpoints for agent communication and session management. Each agent appears as a model (`agentstack/{agent-name}`) accessible via any OpenAI SDK client. The existing A2A protocol remains for agent-to-agent communication.

## Goals

1. **Ecosystem compatibility** — Any OpenAI SDK client (Python, JS, curl) can talk to AgentStack agents out of the box
2. **Standard model gateway** — The gateway acts as an OpenAI-compatible model router where agents appear as "models"
3. **Thread management** — Lightweight Threads API wrapping existing LangGraph checkpointers for conversation persistence

## Non-Goals

- Full OpenAI Assistants API surface (file attachments, code interpreter, vector stores)
- Authentication (deferred to a future design)
- Replacing A2A for agent-to-agent communication

## Architecture

### Approach: Translation Layer in Gateway + Agent Server

Add OpenAI-compatible route handlers to both the generated agent `server.py` and the gateway. These translate between OpenAI request/response formats and existing LangGraph internals (agents) or A2A calls (gateway).

- **Agent-level**: New `/v1/` routes call the same `graph.ainvoke()` / `graph.astream_events()` already in use, reformatting I/O as OpenAI objects
- **Gateway-level**: `/v1/models` aggregates registered agents, `/v1/chat/completions` routes by `model` field via A2A, `/v1/threads/*` proxies to agents
- **Removal**: `/invoke`, `/stream` routes removed from agents. `/invoke/{agent}`, `/stream/{agent}`, `/proxy/{agent}/*` removed from gateway

### What Stays Unchanged

- A2A JSON-RPC 2.0 (`/a2a`) — agent-to-agent communication
- Agent card (`/.well-known/agent.json`) — discovery metadata
- Health endpoint (`/health`)
- Gateway registration (`/register`, `/unregister`, `/agents`)
- Gateway provider routing (`/routes`, `/register-route`, `/register-provider`)
- LangGraph agent graph (`agent.py`), store (`store.py`), tools (`tools/`)

## Shared Types (`agentstack.schema.openai`)

New module in the `agentstack` core package with Pydantic models used by both agents and gateway.

### Models Resource

```python
class ModelObject(BaseModel):
    id: str                          # "agentstack/assistant-agent"
    object: str = "model"
    created: int                     # unix timestamp
    owned_by: str = "agentstack"

class ModelList(BaseModel):
    object: str = "list"
    data: list[ModelObject]
```

### Chat Completions

```python
class ChatMessage(BaseModel):
    role: str                        # "system", "user", "assistant"
    content: str | None = None

class ChatCompletionRequest(BaseModel):
    model: str                       # "agentstack/assistant-agent"
    messages: list[ChatMessage]
    stream: bool = False
    # Extension fields (non-standard, optional)
    session_id: str | None = None
    user_id: str | None = None
    project_id: str | None = None

class Choice(BaseModel):
    index: int = 0
    message: ChatMessage
    finish_reason: str = "stop"

class CompletionUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

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
    # Extension: custom event data for tool calls, sub-agent activity
    x_agentstack: dict | None = None
```

### Threads API

```python
class Thread(BaseModel):
    id: str
    object: str = "thread"
    created_at: int
    metadata: dict = {}

class CreateThreadRequest(BaseModel):
    model: str | None = None         # Optional — bind to agent on creation
    metadata: dict = {}

class ContentBlock(BaseModel):
    type: str = "text"
    text: str

class ThreadMessage(BaseModel):
    id: str
    object: str = "thread.message"
    thread_id: str
    role: str
    content: list[ContentBlock]
    created_at: int

class CreateMessageRequest(BaseModel):
    role: str
    content: str

class CreateRunRequest(BaseModel):
    model: str                       # Required — "agentstack/assistant-agent"
    stream: bool = False

class Run(BaseModel):
    id: str
    object: str = "thread.run"
    thread_id: str
    model: str
    status: str                      # "queued", "in_progress", "completed", "failed"
    created_at: int
    completed_at: int | None = None
```

### Error Response

```python
class ErrorDetail(BaseModel):
    message: str
    type: str
    param: str | None = None
    code: str

class ErrorResponse(BaseModel):
    error: ErrorDetail
```

## Agent-Level Endpoints

Generated by `templates.py` in `agentstack-adapter-langchain`. Replace `/invoke` and `/stream` with:

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/v1/models` | GET | Single-entry `ModelList` with `agentstack/{name}` |
| `/v1/chat/completions` | POST | Non-streaming and streaming |
| `/v1/threads` | POST | Create thread (generates session_id) |
| `/v1/threads/{thread_id}/messages` | GET | List messages from checkpointer |
| `/v1/threads/{thread_id}/messages` | POST | Add message to thread |
| `/v1/threads/{thread_id}/runs` | POST | Execute agent on thread |

### Chat Completions Flow (Agent)

1. Request arrives with `messages` array and optional `session_id`
2. If no `session_id`, generate a UUID
3. Extract the last user message as agent input
4. Memory recall (if sessions configured) using `session_id` as `thread_id`
5. Non-streaming: `graph.ainvoke()` → format as `ChatCompletionResponse`
6. Streaming: `graph.astream_events()` → emit `ChatCompletionChunk` SSE events
   - Standard: `data: {"choices":[{"delta":{"content":"token"}}]}\n\n`
   - Extension: `x_agentstack` field carries tool call / sub-agent events
   - Termination: `data: [DONE]\n\n`
7. Memory action processing (save/forget) after response

### Threads API Flow (Agent)

- `POST /v1/threads` — Generate UUID, return `Thread`. Optional `model` field stored in metadata. Checkpointer creates state lazily on first run.
- `POST /v1/threads/{id}/messages` — Store message by adding to thread state
- `GET /v1/threads/{id}/messages` — Read checkpoint history for thread_id, return full conversation (both user and assistant messages) as `ThreadMessage` list
- `POST /v1/threads/{id}/runs` — Execute agent on thread. Uses latest unprocessed message. Returns `Run` with status. `model` field required (must match this agent's model ID).

## Gateway-Level Endpoints

### New Routes

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/v1/models` | GET | Aggregates all registered agents as model entries |
| `/v1/chat/completions` | POST | Routes by `model` field via A2A |
| `/v1/threads` | POST | Creates thread, stores agent association |
| `/v1/threads/{thread_id}/messages` | GET/POST | Proxies to resolved agent |
| `/v1/threads/{thread_id}/runs` | POST | Proxies to resolved agent |

### Removed Routes

| Endpoint | Replaced By |
|----------|-------------|
| `POST /invoke/{agent_name}` | `/v1/chat/completions` with `model` field |
| `POST /stream/{agent_name}` | `/v1/chat/completions` with `stream: true` |
| `POST /proxy/{agent_name}/invoke` | `/v1/chat/completions` |
| `POST /proxy/{agent_name}/stream` | `/v1/chat/completions` with `stream: true` |
| `GET /proxy/{agent_name}/health` | `/agents` or direct agent `/health` |

### Chat Completions Flow (Gateway)

1. Parse `model` field — strip `agentstack/` prefix to get agent name
2. Look up agent URL from `RegistrationStore`
3. Return 404 (OpenAI error format) if agent not found
4. Non-streaming: A2A `tasks/send` to agent → translate response to `ChatCompletionResponse`
5. Streaming: A2A `tasks/sendSubscribe` to agent → translate SSE events to `ChatCompletionChunk` stream
6. Propagate metadata: `session_id`, `user_id`, `project_id` through A2A metadata

### Thread-Agent Binding (Gateway)

The gateway needs to know which agent a thread belongs to for proxying.

- **On creation** (`POST /v1/threads`): If `model` field provided, store `thread_id → agent_name` mapping
- **Deferred binding**: If no `model` on creation, bind on first `POST /v1/threads/{id}/runs` (which requires `model`)
- **Storage**: Thread-agent mappings stored in gateway's `RegistrationStore` (SQLite)
- **Error**: If thread has no binding and `runs` is called without `model`, return 400

### Models Endpoint (Gateway)

`GET /v1/models` returns a `ModelList` built from registered agents:

- For each agent in `RegistrationStore`, create a `ModelObject` with `id: "agentstack/{name}"`
- `created` timestamp from `registered_at` field on the route
- `owned_by: "agentstack"`

## Chat Client Changes

### `client.py`

- `invoke()` → `POST /v1/chat/completions` with `stream: false`
- `stream_events()` → `POST /v1/chat/completions` with `stream: true`, parse `ChatCompletionChunk` events
- `health()` → unchanged
- `gateway_routes()` → unchanged
- New: `list_models()` → `GET /v1/models`

### `chat.py` REPL

- `/agents` command can pull from `/v1/models` when connected to gateway
- Session management maps to Threads API
- StreamEvent parsing: extract `content` from `choices[0].delta.content`, tool/agent events from `x_agentstack`

### SDK Compatibility

After migration, any OpenAI SDK client works:

```python
from openai import OpenAI
client = OpenAI(base_url="http://localhost:8080/v1", api_key="unused")
response = client.chat.completions.create(
    model="agentstack/assistant-agent",
    messages=[{"role": "user", "content": "Hello"}]
)
```

## Code Generation Changes

### `templates.py` (LangChain Adapter)

- **Remove**: `InvokeRequest`, `InvokeResponse` definitions, `/invoke` route handler, `/stream` route handler
- **Add**: Import shared types from `agentstack.schema.openai`
- **Add**: `/v1/models`, `/v1/chat/completions`, `/v1/threads/*` route handlers
- **Reuse**: Existing `run_agent()` / streaming logic, just new entry points with OpenAI-shaped I/O

### Agent Card Enhancement

Add `models` field to agent card for gateway discovery:

```python
AGENT_CARD = {
    ...
    "models": ["agentstack/{agent_name}"],
    ...
}
```

### No Changes Needed

- `generate_agent_py()` — LangGraph agent graph unchanged
- `generate_store_py()` — memory/session store unchanged
- `generate_tools_py()` — tool definitions unchanged
- `generate_a2a_handler_code()` — A2A protocol unchanged

## Error Handling

All `/v1/` endpoints return errors in OpenAI's standard format:

```json
{
  "error": {
    "message": "Agent 'agentstack/foo' not found",
    "type": "invalid_request_error",
    "param": "model",
    "code": "model_not_found"
  }
}
```

| Scenario | HTTP Status | `type` | `code` |
|----------|------------|--------|--------|
| Unknown model/agent | 404 | `invalid_request_error` | `model_not_found` |
| Missing required field | 400 | `invalid_request_error` | `invalid_value` |
| Agent unhealthy/offline | 503 | `server_error` | `agent_unavailable` |
| Agent timeout | 504 | `server_error` | `timeout` |
| Thread not found | 404 | `invalid_request_error` | `thread_not_found` |
| Thread not bound to agent | 400 | `invalid_request_error` | `thread_not_bound` |
| Internal error | 500 | `server_error` | `internal_error` |

A FastAPI exception handler on `/v1/` routes wraps unhandled errors into this format. Existing `/health`, `/a2a`, `/.well-known/agent.json` routes keep their current error behavior.

## Migration Impact

- **Existing deployments**: `agentstack apply` regenerates server code — redeployment picks up new endpoints automatically
- **Hash detection**: Server template change triggers redeploy via hash-based change detection
- **A2A compatibility**: Agent-to-agent calls unaffected
- **Breaking change**: Clients using `/invoke` or `/stream` must migrate to `/v1/chat/completions`
- **Chat client**: Updated in the same release cycle
