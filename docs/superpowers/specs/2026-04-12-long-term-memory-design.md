# Long-Term Memory — Design Spec

## Overview

Add long-term memory to AgentStack agents. Memories persist across sessions and are scoped to user, project, or global namespaces. The agent automatically recalls relevant memories at the start of each conversation and can save/forget memories via tools.

## Decisions

| Decision | Choice |
|----------|--------|
| Memory trigger | Hybrid — automatic recall, selective save via tool |
| Recall method | Semantic search with fallback to full scan |
| User identity | Explicit `user_id` field in API requests |
| Memory scopes | Three: user, project, global |
| Save tool | content + scope, minimal. Plus forget_memory for deletion |
| SQLite store | Custom AsyncSqliteStore in core SDK |

## Memory Architecture

### Scopes

Memories live in three namespaces:
- `("user", user_id, "memories")` — personal to a user (preferences, facts about them)
- `("project", project_id, "memories")` — shared within a project (team knowledge, project context)
- `("global", "memories")` — shared across all users (common knowledge)

### Flow

On every request:

1. Server receives `message`, `user_id`, `session_id`, optional `project_id`
2. Server searches memories across all applicable scopes using the user's message as a query
3. Recalled memories are formatted and injected into the system prompt
4. Agent runs with `save_memory` and `forget_memory` tools available
5. Agent can save new memories during the conversation using the tools

### Tools

**`save_memory(content: str, scope: str = "user") -> str`**

Save a fact or preference to long-term memory. Scope is "user", "project", or "global". Uses `user_id` and `project_id` from the request context to build the namespace.

**`forget_memory(memory_id: str) -> str`**

Remove a specific memory by its ID. The ID is shown in recalled memories so the user can reference it.

### Recalled Memories Format

Injected into the system prompt:

```
## Recalled Memories
- [mem_abc123] User prefers dark mode (scope: user)
- [mem_def456] Project deadline is March 15 (scope: project)
- [mem_ghi789] Company uses Python 3.11+ (scope: global)
```

Memory IDs are shown so the user can ask the agent to forget specific ones.

### System Prompt Addition

The adapter appends to the agent's instructions:

```
## Memory
You have long-term memory that persists across conversations.
At the start of each conversation, relevant memories are provided below.
Use save_memory to remember important facts, preferences, or instructions.
Use forget_memory to remove incorrect memories.
```

## Store Backend Selection

The store backend matches the resource engine, same pattern as checkpointers:

**Postgres engine:**
- `AsyncPostgresStore` from `langgraph.store.postgres.aio`
- Shares the same Postgres container and connection string as the checkpointer
- Supports semantic search natively

**SQLite engine:**
- Custom `AsyncSqliteStore` from `agentstack.stores.sqlite`
- Uses the same SQLite volume as the checkpointer
- No semantic search — returns all items from namespace (full scan)

**No resource (in-memory):**
- `InMemoryStore` from `langgraph.store.memory`
- Memories lost on restart

## AsyncSqliteStore

Custom store implementation in the core SDK that follows the LangGraph `BaseStore` interface.

### Location

`packages/python/agentstack/src/agentstack/stores/sqlite.py`

### Schema

```sql
CREATE TABLE IF NOT EXISTS store (
    namespace TEXT NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (namespace, key)
);
```

### Interface

```python
class AsyncSqliteStore:
    @classmethod
    def from_conn_string(cls, path: str) -> AsyncContextManager[AsyncSqliteStore]:
        """Async context manager that creates/opens the SQLite database."""

    async def setup(self) -> None:
        """Create the store table if it doesn't exist."""

    async def aput(self, namespace: tuple[str, ...], key: str, value: dict) -> None:
        """Upsert a memory."""

    async def aget(self, namespace: tuple[str, ...], key: str) -> Item | None:
        """Get a single item."""

    async def asearch(self, namespace: tuple[str, ...], *, query: str | None = None, limit: int = 10) -> list[Item]:
        """List items in namespace. Query parameter ignored (no embeddings)."""

    async def adelete(self, namespace: tuple[str, ...], key: str) -> None:
        """Remove an item."""
```

`Item` is a simple dataclass matching LangGraph's store item format:
```python
@dataclass
class Item:
    namespace: tuple[str, ...]
    key: str
    value: dict
    created_at: datetime
```

### Dependencies

Uses `aiosqlite` for async SQLite access. Added to `agentstack` core package dependencies.

## Generated Code Changes

### agent.py

Adds:
- Store initialization (same DB_URI as checkpointer, or InMemoryStore)
- `save_memory` and `forget_memory` tool functions
- `create_agent(checkpointer, store)` now accepts store parameter
- Memory-related system prompt addition

### server.py

Changes to request model:
```python
class InvokeRequest(BaseModel):
    message: str
    session_id: str | None = None
    user_id: str | None = None
    project_id: str | None = None
```

Before invoking the agent:
1. Search memories across applicable scopes (user, project, global)
2. Format recalled memories
3. Prepend as system message or add to configurable context

The agent invocation passes context:
```python
config = {
    "configurable": {
        "thread_id": session_id,
        "user_id": user_id,
        "project_id": project_id,
    }
}
```

Lifespan initializes both checkpointer and store:
```python
@asynccontextmanager
async def lifespan(app):
    global _agent, _store
    async with (
        AsyncPostgresSaver.from_conn_string(DB_URI) as checkpointer,
        AsyncPostgresStore.from_conn_string(DB_URI) as store,
    ):
        await checkpointer.setup()
        await store.setup()
        _store = store
        _agent = create_agent(checkpointer, store)
        yield
```

## File Changes

### Core SDK — new module

```
packages/python/agentstack/src/agentstack/stores/
├── __init__.py           # re-export AsyncSqliteStore
└── sqlite.py             # AsyncSqliteStore implementation
```

New dependency in `packages/python/agentstack/pyproject.toml`: `aiosqlite>=0.20`

### Adapter — template changes

```
packages/python/agentstack-adapter-langchain/src/agentstack_adapter_langchain/
└── templates.py          # memory tools, recall logic, store initialization
```

### Tests

```
packages/python/agentstack/tests/
└── test_sqlite_store.py              # AsyncSqliteStore unit tests

packages/python/agentstack-adapter-langchain/tests/
└── test_templates.py                 # update: memory tools in generated code
```

### No changes needed

- Docker provider (already provisions Postgres + SQLite)
- CLI commands
- Agent schema
- Resource provisioning

## Testing Strategy

### test_sqlite_store.py
- `test_put_and_get` — store and retrieve a memory
- `test_search` — list memories in a namespace
- `test_search_limit` — respects limit parameter
- `test_search_different_namespace` — namespaces are isolated
- `test_delete` — remove a memory
- `test_upsert` — overwrite existing key
- `test_setup_creates_table` — idempotent table creation
- `test_context_manager` — from_conn_string lifecycle

### test_templates.py (additions)
- `test_memory_tools_generated` — save_memory and forget_memory in generated code
- `test_memory_system_prompt` — memory instructions in system prompt
- `test_postgres_store_import` — generates AsyncPostgresStore for postgres
- `test_sqlite_store_import` — generates AsyncSqliteStore for sqlite
- `test_no_resource_uses_inmemory_store` — InMemoryStore as default
- `test_server_accepts_user_id` — user_id in request model
- `test_server_accepts_project_id` — project_id in request model

## What This Spec Does NOT Cover

- Embedding model configuration for semantic search
- Memory size limits or eviction policies
- Memory export/import
- Memory sharing permissions between users
- Admin tools for viewing/managing all memories
- Memory encryption at rest
