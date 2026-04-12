# Long-Term Memory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add long-term memory to AgentStack agents — memories persist across sessions, scoped to user/project/global, with automatic recall and save/forget tools.

**Architecture:** Custom AsyncSqliteStore in core SDK for SQLite backend, LangGraph's AsyncPostgresStore for Postgres. Adapter templates generate memory tools (save/forget) and recall logic in the server. Three memory scopes: user, project, global.

**Tech Stack:** Python 3.11+, aiosqlite, LangGraph stores, pytest

---

### Task 1: AsyncSqliteStore

**Files:**
- Modify: `packages/python/agentstack/pyproject.toml`
- Create: `packages/python/agentstack/src/agentstack/stores/__init__.py`
- Create: `packages/python/agentstack/src/agentstack/stores/sqlite.py`
- Create: `packages/python/agentstack/tests/test_sqlite_store.py`

- [ ] **Step 1: Add aiosqlite dependency**

In `packages/python/agentstack/pyproject.toml`, add `"aiosqlite>=0.20"` to dependencies:

```toml
dependencies = [
    "pydantic>=2.0",
    "pyyaml>=6.0",
    "aiosqlite>=0.20",
]
```

Run: `cd /Users/akolodkin/Developer/work/AgentsStack && uv sync`

- [ ] **Step 2: Write tests**

`packages/python/agentstack/tests/test_sqlite_store.py`:
```python
import asyncio
from datetime import datetime

import pytest

from agentstack.stores.sqlite import AsyncSqliteStore, Item


@pytest.fixture()
def store(tmp_path):
    db_path = str(tmp_path / "test.db")

    async def _make_store():
        async with AsyncSqliteStore.from_conn_string(db_path) as s:
            await s.setup()
            return s, db_path

    s, path = asyncio.get_event_loop().run_until_complete(_make_store())
    return s, path


@pytest.fixture()
def run(store):
    """Helper to run async functions."""
    s, _ = store

    def _run(coro):
        return asyncio.get_event_loop().run_until_complete(coro)

    return _run, s


class TestAsyncSqliteStore:
    def test_put_and_get(self, run):
        _run, store = run
        _run(store.aput(("user", "u1", "memories"), "key1", {"data": "likes coffee"}))
        item = _run(store.aget(("user", "u1", "memories"), "key1"))
        assert item is not None
        assert item.value == {"data": "likes coffee"}
        assert item.key == "key1"
        assert item.namespace == ("user", "u1", "memories")

    def test_get_missing(self, run):
        _run, store = run
        item = _run(store.aget(("user", "u1", "memories"), "nonexistent"))
        assert item is None

    def test_search(self, run):
        _run, store = run
        _run(store.aput(("user", "u1", "memories"), "k1", {"data": "fact one"}))
        _run(store.aput(("user", "u1", "memories"), "k2", {"data": "fact two"}))
        _run(store.aput(("user", "u2", "memories"), "k3", {"data": "other user"}))

        results = _run(store.asearch(("user", "u1", "memories")))
        assert len(results) == 2
        keys = {r.key for r in results}
        assert keys == {"k1", "k2"}

    def test_search_limit(self, run):
        _run, store = run
        for i in range(5):
            _run(store.aput(("ns",), f"k{i}", {"data": f"item {i}"}))

        results = _run(store.asearch(("ns",), limit=3))
        assert len(results) == 3

    def test_search_different_namespace(self, run):
        _run, store = run
        _run(store.aput(("ns1",), "k1", {"data": "in ns1"}))
        _run(store.aput(("ns2",), "k2", {"data": "in ns2"}))

        results = _run(store.asearch(("ns1",)))
        assert len(results) == 1
        assert results[0].key == "k1"

    def test_delete(self, run):
        _run, store = run
        _run(store.aput(("ns",), "k1", {"data": "to delete"}))
        _run(store.adelete(("ns",), "k1"))
        item = _run(store.aget(("ns",), "k1"))
        assert item is None

    def test_upsert(self, run):
        _run, store = run
        _run(store.aput(("ns",), "k1", {"data": "original"}))
        _run(store.aput(("ns",), "k1", {"data": "updated"}))
        item = _run(store.aget(("ns",), "k1"))
        assert item.value == {"data": "updated"}

    def test_setup_idempotent(self, run):
        _run, store = run
        _run(store.setup())
        _run(store.setup())
        _run(store.aput(("ns",), "k1", {"data": "works"}))
        item = _run(store.aget(("ns",), "k1"))
        assert item is not None


class TestContextManager:
    def test_from_conn_string(self, tmp_path):
        db_path = str(tmp_path / "cm_test.db")

        async def _test():
            async with AsyncSqliteStore.from_conn_string(db_path) as store:
                await store.setup()
                await store.aput(("ns",), "k1", {"data": "test"})
                item = await store.aget(("ns",), "k1")
                assert item.value == {"data": "test"}

        asyncio.get_event_loop().run_until_complete(_test())
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest packages/python/agentstack/tests/test_sqlite_store.py -v`

