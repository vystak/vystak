"""Code generation templates for LangChain/LangGraph agents."""

from textwrap import dedent

from agentstack.schema.agent import Agent
from agentstack_adapter_langchain.a2a import (
    generate_a2a_handler_code,
    generate_agent_card_code,
    generate_task_manager_code,
)

# Provider type -> (import statement, class name)
MODEL_PROVIDERS = {
    "anthropic": (
        "from langchain_anthropic import ChatAnthropic",
        "ChatAnthropic",
    ),
    "openai": (
        "from langchain_openai import ChatOpenAI",
        "ChatOpenAI",
    ),
}

# Provider type -> pip package
PROVIDER_PACKAGES = {
    "anthropic": "langchain-anthropic>=0.3",
    "openai": "langchain-openai>=0.3",
}

MEMORY_TOOLS_CODE = '''
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


def _collect_system_prompt(agent: Agent) -> str:
    """Collect system prompt from agent instructions, skill prompts, and memory instructions."""
    prompts = []
    if agent.instructions:
        prompts.append(agent.instructions)
    for skill in agent.skills:
        if skill.prompt:
            prompts.append(skill.prompt)
    session_store = _get_session_store(agent)
    if session_store:
        prompts.append(MEMORY_SYSTEM_PROMPT)
    return "\n\n".join(prompts)


def _get_session_store(agent: Agent):
    """Find a SessionStore resource in the agent, if any."""
    from agentstack.schema.resource import SessionStore
    for resource in agent.resources:
        if isinstance(resource, SessionStore):
            return resource
        # YAML-loaded resources are base Resource — match by engine
        if resource.engine in ("postgres", "sqlite", "redis"):
            return resource
    return None


def generate_agent_py(agent: Agent, found_tool_names: list[str] | None = None, stub_tool_names: list[str] | None = None) -> str:
    """Generate a LangGraph agent definition file."""
    provider_type = agent.model.provider.type
    model_import, model_class = MODEL_PROVIDERS.get(
        provider_type, MODEL_PROVIDERS["anthropic"]
    )

    # Build model kwargs
    model_kwargs = [f'model="{agent.model.model_name}"']

    for key, value in agent.model.parameters.items():
        if isinstance(value, str):
            model_kwargs.append(f'{key}="{value}"')
        else:
            model_kwargs.append(f"{key}={value}")
    model_kwargs_str = ", ".join(model_kwargs)

    # Tool handling
    if found_tool_names is None and stub_tool_names is None:
        # Legacy: extract all tools from skills, treat as stubs
        seen = set()
        stub_tool_names = []
        for skill in agent.skills:
            for tool_name in skill.tools:
                if tool_name not in seen:
                    seen.add(tool_name)
                    stub_tool_names.append(tool_name)
        found_tool_names = []

    if found_tool_names is None:
        found_tool_names = []
    if stub_tool_names is None:
        stub_tool_names = []

    tool_stubs = _generate_tool_stubs(stub_tool_names)
    all_tool_names = found_tool_names + stub_tool_names
    tools_list = ", ".join(all_tool_names) if all_tool_names else ""

    # System prompt
    system_prompt = _collect_system_prompt(agent)

    # Checkpointer based on resources
    session_store = _get_session_store(agent)

    # Build the agent code
    lines = []
    lines.append(f'"""AgentStack generated agent: {agent.name}."""\n')
    lines.append(f"{model_import}")

    # Import tool decorator if needed (stub tools or memory tools)
    if stub_tool_names or session_store:
        lines.append("from langchain_core.tools import tool")

    if session_store and session_store.engine == "postgres":
        lines.append("import os")
        lines.append("")
        lines.append("from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver")
        lines.append("from langgraph.store.postgres.aio import AsyncPostgresStore")
    elif session_store and session_store.engine == "sqlite":
        lines.append("from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver")
        lines.append("from store import AsyncSqliteStore")
    else:
        lines.append("from langgraph.checkpoint.memory import MemorySaver")

    lines.append("from langgraph.prebuilt import create_react_agent")
    lines.append("")
    lines.append("")
    lines.append(f"# Model")
    lines.append(f"model = {model_class}({model_kwargs_str})")
    lines.append("")

    if session_store and session_store.engine == "postgres":
        lines.append("# Session persistence (Postgres) — initialized at startup via lifespan")
        lines.append('DB_URI = os.environ["SESSION_STORE_URL"]')
        lines.append("memory = None  # set during server lifespan")
        lines.append("")
        lines.append("# Long-term memory store — initialized at startup via lifespan")
        lines.append("store = None  # set during server lifespan")
    elif session_store and session_store.engine == "sqlite":
        lines.append("# Session persistence (SQLite) — initialized at startup via lifespan")
        lines.append(f'DB_URI = "/data/{session_store.name}.db"')
        lines.append("memory = None  # set during server lifespan")
        lines.append("")
        lines.append("# Long-term memory store — initialized at startup via lifespan")
        lines.append("store = None  # set during server lifespan")
    else:
        lines.append("# Session memory (in-memory, not persisted)")
        lines.append("memory = MemorySaver()")

    lines.append("")

    # Import real tools from tools/ package
    if found_tool_names:
        lines.append("")
        lines.append("# Tools (loaded from tools/ directory)")
        imports = ", ".join(found_tool_names)
        lines.append(f"from tools import {imports}")

    if tool_stubs:
        lines.append("")
        lines.append("# Tool stubs (no implementation found)")
        lines.append(tool_stubs)

    if session_store:
        lines.append(MEMORY_TOOLS_CODE)

    lines.append("")
    lines.append("# Agent")

    if system_prompt:
        escaped_prompt = system_prompt.replace('"""', '\\"\\"\\"')
        lines.append(f'system_prompt = """{escaped_prompt}"""')
        lines.append("")

    # Build tools list including memory tools if session_store is present
    if session_store:
        memory_tools = "save_memory, forget_memory"
        if tools_list:
            full_tools_list = f"{tools_list}, {memory_tools}"
        else:
            full_tools_list = memory_tools
    else:
        full_tools_list = tools_list

    # For persistent checkpointers, create agent via function (memory set at startup)
    if session_store and session_store.engine in ("postgres", "sqlite"):
        if system_prompt:
            lines.append(f"def create_agent(checkpointer, store=None):")
            lines.append(f"    return create_react_agent(model, [{full_tools_list}], checkpointer=checkpointer, store=store, prompt=system_prompt)")
        else:
            lines.append(f"def create_agent(checkpointer, store=None):")
            lines.append(f"    return create_react_agent(model, [{full_tools_list}], checkpointer=checkpointer, store=store)")
        lines.append("")
        lines.append("agent = None  # created during server lifespan")
    else:
        if system_prompt:
            lines.append(
                f"agent = create_react_agent(model, [{full_tools_list}], checkpointer=memory, prompt=system_prompt)"
            )
        else:
            lines.append(f"agent = create_react_agent(model, [{full_tools_list}], checkpointer=memory)")

    lines.append("")

    return "\n".join(lines)


def generate_server_py(agent: Agent) -> str:
    """Generate a FastAPI harness server file."""
    session_store = _get_session_store(agent)
    uses_persistent = session_store and session_store.engine in ("postgres", "sqlite")

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
        agent_ref = "agent"

    lines = []
    lines.append(f'"""AgentStack harness server for {agent.name}."""')
    lines.append("")
    lines.append("import json")
    lines.append("import os")
    lines.append("import uuid")
    lines.append("")
    lines.append("from fastapi import FastAPI, Request")
    lines.append("from pydantic import BaseModel")
    lines.append("from sse_starlette.sse import EventSourceResponse")
    lines.append("")

    if uses_persistent:
        lines.append("from contextlib import asynccontextmanager")
        lines.append(f"from langgraph.checkpoint.{saver_module} import {saver_class}")
        lines.append(store_import)
        lines.append("")
        lines.append("from agent import create_agent, DB_URI")
        lines.append("")
        lines.append("")
        lines.append("_agent = None")
        lines.append("_store = None")
        lines.append("")
        lines.append("")
        lines.append("@asynccontextmanager")
        lines.append("async def lifespan(app):")
        lines.append("    global _agent, _store")
        if session_store.engine == "postgres":
            lines.append(f"    async with {saver_class}.from_conn_string(DB_URI) as checkpointer, \\")
            lines.append(f"               {store_class}.from_conn_string(DB_URI) as store:")
        else:
            lines.append(f"    async with {saver_class}.from_conn_string(DB_URI) as checkpointer, \\")
            lines.append(f"               {store_class}.from_conn_string(DB_URI.replace('.db', '_store.db')) as store:")
        lines.append("        await checkpointer.setup()")
        lines.append("        _store = store")
        lines.append("        _agent = create_agent(checkpointer, store=store)")
        lines.append("        yield")
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
    lines.append('HOST = os.environ.get("HOST", "0.0.0.0")')
    lines.append('PORT = int(os.environ.get("PORT", "8000"))')
    lines.append("")
    lines.append("")
    lines.append("class InvokeRequest(BaseModel):")
    lines.append("    message: str")
    lines.append("    session_id: str | None = None")
    if uses_persistent:
        lines.append("    user_id: str | None = None")
        lines.append("    project_id: str | None = None")
    lines.append("")
    lines.append("")
    lines.append("class UsageInfo(BaseModel):")
    lines.append("    input_tokens: int = 0")
    lines.append("    output_tokens: int = 0")
    lines.append("    total_tokens: int = 0")
    lines.append("")
    lines.append("")
    lines.append("class InvokeResponse(BaseModel):")
    lines.append("    response: str")
    lines.append("    session_id: str")
    lines.append("    usage: UsageInfo | None = None")
    lines.append("")
    lines.append("")

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

    lines.append('@app.get("/health")')
    lines.append("async def health():")
    lines.append('    return {"status": "ok", "agent": AGENT_NAME, "version": "0.1.0"}')
    lines.append("")
    lines.append("")
    lines.append('@app.post("/invoke", response_model=InvokeResponse)')
    lines.append("async def invoke(request: InvokeRequest):")
    lines.append("    session_id = request.session_id or str(uuid.uuid4())")

    if uses_persistent:
        lines.append("    user_id = request.user_id")
        lines.append("    project_id = request.project_id")
        lines.append("    memories = await recall_memories(_store, request.message, user_id=user_id, project_id=project_id)")
        lines.append("    messages = []")
        lines.append("    if memories:")
        lines.append('        memory_text = "Relevant memories:\\n" + "\\n".join(memories)')
        lines.append('        messages.append(("system", memory_text))')
        lines.append('    messages.append(("user", request.message))')
        lines.append(f"    result = await {agent_ref}.ainvoke(")
        lines.append('        {"messages": messages},')
        lines.append('        config={"configurable": {"thread_id": session_id}},')
        lines.append("    )")
        lines.append('    content = result["messages"][-1].content')
        lines.append("    if isinstance(content, list):")
        lines.append("        response_text = ''.join(")
        lines.append('            block.get("text", "") if isinstance(block, dict) else str(block)')
        lines.append("            for block in content")
        lines.append("        )")
        lines.append("    else:")
        lines.append("        response_text = str(content)")
        lines.append("    await handle_memory_actions(_store, result['messages'], user_id=user_id, project_id=project_id)")
        lines.append("    last_msg = result['messages'][-1]")
        lines.append("    usage = None")
        lines.append("    if hasattr(last_msg, 'usage_metadata') and last_msg.usage_metadata:")
        lines.append("        um = last_msg.usage_metadata")
        lines.append("        usage = UsageInfo(")
        lines.append("            input_tokens=um.get('input_tokens', 0),")
        lines.append("            output_tokens=um.get('output_tokens', 0),")
        lines.append("            total_tokens=um.get('total_tokens', 0),")
        lines.append("        )")
        lines.append("    return InvokeResponse(response=response_text, session_id=session_id, usage=usage)")
    else:
        lines.append(f"    result = await {agent_ref}.ainvoke(")
        lines.append('        {"messages": [("user", request.message)]},')
        lines.append('        config={"configurable": {"thread_id": session_id}},')
        lines.append("    )")
        lines.append('    content = result["messages"][-1].content')
        lines.append("    if isinstance(content, list):")
        lines.append("        response_text = ''.join(")
        lines.append('            block.get("text", "") if isinstance(block, dict) else str(block)')
        lines.append("            for block in content")
        lines.append("        )")
        lines.append("    else:")
        lines.append("        response_text = str(content)")
        lines.append("    last_msg = result['messages'][-1]")
        lines.append("    usage = None")
        lines.append("    if hasattr(last_msg, 'usage_metadata') and last_msg.usage_metadata:")
        lines.append("        um = last_msg.usage_metadata")
        lines.append("        usage = UsageInfo(")
        lines.append("            input_tokens=um.get('input_tokens', 0),")
        lines.append("            output_tokens=um.get('output_tokens', 0),")
        lines.append("            total_tokens=um.get('total_tokens', 0),")
        lines.append("        )")
        lines.append("    return InvokeResponse(response=response_text, session_id=session_id, usage=usage)")

    lines.append("")
    lines.append("")
    lines.append('@app.post("/stream")')
    lines.append("async def stream(request: InvokeRequest):")
    lines.append("    session_id = request.session_id or str(uuid.uuid4())")
    lines.append("")
    lines.append("    async def event_generator():")
    lines.append("        usage = {}")
    lines.append(f"        async for event in {agent_ref}.astream_events(")
    lines.append('            {"messages": [("user", request.message)]},')
    lines.append('            config={"configurable": {"thread_id": session_id}},')
    lines.append('            version="v2",')
    lines.append("        ):")
    lines.append('            if event["event"] == "on_chat_model_stream":')
    lines.append('                token = event["data"]["chunk"].content')
    lines.append("                if token:")
    lines.append('                    yield {"data": json.dumps({"token": token, "session_id": session_id})}')
    lines.append('            elif event["event"] == "on_chat_model_end":')
    lines.append('                msg = event["data"].get("output")')
    lines.append("                if msg and hasattr(msg, 'usage_metadata') and msg.usage_metadata:")
    lines.append("                    um = msg.usage_metadata")
    lines.append('                    usage = {"input_tokens": um.get("input_tokens", 0), "output_tokens": um.get("output_tokens", 0), "total_tokens": um.get("total_tokens", 0)}')
    lines.append('        yield {"data": json.dumps({"done": True, "session_id": session_id, "usage": usage})}')
    lines.append("")
    lines.append("    return EventSourceResponse(event_generator())")
    lines.append("")
    lines.append("")

    # A2A Protocol
    lines.append(generate_task_manager_code())
    lines.append(generate_agent_card_code(agent))
    lines.append(generate_a2a_handler_code(agent))

    lines.append('if __name__ == "__main__":')
    lines.append("    import uvicorn")
    lines.append("")
    lines.append("    uvicorn.run(app, host=HOST, port=PORT)")
    lines.append("")

    return "\n".join(lines)


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


def generate_store_py() -> str:
    """Generate the AsyncSqliteStore module for bundling with SQLite deployments."""
    return '''\
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
    """Async SQLite-backed store compatible with LangGraph\'s store interface."""

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
        """Create the store table if it doesn\'t exist."""
        await self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS store (
                namespace TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime(\'now\')),
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

    async def aget(self, namespace: tuple[str, ...], key: str):
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
    ) -> list:
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
'''
