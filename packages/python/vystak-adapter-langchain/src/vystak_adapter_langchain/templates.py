"""Code generation templates for LangChain/LangGraph agents."""

from textwrap import dedent

from vystak.schema.agent import Agent

from vystak_adapter_langchain.a2a import (
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
    """Find the session store for the agent.

    Prefers agent.sessions (new API), falls back to agent.resources (deprecated).
    """
    if agent.sessions is not None:
        return agent.sessions

    from vystak.schema.resource import SessionStore

    for resource in agent.resources:
        if isinstance(resource, SessionStore):
            return resource
        if resource.engine in ("postgres", "sqlite", "redis"):
            return resource
    return None


def _has_mcp_servers(agent: Agent) -> bool:
    """Check if the agent has MCP servers configured."""
    return bool(agent.mcp_servers)


def _generate_mcp_config(agent: Agent) -> str:
    """Generate MCP_SERVERS dict for MultiServerMCPClient."""
    if not agent.mcp_servers:
        return ""

    lines = []
    lines.append("")
    lines.append("# MCP Server connections")
    lines.append("MCP_SERVERS = {")

    for mcp in agent.mcp_servers:
        lines.append(f'    "{mcp.name}": {{')
        transport_map = {"stdio": "stdio", "sse": "sse", "streamable_http": "http"}
        transport = transport_map.get(mcp.transport.value, mcp.transport.value)
        lines.append(f'        "transport": "{transport}",')
        if mcp.command:
            # Split command string into executable + args for langchain_mcp_adapters
            parts = mcp.command.split()
            lines.append(f'        "command": "{parts[0]}",')
            # Merge explicit args after any args parsed from command string
            all_args = parts[1:] + list(mcp.args or [])
            if all_args:
                args_str = ", ".join(f'"{a}"' for a in all_args)
                lines.append(f'        "args": [{args_str}],')
        elif mcp.args:
            args_str = ", ".join(f'"{a}"' for a in mcp.args)
            lines.append(f'        "args": [{args_str}],')
        if mcp.url:
            lines.append(f'        "url": "{mcp.url}",')
        if mcp.env:
            lines.append('        "env": {')
            for k, v in mcp.env.items():
                lines.append(f'            "{k}": "{v}",')
            lines.append("        },")
        if mcp.headers:
            lines.append('        "headers": {')
            for k, v in mcp.headers.items():
                lines.append(f'            "{k}": "{v}",')
            lines.append("        },")
        lines.append("    },")

    lines.append("}")
    lines.append("")
    return "\n".join(lines)


def generate_agent_py(
    agent: Agent,
    found_tool_names: list[str] | None = None,
    stub_tool_names: list[str] | None = None,
) -> str:
    """Generate a LangGraph agent definition file."""
    has_mcp = _has_mcp_servers(agent)
    provider_type = agent.model.provider.type
    model_import, model_class = MODEL_PROVIDERS.get(provider_type, MODEL_PROVIDERS["anthropic"])

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
    lines.append(f'"""Vystak generated agent: {agent.name}."""\n')
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
    if has_mcp:
        lines.append("from langchain_mcp_adapters.client import MultiServerMCPClient")
        lines.append(_generate_mcp_config(agent))
    lines.append("")
    lines.append("")
    lines.append("# Model")
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
        full_tools_list = f"{tools_list}, {memory_tools}" if tools_list else memory_tools
    else:
        full_tools_list = tools_list

    # For persistent checkpointers, create agent via function (memory set at startup)
    # Use a prompt callable so memory recall is ephemeral (never saved to checkpoint state)
    if session_store and session_store.engine in ("postgres", "sqlite"):
        lines.append("")
        lines.append("def _make_prompt(base_prompt, mem_store):")
        lines.append(
            '    """Create a prompt callable that injects recalled memories ephemerally."""'
        )
        lines.append("    async def prompt(state, config):")
        lines.append("        user_id = config.get('configurable', {}).get('user_id')")
        lines.append("        project_id = config.get('configurable', {}).get('project_id')")
        lines.append("        last_msg = ''")
        lines.append("        for m in reversed(state.get('messages', [])):")
        lines.append(
            "            if hasattr(m, 'content') and isinstance(m.content, str) and getattr(m, 'type', '') == 'human':"
        )
        lines.append("                last_msg = m.content")
        lines.append("                break")
        lines.append("        memories = []")
        lines.append("        if mem_store and last_msg:")
        lines.append("            if user_id:")
        lines.append(
            '                results = await mem_store.asearch(("user", user_id, "memories"), query=last_msg, limit=5)'
        )
        lines.append("                for item in results:")
        lines.append(
            '                    memories.append(f\'[{item.key}] {item.value.get("data", "")} (scope: user)\')'
        )
        lines.append("            if project_id:")
        lines.append(
            '                results = await mem_store.asearch(("project", project_id, "memories"), query=last_msg, limit=5)'
        )
        lines.append("                for item in results:")
        lines.append(
            '                    memories.append(f\'[{item.key}] {item.value.get("data", "")} (scope: project)\')'
        )
        lines.append(
            '            results = await mem_store.asearch(("global", "memories"), query=last_msg, limit=5)'
        )
        lines.append("            for item in results:")
        lines.append(
            '                memories.append(f\'[{item.key}] {item.value.get("data", "")} (scope: global)\')'
        )
        lines.append("        parts = []")
        lines.append("        if base_prompt:")
        lines.append("            parts.append(base_prompt)")
        lines.append("        if memories:")
        lines.append('            parts.append("Relevant memories:\\n" + "\\n".join(memories))')
        lines.append(
            '        system_content = "\\n\\n".join(parts) if parts else "You are a helpful assistant."'
        )
        lines.append(
            '        return [{"role": "system", "content": system_content}] + state["messages"]'
        )
        lines.append("    return prompt")
        lines.append("")
        lines.append("")
        lines.append("def create_agent(checkpointer, store=None, mcp_tools=None):")
        lines.append(f"    all_tools = [{full_tools_list}]")
        lines.append("    if mcp_tools:")
        lines.append("        all_tools.extend(mcp_tools)")
        if system_prompt:
            lines.append("    prompt_fn = _make_prompt(system_prompt, store)")
        else:
            lines.append("    prompt_fn = _make_prompt(None, store)")
        lines.append(
            "    return create_react_agent(model, all_tools, checkpointer=checkpointer, store=store, prompt=prompt_fn)"
        )
        lines.append("")
        lines.append("agent = None  # created during server lifespan")
    elif has_mcp:
        lines.append("def create_agent(mcp_tools=None):")
        lines.append(f"    all_tools = [{full_tools_list}]")
        lines.append("    if mcp_tools:")
        lines.append("        all_tools.extend(mcp_tools)")
        if system_prompt:
            lines.append(
                "    return create_react_agent(model, all_tools, checkpointer=memory, prompt=system_prompt)"
            )
        else:
            lines.append("    return create_react_agent(model, all_tools, checkpointer=memory)")
        lines.append("")
        lines.append("agent = None  # created during server lifespan")
    else:
        if system_prompt:
            lines.append(
                f"agent = create_react_agent(model, [{full_tools_list}], checkpointer=memory, prompt=system_prompt)"
            )
        else:
            lines.append(
                f"agent = create_react_agent(model, [{full_tools_list}], checkpointer=memory)"
            )

    lines.append("")

    return "\n".join(lines)


def generate_server_py(agent: Agent) -> str:
    """Generate a FastAPI harness server file."""
    session_store = _get_session_store(agent)
    uses_persistent = session_store and session_store.engine in ("postgres", "sqlite")
    has_mcp = _has_mcp_servers(agent)

    if uses_persistent:
        saver_class = (
            "AsyncPostgresSaver" if session_store.engine == "postgres" else "AsyncSqliteSaver"
        )
        saver_module = "postgres.aio" if session_store.engine == "postgres" else "sqlite.aio"
        store_class = (
            "AsyncPostgresStore" if session_store.engine == "postgres" else "AsyncSqliteStore"
        )
        if session_store.engine == "postgres":
            store_import = "from langgraph.store.postgres.aio import AsyncPostgresStore"
        else:
            store_import = "from store import AsyncSqliteStore"
        agent_ref = "_agent"
    else:
        agent_ref = "_agent"

    lines = []
    lines.append(f'"""Vystak harness server for {agent.name}."""')
    lines.append("")
    lines.append("import asyncio")
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
    lines.append("")

    if uses_persistent:
        # Case 1: persistent + MCP  or  Case 2: persistent + no MCP
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
                lines.append(
                    f"    async with {saver_class}.from_conn_string(DB_URI) as checkpointer, \\"
                )
                lines.append(f"               {store_class}.from_conn_string(DB_URI) as store:")
            else:
                lines.append(
                    f"    async with {saver_class}.from_conn_string(DB_URI) as checkpointer, \\"
                )
                lines.append(
                    f"               {store_class}.from_conn_string(DB_URI.replace('.db', '_store.db')) as store:"
                )
            lines.append("        await checkpointer.setup()")
            lines.append("        await store.setup()")
            lines.append("        _store = store")
            lines.append(
                "        _agent = create_agent(checkpointer, store=store, mcp_tools=mcp_tools)"
            )
            lines.append("        yield")
        else:
            if session_store.engine == "postgres":
                lines.append("    import asyncio as _asyncio")
                lines.append("    for _attempt in range(30):")
                lines.append("        try:")
                lines.append(
                    f"            async with {saver_class}.from_conn_string(DB_URI) as checkpointer, \\"
                )
                lines.append(
                    f"                       {store_class}.from_conn_string(DB_URI) as store:"
                )
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
                lines.append(
                    f"    async with {saver_class}.from_conn_string(DB_URI) as checkpointer, \\"
                )
                lines.append(
                    f"               {store_class}.from_conn_string(DB_URI.replace('.db', '_store.db')) as store:"
                )
                lines.append("        await checkpointer.setup()")
                lines.append("        await store.setup()")
                lines.append("        _store = store")
                lines.append("        _agent = create_agent(checkpointer, store=store)")
                lines.append("        yield")
        lines.append("")
        lines.append("")
        lines.append(f'app = FastAPI(title="{agent.name}", lifespan=lifespan)')
    elif has_mcp:
        # Case 3: not persistent + MCP — needs new lifespan
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
        # Case 4: not persistent + no MCP — unchanged
        lines.append("from agent import agent")
        lines.append("_agent = agent  # alias for A2A handlers")
        lines.append("")
        lines.append(f'app = FastAPI(title="{agent.name}")')

    lines.append("")
    lines.append(f'AGENT_NAME = os.environ.get("VYSTAK_AGENT_NAME", "{agent.name}")')
    lines.append(f'MODEL_ID = "vystak/{agent.name}"')
    lines.append('HOST = os.environ.get("HOST", "0.0.0.0")')
    lines.append('PORT = int(os.environ.get("PORT", "8000"))')
    lines.append("")
    lines.append("")

    # Memory recall is now handled by the agent's prompt callable (ephemeral, not checkpointed).
    # Only handle_memory_actions remains in the server for processing save/forget tool results.
    if uses_persistent:
        lines.append(
            "async def handle_memory_actions(store, messages, user_id=None, project_id=None):"
        )
        lines.append("    import uuid as _uuid")
        lines.append("    for msg in messages:")
        lines.append("        if hasattr(msg, 'content') and isinstance(msg.content, str):")
        lines.append('            if msg.content.startswith("__SAVE_MEMORY__|"):')
        lines.append('                parts = msg.content.split("|", 2)')
        lines.append("                if len(parts) == 3:")
        lines.append("                    scope, content = parts[1], parts[2]")
        lines.append("                    memory_id = str(_uuid.uuid4())[:8]")
        lines.append('                    if scope == "user" and user_id:')
        lines.append(
            '                        await store.aput(("user", user_id, "memories"), memory_id, {"data": content})'
        )
        lines.append('                    elif scope == "project" and project_id:')
        lines.append(
            '                        await store.aput(("project", project_id, "memories"), memory_id, {"data": content})'
        )
        lines.append('                    elif scope == "global":')
        lines.append(
            '                        await store.aput(("global", "memories"), memory_id, {"data": content})'
        )
        lines.append('            elif msg.content.startswith("__FORGET_MEMORY__|"):')
        lines.append('                memory_id = msg.content.split("|", 1)[1]')
        lines.append("                if user_id:")
        lines.append(
            '                    await store.adelete(("user", user_id, "memories"), memory_id)'
        )
        lines.append("                if project_id:")
        lines.append(
            '                    await store.adelete(("project", project_id, "memories"), memory_id)'
        )
        lines.append('                await store.adelete(("global", "memories"), memory_id)')
        lines.append("")
        lines.append("")

    # === OpenAI Error Handler ===
    lines.append("@app.exception_handler(Exception)")
    lines.append("async def openai_error_handler(request: Request, exc: Exception):")
    lines.append('    if request.url.path.startswith("/v1/"):')
    lines.append("        return JSONResponse(")
    lines.append("            status_code=500,")
    lines.append("            content=ErrorResponse(error=ErrorDetail(")
    lines.append("                message=str(exc),")
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

    # === /v1/chat/completions (stateless) ===
    lines.append('@app.post("/v1/chat/completions")')
    lines.append("async def chat_completions(request: ChatCompletionRequest):")
    lines.append("    user_id = request.user_id")
    lines.append("    project_id = request.project_id")
    lines.append("    # Stateless: random one-shot thread_id")
    lines.append('    config = {"configurable": {')
    lines.append('        "thread_id": str(uuid.uuid4()),')
    lines.append('        "user_id": user_id,')
    lines.append('        "project_id": project_id,')
    lines.append('        "agent_name": AGENT_NAME,')
    lines.append("    }}")
    lines.append("")
    lines.append("    # Convert full messages array to LangGraph format")
    lines.append("    # Memory recall handled by agent's prompt callable (ephemeral)")
    lines.append("    messages = []")
    lines.append("    for msg in request.messages:")
    lines.append("        messages.append((msg.role, msg.content or ''))")
    lines.append("")
    lines.append("    if request.stream:")
    lines.append("        return await _stream_chat_completions(messages, config, request)")
    lines.append("")
    lines.append(f"    result = await {agent_ref}.ainvoke(")
    lines.append('        {"messages": messages},')
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
        lines.append(
            "    await handle_memory_actions(_store, result['messages'], user_id=user_id, project_id=project_id)"
        )
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
    lines.append(
        "        choices=[Choice(message=ChatMessage(role='assistant', content=response_text))],"
    )
    lines.append("        usage=usage,")
    lines.append("    ).model_dump()")
    lines.append("")
    lines.append("")

    # === Chat Completions Streaming helper ===
    lines.append("async def _stream_chat_completions(messages, config, request):")
    lines.append('    completion_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"')
    lines.append("")
    lines.append("    async def event_generator():")
    lines.append("        usage = {}")
    lines.append("        tool_msgs = []")
    lines.append(f"        async for chunk in {agent_ref}.astream(")
    lines.append('            {"messages": messages},')
    lines.append("            config=config,")
    lines.append('            stream_mode=["messages", "custom"],')
    lines.append("        ):")
    lines.append('            if chunk[0] == "custom":')
    lines.append("                oai_chunk = ChatCompletionChunk(")
    lines.append("                    id=completion_id,")
    lines.append("                    created=int(time.time()),")
    lines.append("                    model=MODEL_ID,")
    lines.append("                    choices=[ChunkChoice(delta=ChunkDelta())],")
    lines.append("                    x_vystak=chunk[1],")
    lines.append("                ).model_dump()")
    lines.append('                yield {"data": json.dumps(oai_chunk)}')
    lines.append('            elif chunk[0] == "messages":')
    lines.append("                msg, metadata = chunk[1]")
    lines.append('                if msg.type == "AIMessageChunk":')
    lines.append("                    if msg.content:")
    lines.append(
        "                        text = msg.content if isinstance(msg.content, str) else ''"
    )
    lines.append("                        if not text and isinstance(msg.content, list):")
    lines.append("                            for block in msg.content:")
    lines.append(
        "                                if isinstance(block, dict) and block.get('type') == 'text':"
    )
    lines.append("                                    text += block.get('text', '')")
    lines.append("                        if text:")
    lines.append("                            oai_chunk = ChatCompletionChunk(")
    lines.append("                                id=completion_id,")
    lines.append("                                created=int(time.time()),")
    lines.append("                                model=MODEL_ID,")
    lines.append(
        "                                choices=[ChunkChoice(delta=ChunkDelta(content=text))],"
    )
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
    lines.append(
        '                                    x_vystak={"type": "tool_call_start", "tool": tc["name"]},'
    )
    lines.append("                                ).model_dump()")
    lines.append('                                yield {"data": json.dumps(oai_chunk)}')
    lines.append("                    if hasattr(msg, 'usage_metadata') and msg.usage_metadata:")
    lines.append("                        um = msg.usage_metadata")
    lines.append("                        inp = um.get('input_tokens', 0)")
    lines.append("                        out = um.get('output_tokens', 0)")
    lines.append("                        if inp or out:")
    lines.append(
        '                            usage = {"prompt_tokens": inp, "completion_tokens": out, "total_tokens": um.get("total_tokens", 0)}'
    )
    lines.append('                elif msg.type == "tool":')
    lines.append("                    tool_name = getattr(msg, 'name', 'tool')")
    lines.append("                    output_str = str(msg.content)[:200] if msg.content else ''")
    lines.append("                    oai_chunk = ChatCompletionChunk(")
    lines.append("                        id=completion_id,")
    lines.append("                        created=int(time.time()),")
    lines.append("                        model=MODEL_ID,")
    lines.append("                        choices=[ChunkChoice(delta=ChunkDelta())],")
    lines.append(
        '                        x_vystak={"type": "tool_result", "tool": tool_name, "result": output_str},'
    )
    lines.append("                    ).model_dump()")
    lines.append('                    yield {"data": json.dumps(oai_chunk)}')
    lines.append("                    tool_msgs.append(msg)")
    lines.append("        # Final chunk with finish_reason")
    lines.append("        final = ChatCompletionChunk(")
    lines.append("            id=completion_id,")
    lines.append("            created=int(time.time()),")
    lines.append("            model=MODEL_ID,")
    lines.append('            choices=[ChunkChoice(delta=ChunkDelta(), finish_reason="stop")],')
    lines.append("        ).model_dump()")
    lines.append('        yield {"data": json.dumps(final)}')

    if uses_persistent:
        lines.append("        # Process memory actions from tool messages")
        lines.append("        if tool_msgs:")
        lines.append(
            "            await handle_memory_actions(_store, tool_msgs, user_id=request.user_id, project_id=request.project_id)"
        )

    lines.append('        yield {"data": "[DONE]"}')
    lines.append("")
    lines.append("    return EventSourceResponse(event_generator())")
    lines.append("")
    lines.append("")

    # === Response storage ===
    lines.append("# Response storage (in-memory)")
    lines.append("_responses: dict[str, dict] = {}")
    lines.append("")
    lines.append("")

    # === POST /v1/responses ===
    lines.append('@app.post("/v1/responses")')
    lines.append("async def create_response(request: CreateResponseRequest):")
    lines.append("    user_id = request.user_id")
    lines.append("    project_id = request.project_id")
    lines.append("    store = getattr(request, 'store', True)")
    lines.append("    previous_id = request.previous_response_id")
    lines.append("")
    lines.append("    # Parse input into messages")
    lines.append("    input_messages = []")

    if uses_persistent:
        lines.append("    last_user_msg = ''")

    lines.append("    if isinstance(request.input, str):")
    lines.append("        input_messages.append(('user', request.input))")
    if uses_persistent:
        lines.append("        last_user_msg = request.input")
    lines.append("    else:")
    lines.append("        for item in request.input:")
    lines.append("            if isinstance(item, dict):")
    lines.append(
        "                input_messages.append((item.get('role', 'user'), item.get('content', '')))"
    )
    if uses_persistent:
        lines.append("                if item.get('role') == 'user' and item.get('content'):")
        lines.append("                    last_user_msg = item['content']")
    lines.append("            elif hasattr(item, 'role'):")
    lines.append("                input_messages.append((item.role, item.content or ''))")
    if uses_persistent:
        lines.append("                if item.role == 'user' and item.content:")
        lines.append("                    last_user_msg = item.content")
    lines.append("")

    # Determine thread_id and response_id based on store + previous_response_id
    lines.append("    # Determine thread_id and response_id")
    lines.append("    if previous_id:")
    lines.append("        if previous_id not in _responses:")
    lines.append(
        "            return JSONResponse(status_code=404, content=ErrorResponse(error=ErrorDetail("
    )
    lines.append("                message=f\"Response '{previous_id}' not found\",")
    lines.append('                type="invalid_request_error", code="response_not_found",')
    lines.append("            )).model_dump())")
    lines.append("        prev = _responses[previous_id]")
    lines.append("        if not prev.get('stored'):")
    lines.append(
        "            return JSONResponse(status_code=400, content=ErrorResponse(error=ErrorDetail("
    )
    lines.append('                message="Cannot chain from a response created with store=false",')
    lines.append('                type="invalid_request_error", code="invalid_value",')
    lines.append("            )).model_dump())")
    lines.append("        thread_id = prev.get('thread_id', str(uuid.uuid4()))")
    lines.append("        response_id = f'resp-{uuid.uuid4().hex[:16]}'")
    lines.append("    elif store:")
    lines.append("        response_id = f'resp-{uuid.uuid4().hex[:16]}'")
    lines.append("        thread_id = response_id")
    lines.append("    else:")
    lines.append("        response_id = f'resp-{uuid.uuid4().hex[:16]}'")
    lines.append("        thread_id = str(uuid.uuid4())")
    lines.append("")
    lines.append('    config = {"configurable": {')
    lines.append('        "thread_id": thread_id,')
    lines.append('        "user_id": user_id,')
    lines.append('        "project_id": project_id,')
    lines.append('        "agent_name": AGENT_NAME,')
    lines.append("    }}")
    lines.append("")

    # Memory recall is handled by the agent's prompt callable (ephemeral, not checkpointed)

    # Streaming
    lines.append("    if request.stream:")
    lines.append(
        "        return await _stream_response(input_messages, config, response_id, request)"
    )
    lines.append("")

    # Background
    lines.append("    if request.background:")
    lines.append("        # Store in-progress response and launch background task")
    lines.append("        _responses[response_id] = {")
    lines.append("            'id': response_id,")
    lines.append("            'status': 'in_progress',")
    lines.append("            'output': [],")
    lines.append("            'model': MODEL_ID,")
    lines.append("            'stored': store,")
    lines.append("            'thread_id': thread_id,")
    lines.append("            'created_at': int(time.time()),")
    lines.append("        }")
    lines.append(
        "        asyncio.create_task(_run_background(input_messages, config, response_id, request))"
    )
    lines.append("        return ResponseObject(")
    lines.append("            id=response_id,")
    lines.append('            status="in_progress",')
    lines.append("            output=[],")
    lines.append("            model=MODEL_ID,")
    lines.append("            created_at=int(time.time()),")
    lines.append("        ).model_dump()")
    lines.append("")

    # Synchronous invoke
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
        lines.append(
            "    await handle_memory_actions(_store, result['messages'], user_id=user_id, project_id=project_id)"
        )

    lines.append("")
    lines.append("    last = result['messages'][-1]")
    lines.append("    usage_obj = None")
    lines.append("    if hasattr(last, 'usage_metadata') and last.usage_metadata:")
    lines.append("        um = last.usage_metadata")
    lines.append("        usage_obj = ResponseUsage(")
    lines.append("            input_tokens=um.get('input_tokens', 0),")
    lines.append("            output_tokens=um.get('output_tokens', 0),")
    lines.append("            total_tokens=um.get('total_tokens', 0),")
    lines.append("        )")
    lines.append("")
    lines.append(
        "    output = [ResponseOutput(type='message', role='assistant', content=response_text)]"
    )
    lines.append("    resp = ResponseObject(")
    lines.append("        id=response_id,")
    lines.append('        status="completed",')
    lines.append("        output=output,")
    lines.append("        model=MODEL_ID,")
    lines.append("        usage=usage_obj,")
    lines.append("        created_at=int(time.time()),")
    lines.append("    )")
    lines.append("    if store:")
    lines.append("        _responses[response_id] = {")
    lines.append("            'id': response_id,")
    lines.append("            'status': 'completed',")
    lines.append("            'output': output,")
    lines.append("            'model': MODEL_ID,")
    lines.append("            'usage': usage_obj,")
    lines.append("            'stored': True,")
    lines.append("            'thread_id': thread_id,")
    lines.append("            'created_at': int(time.time()),")
    lines.append("            'response': resp.model_dump(),")
    lines.append("        }")
    lines.append("    return resp.model_dump()")
    lines.append("")
    lines.append("")

    # === Background runner ===
    lines.append("async def _run_background(input_messages, config, response_id, request):")
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
    lines.append(
        "        output = [ResponseOutput(type='message', role='assistant', content=response_text)]"
    )
    lines.append("        last = result['messages'][-1]")
    lines.append("        usage_obj = None")
    lines.append("        if hasattr(last, 'usage_metadata') and last.usage_metadata:")
    lines.append("            um = last.usage_metadata")
    lines.append("            usage_obj = ResponseUsage(")
    lines.append("                input_tokens=um.get('input_tokens', 0),")
    lines.append("                output_tokens=um.get('output_tokens', 0),")
    lines.append("                total_tokens=um.get('total_tokens', 0),")
    lines.append("            )")
    lines.append("        _responses[response_id].update({")
    lines.append("            'status': 'completed',")
    lines.append("            'output': output,")
    lines.append("            'usage': usage_obj,")
    lines.append("        })")
    lines.append("    except Exception as exc:")
    lines.append("        _responses[response_id].update({")
    lines.append("            'status': 'failed',")
    lines.append("            'error': str(exc),")
    lines.append("        })")
    lines.append("")
    lines.append("")

    # === GET /v1/responses/{response_id} ===
    lines.append('@app.get("/v1/responses/{response_id}")')
    lines.append("async def get_response(response_id: str):")
    lines.append("    if response_id not in _responses:")
    lines.append(
        "        return JSONResponse(status_code=404, content=ErrorResponse(error=ErrorDetail("
    )
    lines.append("            message=f\"Response '{response_id}' not found\",")
    lines.append('            type="invalid_request_error", code="response_not_found",')
    lines.append("        )).model_dump())")
    lines.append("    stored = _responses[response_id]")
    lines.append("    if 'response' in stored:")
    lines.append("        return stored['response']")
    lines.append("    return ResponseObject(")
    lines.append("        id=stored['id'],")
    lines.append("        status=stored['status'],")
    lines.append("        output=stored.get('output', []),")
    lines.append("        model=stored.get('model', MODEL_ID),")
    lines.append("        usage=stored.get('usage'),")
    lines.append("        created_at=stored.get('created_at', 0),")
    lines.append("    ).model_dump()")
    lines.append("")
    lines.append("")

    # === Responses streaming helper ===
    lines.append("async def _stream_response(input_messages, config, response_id, request):")
    lines.append("    store = getattr(request, 'store', True)")
    lines.append("")
    lines.append("    async def event_generator():")
    lines.append("        created_at = int(time.time())")
    lines.append("        # response.created")
    lines.append("        created_event = {")
    lines.append('            "type": "response.created",')
    lines.append('            "response": {')
    lines.append('                "id": response_id,')
    lines.append('                "status": "in_progress",')
    lines.append('                "output": [],')
    lines.append('                "model": MODEL_ID,')
    lines.append('                "created_at": created_at,')
    lines.append("            },")
    lines.append("        }")
    lines.append('        yield {"data": json.dumps(created_event)}')
    lines.append("")
    lines.append("        output_index = 0")
    lines.append("        accumulated = []")
    lines.append("        pending_tool_calls = {}")
    lines.append(
        "        tool_messages_for_memory = []  # Collect tool messages for memory processing"
    )
    lines.append("        final_output = []")
    lines.append("")
    lines.append("        # response.output_item.added (message)")
    lines.append("        item_added = {")
    lines.append('            "type": "response.output_item.added",')
    lines.append('            "output_index": output_index,')
    lines.append('            "item": {"type": "message", "role": "assistant", "content": []},')
    lines.append("        }")
    lines.append('        yield {"data": json.dumps(item_added)}')
    lines.append("")
    lines.append("        # response.content_part.added")
    lines.append("        part_added = {")
    lines.append('            "type": "response.content_part.added",')
    lines.append('            "output_index": output_index,')
    lines.append('            "content_index": 0,')
    lines.append('            "part": {"type": "output_text", "text": ""},')
    lines.append("        }")
    lines.append('        yield {"data": json.dumps(part_added)}')
    lines.append("")
    lines.append(f"        async for chunk in {agent_ref}.astream(")
    lines.append('            {"messages": input_messages},')
    lines.append("            config=config,")
    lines.append('            stream_mode=["messages", "custom"],')
    lines.append("        ):")
    lines.append('            if chunk[0] == "messages":')
    lines.append("                msg, metadata = chunk[1]")
    lines.append('                if msg.type == "AIMessageChunk":')
    lines.append("                    if msg.content:")
    lines.append(
        "                        text = msg.content if isinstance(msg.content, str) else ''"
    )
    lines.append("                        if not text and isinstance(msg.content, list):")
    lines.append("                            for block in msg.content:")
    lines.append(
        "                                if isinstance(block, dict) and block.get('type') == 'text':"
    )
    lines.append("                                    text += block.get('text', '')")
    lines.append("                        if text:")
    lines.append("                            accumulated.append(text)")
    lines.append("                            delta_event = {")
    lines.append('                                "type": "response.output_text.delta",')
    lines.append('                                "output_index": output_index,')
    lines.append('                                "content_index": 0,')
    lines.append('                                "delta": text,')
    lines.append("                            }")
    lines.append('                            yield {"data": json.dumps(delta_event)}')
    lines.append("                    if msg.tool_call_chunks:")
    lines.append("                        for tc in msg.tool_call_chunks:")
    lines.append("                            tc_id = tc.get('id') or tc.get('index', '')")
    lines.append("                            if tc.get('name'):")
    lines.append("                                output_index += 1")
    lines.append("                                pending_tool_calls[str(tc_id)] = {")
    lines.append("                                    'name': tc['name'],")
    lines.append("                                    'args': '',")
    lines.append("                                    'output_index': output_index,")
    lines.append("                                }")
    lines.append("                                fc_added = {")
    lines.append('                                    "type": "response.output_item.added",')
    lines.append('                                    "output_index": output_index,')
    lines.append(
        '                                    "item": {"type": "function_call", "name": tc["name"], "call_id": str(tc_id)},'
    )
    lines.append("                                }")
    lines.append('                                yield {"data": json.dumps(fc_added)}')
    lines.append("                            if tc.get('args'):")
    lines.append("                                key = str(tc_id)")
    lines.append("                                if key in pending_tool_calls:")
    lines.append(
        "                                    pending_tool_calls[key]['args'] += tc['args']"
    )
    lines.append("                                args_delta = {")
    lines.append(
        '                                    "type": "response.function_call_arguments.delta",'
    )
    lines.append(
        '                                    "output_index": pending_tool_calls.get(key, {}).get("output_index", output_index),'
    )
    lines.append('                                    "delta": tc["args"],')
    lines.append("                                }")
    lines.append('                                yield {"data": json.dumps(args_delta)}')
    lines.append('                elif msg.type == "tool":')
    lines.append("                    # Close pending tool call")
    lines.append("                    tool_call_id = getattr(msg, 'tool_call_id', None)")
    lines.append("                    if tool_call_id and str(tool_call_id) in pending_tool_calls:")
    lines.append("                        tc_info = pending_tool_calls.pop(str(tool_call_id))")
    lines.append("                        args_done = {")
    lines.append('                            "type": "response.function_call_arguments.done",')
    lines.append('                            "output_index": tc_info["output_index"],')
    lines.append('                            "arguments": tc_info["args"],')
    lines.append("                        }")
    lines.append('                        yield {"data": json.dumps(args_done)}')
    lines.append("                    # Emit tool output")
    lines.append("                    output_index += 1")
    lines.append("                    tool_output = {")
    lines.append('                        "type": "response.output_item.added",')
    lines.append('                        "output_index": output_index,')
    lines.append('                        "item": {')
    lines.append('                            "type": "function_call_output",')
    lines.append('                            "call_id": str(getattr(msg, "tool_call_id", "")),')
    lines.append(
        '                            "output": str(msg.content)[:500] if msg.content else "",'
    )
    lines.append("                        },")
    lines.append("                    }")
    lines.append('                    yield {"data": json.dumps(tool_output)}')
    lines.append("                    tool_messages_for_memory.append(msg)")
    lines.append("")
    lines.append("        # response.output_text.done")
    lines.append("        full_text = ''.join(accumulated)")
    lines.append("        text_done = {")
    lines.append('            "type": "response.output_text.done",')
    lines.append('            "output_index": 0,')
    lines.append('            "content_index": 0,')
    lines.append('            "text": full_text,')
    lines.append("        }")
    lines.append('        yield {"data": json.dumps(text_done)}')
    lines.append("")
    lines.append(
        "        final_output = [ResponseOutput(type='message', role='assistant', content=full_text)]"
    )
    lines.append("")
    lines.append("        # response.completed")
    lines.append("        completed_event = {")
    lines.append('            "type": "response.completed",')
    lines.append('            "response": {')
    lines.append('                "id": response_id,')
    lines.append('                "status": "completed",')
    lines.append(
        '                "output": [o.model_dump() if hasattr(o, "model_dump") else o for o in final_output],'
    )
    lines.append('                "model": MODEL_ID,')
    lines.append('                "created_at": created_at,')
    lines.append("            },")
    lines.append("        }")
    lines.append('        yield {"data": json.dumps(completed_event)}')
    lines.append("")
    lines.append("        if store:")
    lines.append("            _responses[response_id] = {")
    lines.append("                'id': response_id,")
    lines.append("                'status': 'completed',")
    lines.append("                'output': final_output,")
    lines.append("                'model': MODEL_ID,")
    lines.append("                'stored': True,")
    lines.append("                'thread_id': config['configurable']['thread_id'],")
    lines.append("                'created_at': created_at,")
    lines.append("            }")
    lines.append("")

    if uses_persistent:
        lines.append("        # Process memory actions from tool messages")
        lines.append("        if tool_messages_for_memory:")
        lines.append(
            "            await handle_memory_actions(_store, tool_messages_for_memory, user_id=request.user_id, project_id=request.project_id)"
        )

    lines.append("")
    lines.append('        yield {"data": "[DONE]"}')
    lines.append("")
    lines.append("    return EventSourceResponse(event_generator())")
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

    mcp_pkg = ""
    if agent.mcp_servers:
        mcp_pkg = "\nlangchain-mcp-adapters>=0.1"

    return dedent(f"""\
        langchain-core>=0.3
        langgraph>=0.2
        {provider_pkg}
        fastapi>=0.115
        uvicorn>=0.34
        sse-starlette>=2.0{checkpoint_pkg}{mcp_pkg}{tool_deps}
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