Expected: FAIL — module not found.

- [ ] **Step 4: Implement AsyncSqliteStore**

`packages/python/agentstack/src/agentstack/stores/__init__.py`:
```python
"""AgentStack store implementations."""

from agentstack.stores.sqlite import AsyncSqliteStore, Item

__all__ = ["AsyncSqliteStore", "Item"]
```

`packages/python/agentstack/src/agentstack/stores/sqlite.py`:
```python
"""Async SQLite-backed key-value store for long-term memory."""

import json
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone

import aiosqlite


@dataclass
class Item:
    """A single item in the store."""

    namespace: tuple[str, ...]
    key: str
    value: dict
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class AsyncSqliteStore:
    """Async SQLite-backed store compatible with LangGraph's store interface."""

    def __init__(self, db: aiosqlite.Connection):
        self._db = db

    @classmethod
    @asynccontextmanager
    async def from_conn_string(cls, path: str):
        """Async context manager that opens a SQLite database."""
        db = await aiosqlite.connect(path)
        store = cls(db)
        await store.setup()
        try:
            yield store
        finally:
            await db.close()

    async def setup(self) -> None:
        """Create the store table if it doesn't exist."""
        await self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS store (
                namespace TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (namespace, key)
            )
            """
        )
        await self._db.commit()

    async def aput(self, namespace: tuple[str, ...], key: str, value: dict) -> None:
        """Upsert an item."""
        ns_str = "|".join(namespace)
        now = datetime.now(timezone.utc).isoformat()
        await self._db.execute(
            """
            INSERT INTO store (namespace, key, value, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(namespace, key) DO UPDATE SET value = ?, created_at = ?
            """,
            (ns_str, key, json.dumps(value), now, json.dumps(value), now),
        )
        await self._db.commit()

    async def aget(self, namespace: tuple[str, ...], key: str) -> Item | None:
        """Get a single item."""
        ns_str = "|".join(namespace)
        cursor = await self._db.execute(
            "SELECT namespace, key, value, created_at FROM store WHERE namespace = ? AND key = ?",
            (ns_str, key),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return Item(
            namespace=tuple(row[0].split("|")),
            key=row[1],
            value=json.loads(row[2]),
            created_at=datetime.fromisoformat(row[3]),
        )

    async def asearch(
        self,
        namespace: tuple[str, ...],
        *,
        query: str | None = None,
        limit: int = 10,
    ) -> list[Item]:
        """List items in a namespace. Query parameter is ignored (no embeddings)."""
        ns_str = "|".join(namespace)
        cursor = await self._db.execute(
            "SELECT namespace, key, value, created_at FROM store WHERE namespace = ? ORDER BY created_at DESC LIMIT ?",
            (ns_str, limit),
        )
        rows = await cursor.fetchall()
        return [
            Item(
                namespace=tuple(row[0].split("|")),
                key=row[1],
                value=json.loads(row[2]),
                created_at=datetime.fromisoformat(row[3]),
            )
            for row in rows
        ]

    async def adelete(self, namespace: tuple[str, ...], key: str) -> None:
        """Remove an item."""
        ns_str = "|".join(namespace)
        await self._db.execute(
            "DELETE FROM store WHERE namespace = ? AND key = ?",
            (ns_str, key),
        )
        await self._db.commit()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest packages/python/agentstack/tests/test_sqlite_store.py -v`

Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add packages/python/agentstack/
git commit -m "feat: add AsyncSqliteStore for long-term memory persistence"
```

---

### Task 2: Update Agent Template — Memory Tools and Store

**Files:**
- Modify: `packages/python/agentstack-adapter-langchain/src/agentstack_adapter_langchain/templates.py`

This task updates `generate_agent_py` to:
1. Add store initialization
2. Add `save_memory` and `forget_memory` tools
3. Add memory instructions to the system prompt
4. Pass `store` to `create_agent`

- [ ] **Step 1: Add memory tool generation helper**

Add this function after `_get_session_store` in `templates.py`:

```python
MEMORY_TOOLS_CODE = '''

# Memory tools
@tool
def save_memory(content: str, scope: str = "user") -> str:
    """Save a fact or preference to long-term memory.

    Args:
        content: The information to remember
        scope: Where to store — "user" (personal), "project" (team), or "global" (everyone)
    """
    return f"__SAVE_MEMORY__|{scope}|{content}"


@tool
def forget_memory(memory_id: str) -> str:
    """Forget a specific memory by its ID (shown in recalled memories).

    Args:
        memory_id: The ID of the memory to remove
    """
    return f"__FORGET_MEMORY__|{memory_id}"
'''

