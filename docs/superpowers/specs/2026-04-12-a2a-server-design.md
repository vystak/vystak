# A2A Protocol Server — Design Spec

## Overview

Add Agent-to-Agent (A2A) protocol support to generated AgentStack servers. The A2A protocol (Google, open standard) enables agents to discover each other and communicate via a standardized JSON-RPC 2.0 interface. This spec covers the server side — making AgentStack agents A2A-compatible.

## Decisions

| Decision | Choice |
|----------|--------|
| Coexistence with REST API | Both side by side — A2A at `/a2a`, REST at `/invoke` and `/stream` |
| Task state tracking | LangGraph thread_id = A2A task_id, thin metadata layer in existing store |
| Agent Card | Auto-generated from agent schema |
| Interrupt/input_required | Supported from the start via LangGraph interrupt() |
| Streaming | Yes — tasks/sendSubscribe via SSE |

## A2A Protocol Summary

The A2A protocol (Agent-to-Agent) is a JSON-RPC 2.0 over HTTP standard for agent interoperability:

- **Agent Card** — discovery manifest at `/.well-known/agent.json`
- **Task** — unit of work with lifecycle: submitted → working → completed/failed/canceled/input_required
- **Message** — communication with parts (text, files, structured data)
- **Artifact** — task output
- **Streaming** — SSE for real-time task updates

## Endpoints

The generated server exposes both REST and A2A interfaces:

```
GET  /.well-known/agent.json  — A2A Agent Card (discovery)
POST /a2a                     — A2A JSON-RPC handler
POST /invoke                  — REST API (existing, unchanged)
POST /stream                  — REST SSE (existing, unchanged)
GET  /health                  — Health check (existing, unchanged)
```

## Agent Card

Auto-generated from the agent schema. Served at `GET /.well-known/agent.json`.

```json
{
  "name": "hello-agent",
  "description": "You are a helpful assistant built with AgentStack...",
  "url": "http://agentstack-hello-agent:8000",
  "version": "0.1.0",
  "capabilities": {
    "streaming": true,
    "pushNotifications": false
  },
  "skills": [
    {
      "id": "assistant",
      "name": "assistant",
      "description": "Tools: get_weather, get_time",
      "tags": ["get_weather", "get_time"]
    }
  ],
  "defaultInputModes": ["text/plain"],
  "defaultOutputModes": ["text/plain"]
}
```

Field mapping:
- `name` ← `agent.name`
- `description` ← `agent.instructions` (first 500 chars)
- `url` ← container hostname on Docker network (`http://agentstack-{name}:8000`)
- `skills` ← `agent.skills` (skill name, tool names as tags)
- `capabilities.streaming` ← `true` (always supported)
- `capabilities.pushNotifications` ← `false` (MVP)

## JSON-RPC Methods

All methods are dispatched via `POST /a2a`.

### tasks/send — Synchronous Message

```json
// Request
{
  "jsonrpc": "2.0",
  "method": "tasks/send",
  "id": 1,
  "params": {
    "id": "task-123",
    "message": {
      "role": "user",
      "parts": [{"text": "What's the weather in London?"}]
    }
  }
}

// Response (completed)
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "id": "task-123",
    "status": {
      "state": "completed",
      "message": {
        "role": "agent",
        "parts": [{"text": "London: Sunny, 15°C"}]
      },
      "timestamp": "2026-04-12T14:30:00Z"
    }
  }
}

// Response (input_required — agent interrupted)
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "id": "task-123",
    "status": {
      "state": "input_required",
      "message": {
        "role": "agent",
        "parts": [{"text": "Please confirm: send email to alice@example.com?"}]
      }
    }
  }
}
```

**Flow:**
1. Extract text from message parts
2. Create or resume LangGraph thread with thread_id = task_id
3. If task is new or completed: `agent.ainvoke({"messages": [("user", text)]})`
4. If task is in `input_required` state: `agent.ainvoke(Command(resume=text))`
5. Check result for `__interrupt__` — if present, return `input_required`
6. Otherwise return `completed` with agent's response

### tasks/sendSubscribe — Streaming

Same request format as `tasks/send`. Returns SSE stream:

```
event: task_status
data: {"id": "task-123", "status": {"state": "working"}, "final": false}

event: task_artifact
data: {"id": "task-123", "artifact": {"parts": [{"text": "London"}]}, "append": true}

event: task_artifact
data: {"id": "task-123", "artifact": {"parts": [{"text": ": Sunny, 15°C"}]}, "append": true, "lastChunk": true}

event: task_status
data: {"id": "task-123", "status": {"state": "completed", "message": {"role": "agent", "parts": [{"text": "London: Sunny, 15°C"}]}}, "final": true}
```

Uses `agent.astream_events` internally, same as the existing `/stream` endpoint.

### tasks/get — Check Task Status