MEMORY_SYSTEM_PROMPT = """
## Memory
You have long-term memory that persists across conversations.
At the start of each conversation, relevant memories are provided in context.
Use save_memory to remember important facts, preferences, or instructions the user shares.
Use forget_memory to remove incorrect or outdated memories when asked.
"""
```

- [ ] **Step 2: Update `_collect_system_prompt` to include memory instructions**

Replace `_collect_system_prompt` in `templates.py`:

```python
def _collect_system_prompt(agent: Agent) -> str:
    """Collect system prompt from agent instructions, skill prompts, and memory instructions."""
    prompts = []
    if agent.instructions:
        prompts.append(agent.instructions)
    for skill in agent.skills:
        if skill.prompt:
            prompts.append(skill.prompt)
    # Add memory instructions if resources are present (memory is enabled)
    session_store = _get_session_store(agent)
    if session_store:
        prompts.append(MEMORY_SYSTEM_PROMPT)
    return "\n\n".join(prompts)
```

- [ ] **Step 3: Update `generate_agent_py` — add store imports and initialization**

In `generate_agent_py`, after the checkpointer import section (around line 114), add store imports:

After `lines.append("from langgraph.prebuilt import create_react_agent")`, add:

```python
    # Store for long-term memory
    if session_store and session_store.engine == "postgres":
        lines.append("from langgraph.store.postgres.aio import AsyncPostgresStore")
    elif session_store and session_store.engine == "sqlite":
        lines.append("from agentstack.stores.sqlite import AsyncSqliteStore")
    else:
        # No store for in-memory mode
        pass
```

After the checkpointer setup section (memory = ...), add store setup:

```python
    if session_store and session_store.engine in ("postgres", "sqlite"):
        lines.append("")
        lines.append("# Long-term memory store — initialized at startup via lifespan")
        lines.append("store = None  # set during server lifespan")
```

- [ ] **Step 4: Add memory tools to generated code**

After the tool stubs section and before `# Agent`, if a session store is present, add the memory tools:

```python
    if session_store:
        lines.append("")
        lines.append(MEMORY_TOOLS_CODE)
```

Also add `save_memory` and `forget_memory` to the tools list:

```python
    # Add memory tools to the tools list if store is present
    if session_store:
        if tools_list:
            tools_list += ", save_memory, forget_memory"
        else:
            tools_list = "save_memory, forget_memory"
```