```json
// Request
{"jsonrpc": "2.0", "method": "tasks/get", "id": 2, "params": {"id": "task-123"}}

// Response
{
  "jsonrpc": "2.0",
  "id": 2,
  "result": {
    "id": "task-123",
    "status": {"state": "completed", "timestamp": "2026-04-12T14:30:00Z"},
    "history": [
      {"role": "user", "parts": [{"text": "What's the weather?"}]},
      {"role": "agent", "parts": [{"text": "London: Sunny, 15°C"}]}
    ]
  }
}
```

Reads from LangGraph checkpointer by thread_id. Reconstructs history from checkpoint messages.

### tasks/cancel — Cancel a Task

```json
// Request
{"jsonrpc": "2.0", "method": "tasks/cancel", "id": 3, "params": {"id": "task-123"}}

// Response
{"jsonrpc": "2.0", "id": 3, "result": {"id": "task-123", "status": {"state": "canceled"}}}
```

Best-effort. If task already completed, returns the completed state.

## Task State Manager

A thin tracking layer stored in the memory store (same Postgres/SQLite/InMemory store used for long-term memory).

```python
class TaskManager:
    def __init__(self, store):
        self.store = store

    async def create_task(self, task_id: str) -> dict:
        task = {"state": "submitted", "created_at": now(), "updated_at": now()}
        await self.store.aput(("a2a", "tasks"), task_id, task)
        return task

    async def get_task(self, task_id: str) -> dict | None:
        item = await self.store.aget(("a2a", "tasks"), task_id)
        return item.value if item else None

    async def update_task(self, task_id: str, state: str, message: dict | None = None) -> dict:
        task = await self.get_task(task_id) or {}
        task["state"] = state
        task["updated_at"] = now()
        if message:
            task["last_message"] = message
        await self.store.aput(("a2a", "tasks"), task_id, task)
        return task
```

Namespace: `("a2a", "tasks")` — separate from memory namespaces.

Initialized in the server lifespan alongside checkpointer and store. For in-memory mode (no resources), uses a simple dict instead.

## Interrupt/Resume Flow

When a LangGraph agent calls `interrupt()`:

1. Agent invocation returns with `__interrupt__` in the result
2. A2A handler detects this, sets task state to `input_required`
3. Returns the interrupt payload as the task status message
4. When the caller sends another `tasks/send` with the same task_id:
   - Handler sees task is in `input_required` state
   - Invokes with `Command(resume=user_response)`
   - Graph resumes from the interrupt point

This works because the checkpointer persists the graph state at the interrupt point.

## File Changes

### Adapter — new module

```
packages/python/agentstack-adapter-langchain/src/agentstack_adapter_langchain/
├── a2a.py                # NEW — Agent Card builder, JSON-RPC code generation, TaskManager code
├── templates.py          # Update — generate_server_py adds A2A endpoints
└── adapter.py            # No changes
```

**`a2a.py` functions:**
- `generate_agent_card_code(agent)` → code string for AGENT_CARD dict and endpoint
- `generate_task_manager_code()` → code string for TaskManager class
- `generate_a2a_handler_code(agent)` → code string for `/a2a` endpoint and JSON-RPC dispatch
- `generate_a2a_stream_handler_code()` → code string for tasks/sendSubscribe SSE handler

### Templates update

**`generate_server_py`** adds:
- Import `Request` from fastapi
- Agent Card constant and `/.well-known/agent.json` route
- TaskManager class
- `/a2a` POST route with JSON-RPC dispatch
- `handle_tasks_send`, `handle_tasks_get`, `handle_tasks_cancel`, `handle_tasks_stream` functions
- TaskManager initialization in lifespan

### Generated requirements.txt

No new dependencies — JSON-RPC is plain JSON, SSE uses existing `sse-starlette`.

### Tests

```
packages/python/agentstack-adapter-langchain/tests/
├── test_a2a.py           # NEW — Agent Card generation, task manager code, JSON-RPC handler code
└── test_templates.py     # Update — verify A2A endpoints in generated server, ast.parse()
```

## Testing Strategy

### test_a2a.py
- `test_agent_card_has_name` — card includes agent name
- `test_agent_card_has_skills` — card includes skills from agent schema
- `test_agent_card_has_capabilities` — streaming=true
- `test_agent_card_code_parseable` — generated code passes ast.parse()
- `test_task_manager_code_parseable` — generated code passes ast.parse()
- `test_a2a_handler_code_parseable` — generated code passes ast.parse()
- `test_jsonrpc_dispatch_methods` — handler code contains all four methods

### test_templates.py (additions)
- `test_server_has_agent_card_endpoint` — `/.well-known/agent.json` in generated server
- `test_server_has_a2a_endpoint` — `/a2a` in generated server
- `test_server_has_task_manager` — TaskManager class in generated server
- `test_server_a2a_parseable` — generated server with A2A passes ast.parse()

## What This Spec Does NOT Cover

- A2A client (calling other agents via A2A) — separate spec
- Agent discovery mechanism (registry, DNS) — separate spec
- Push notifications — future enhancement
- A2A authentication/security schemes — future enhancement
- File/binary parts in messages — text only for MVP
- Multi-turn artifact streaming — text artifacts only