- [ ] **Step 5: Update `create_agent` function to accept store**

Change the `create_agent` function signature and call:

For persistent checkpointers:
```python
    if session_store and session_store.engine in ("postgres", "sqlite"):
        if system_prompt:
            lines.append(f"def create_agent(checkpointer, store=None):")
            lines.append(f"    return create_react_agent(model, [{tools_list}], checkpointer=checkpointer, store=store, prompt=system_prompt)")
        else:
            lines.append(f"def create_agent(checkpointer, store=None):")
            lines.append(f"    return create_react_agent(model, [{tools_list}], checkpointer=checkpointer, store=store)")
```

For in-memory:
```python
    else:
        if system_prompt:
            lines.append(
                f"agent = create_react_agent(model, [{tools_list}], checkpointer=memory, prompt=system_prompt)"
            )
        else:
            lines.append(f"agent = create_react_agent(model, [{tools_list}], checkpointer=memory)")
```

- [ ] **Step 6: Run tests**

Run: `uv run pytest packages/python/agentstack-adapter-langchain/tests/ -v`

Fix any failures (existing tests may need updates due to memory tools being added to agents with resources).

- [ ] **Step 7: Commit**

```bash
git add packages/python/agentstack-adapter-langchain/
git commit -m "feat: generate memory tools and store initialization in agent template"
```

---

### Task 3: Update Server Template — Memory Recall and User Identity

**Files:**
- Modify: `packages/python/agentstack-adapter-langchain/src/agentstack_adapter_langchain/templates.py`

This task updates `generate_server_py` to:
1. Add `user_id` and `project_id` to the request model
2. Initialize store in the lifespan
3. Recall memories before each request
4. Handle `save_memory` and `forget_memory` tool outputs after agent response

- [ ] **Step 1: Update request model in server template**

In `generate_server_py`, update the `InvokeRequest` class lines:

```python
    lines.append("class InvokeRequest(BaseModel):")
    lines.append("    message: str")
    lines.append("    session_id: str | None = None")
    lines.append("    user_id: str | None = None")
    lines.append("    project_id: str | None = None")
```

- [ ] **Step 2: Update lifespan to initialize store**

For persistent mode, update the lifespan block. Replace the current lifespan with:

For Postgres:
```python
        lines.append("@asynccontextmanager")
        lines.append("async def lifespan(app):")
        lines.append("    global _agent, _store")
        lines.append(f"    async with {saver_class}.from_conn_string(DB_URI) as checkpointer, \\")
        lines.append(f"             AsyncPostgresStore.from_conn_string(DB_URI) as store:")
        lines.append("        await checkpointer.setup()")
        lines.append("        await store.setup()")
        lines.append("        _store = store")
        lines.append("        _agent = create_agent(checkpointer, store)")
        lines.append("        yield")
```

For SQLite, use AsyncSqliteStore with a separate db file for the store:
```python
        lines.append("@asynccontextmanager")
        lines.append("async def lifespan(app):")
        lines.append("    global _agent, _store")
        lines.append(f"    async with {saver_class}.from_conn_string(DB_URI) as checkpointer, \\")
        lines.append(f"             AsyncSqliteStore.from_conn_string(DB_URI.replace('.db', '_store.db')) as store:")
        lines.append("        await checkpointer.setup()")
        lines.append("        await store.setup()")
        lines.append("        _store = store")
        lines.append("        _agent = create_agent(checkpointer, store)")
        lines.append("        yield")
```

Add `_store = None` alongside `_agent = None` at module level.

Update imports for the persistent case to also import the store class:
```python
    if uses_persistent:
        lines.append("from contextlib import asynccontextmanager")
        lines.append(f"from langgraph.checkpoint.{saver_module} import {saver_class}")
        if session_store.engine == "postgres":
            lines.append("from langgraph.store.postgres.aio import AsyncPostgresStore")
        elif session_store.engine == "sqlite":
            lines.append("from agentstack.stores.sqlite import AsyncSqliteStore")
```

- [ ] **Step 3: Add memory recall helper function in server**

After the lifespan block and before the routes, add a recall function:

```python
    if uses_persistent:
        lines.append("")
        lines.append("")
        lines.append("async def recall_memories(store, message, user_id=None, project_id=None):")
        lines.append('    """Search memories across applicable scopes."""')
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
```

- [ ] **Step 4: Add memory action handler in server**

```python
    if uses_persistent:
        lines.append("")
        lines.append("")
        lines.append("async def handle_memory_actions(store, messages, user_id=None, project_id=None):")
        lines.append('    """Process save_memory and forget_memory tool calls from agent response."""')
        lines.append("    import uuid as _uuid")
        lines.append("    for msg in messages:")
        lines.append("        if hasattr(msg, 'content') and isinstance(msg.content, str):")
        lines.append('            if msg.content.startswith("__SAVE_MEMORY__|"):")')
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
        lines.append("                # Try all scopes")
        lines.append("                if user_id:")
        lines.append('                    await store.adelete(("user", user_id, "memories"), memory_id)')
        lines.append("                if project_id:")
        lines.append('                    await store.adelete(("project", project_id, "memories"), memory_id)')
        lines.append('                await store.adelete(("global", "memories"), memory_id)')
```

- [ ] **Step 5: Update invoke endpoint to use memory**

Update the invoke handler to recall memories and handle memory actions:

```python
    lines.append('@app.post("/invoke", response_model=InvokeResponse)')
    lines.append("async def invoke(request: InvokeRequest):")
    lines.append("    session_id = request.session_id or str(uuid.uuid4())")
    if uses_persistent:
        lines.append("    user_id = request.user_id")
        lines.append("    project_id = request.project_id")
        lines.append("")
        lines.append("    # Recall relevant memories")
        lines.append("    recalled = await recall_memories(_store, request.message, user_id, project_id)")
        lines.append("    memory_context = ''")
        lines.append("    if recalled:")
        lines.append("""        memory_context = '\\n## Recalled Memories\\n' + '\\n'.join(f'- {m}' for m in recalled) + '\\n'""")
        lines.append("")
        lines.append("    messages = []")
        lines.append("    if memory_context:")
        lines.append('        messages.append(("system", memory_context))')
        lines.append('    messages.append(("user", request.message))')
        lines.append("")
        lines.append(f"    result = await {agent_ref}.ainvoke(")
        lines.append('        {"messages": messages},')
        lines.append('        config={"configurable": {"thread_id": session_id}},')
        lines.append("    )")
        lines.append("")
        lines.append("    # Handle memory save/forget actions")
        lines.append('    await handle_memory_actions(_store, result["messages"], user_id, project_id)')
    else:
        lines.append(f"    result = await {agent_ref}.ainvoke(")
        lines.append('        {"messages": [("user", request.message)]},')
        lines.append('        config={"configurable": {"thread_id": session_id}},')
        lines.append("    )")
    lines.append('    content = result["messages"][-1].content')
    # ... rest of response parsing unchanged
```

- [ ] **Step 6: Update requirements**

In `generate_requirements_txt`, add `aiosqlite>=0.20` for SQLite store and `agentstack` for the store import:

```python
    if session_store and session_store.engine == "sqlite":
        checkpoint_pkg = "\nlanggraph-checkpoint-sqlite>=2.0\naiosqlite>=0.20"
```

- [ ] **Step 7: Run tests**

Run: `uv run pytest packages/python/agentstack-adapter-langchain/tests/ -v`

Fix any failures.

- [ ] **Step 8: Commit**

```bash
git add packages/python/agentstack-adapter-langchain/
git commit -m "feat: add memory recall and user identity to server template"
```

---

### Task 4: Update Template Tests

**Files:**
- Modify: `packages/python/agentstack-adapter-langchain/tests/test_templates.py`

- [ ] **Step 1: Add memory-related test fixtures and tests**

Append to `test_templates.py`:

```python
class TestMemoryGeneration:
    def test_memory_tools_generated_with_resource(self, postgres_agent):
        code = generate_agent_py(postgres_agent)
        assert "save_memory" in code
        assert "forget_memory" in code
        assert "__SAVE_MEMORY__" in code

    def test_no_memory_tools_without_resource(self, openai_agent):
        code = generate_agent_py(openai_agent)
        assert "save_memory" not in code
        assert "forget_memory" not in code

    def test_memory_system_prompt_with_resource(self, postgres_agent):
        code = generate_agent_py(postgres_agent)
        assert "long-term memory" in code.lower()

    def test_no_memory_prompt_without_resource(self, openai_agent):
        code = generate_agent_py(openai_agent)
        assert "long-term memory" not in code.lower()

    def test_postgres_store_import(self, postgres_agent):
        code = generate_agent_py(postgres_agent)
        assert "AsyncPostgresStore" in code

    def test_sqlite_store_import(self, sqlite_agent):
        code = generate_agent_py(sqlite_agent)
        assert "AsyncSqliteStore" in code

    def test_create_agent_accepts_store(self, postgres_agent):
        code = generate_agent_py(postgres_agent)
        assert "def create_agent(checkpointer, store=None)" in code
        assert "store=store" in code

    def test_agent_py_with_memory_parseable(self, postgres_agent):
        code = generate_agent_py(postgres_agent)
        python_ast.parse(code)

    def test_agent_py_sqlite_with_memory_parseable(self, sqlite_agent):
        code = generate_agent_py(sqlite_agent)
        python_ast.parse(code)


class TestServerMemory:
    def test_server_accepts_user_id(self, postgres_agent):
        code = generate_server_py(postgres_agent)
        assert "user_id" in code

    def test_server_accepts_project_id(self, postgres_agent):
        code = generate_server_py(postgres_agent)
        assert "project_id" in code

    def test_server_recall_memories(self, postgres_agent):
        code = generate_server_py(postgres_agent)
        assert "recall_memories" in code

    def test_server_handle_memory_actions(self, postgres_agent):
        code = generate_server_py(postgres_agent)
        assert "handle_memory_actions" in code

    def test_server_no_memory_without_resource(self, openai_agent):
        code = generate_server_py(openai_agent)
        assert "recall_memories" not in code
        assert "user_id" not in code

    def test_server_with_memory_parseable(self, postgres_agent):
        code = generate_server_py(postgres_agent)
        python_ast.parse(code)

    def test_server_sqlite_with_memory_parseable(self, sqlite_agent):
        code = generate_server_py(sqlite_agent)
        python_ast.parse(code)

    def test_sqlite_requirements_include_aiosqlite(self, sqlite_agent):
        reqs = generate_requirements_txt(sqlite_agent)
        assert "aiosqlite" in reqs
```

- [ ] **Step 2: Run all tests**

Run: `uv run pytest packages/python/agentstack-adapter-langchain/tests/ -v`

Expected: all tests PASS.

- [ ] **Step 3: Commit**

```bash
git add packages/python/agentstack-adapter-langchain/tests/
git commit -m "test: add memory tools and recall tests for templates"
```

---

### Task 5: Full Verification

- [ ] **Step 1: Run all Python tests**

Run: `just test-python`

Expected: all tests pass.

- [ ] **Step 2: Preview generated code with memory**

Run: `uv run python examples/hello-agent/preview.py`

Verify:
- `agent.py` includes `save_memory` and `forget_memory` tools
- `agent.py` includes `AsyncSqliteStore` or `AsyncPostgresStore` import
- `agent.py` includes memory instructions in system prompt
- `server.py` includes `user_id` and `project_id` in request model
- `server.py` includes `recall_memories` function
- `server.py` lifespan initializes both checkpointer and store
- Both files parse with `ast.parse()`

- [ ] **Step 3: Run linting**

Run: `uv run ruff check packages/python/agentstack/src/agentstack/stores/ packages/python/agentstack-adapter-langchain/`

Fix any lint errors.
