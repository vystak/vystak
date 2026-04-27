"""Code generation templates for LangChain/LangGraph agents."""

from textwrap import dedent

from vystak.schema.agent import Agent

from vystak_adapter_langchain.a2a import (
    generate_a2a_handler_code,
    generate_agent_card_code,
    generate_task_manager_code,
)
from vystak_adapter_langchain.responses import generate_responses_handler_code
from vystak_adapter_langchain.turn_core import emit_turn_core_helpers

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


# Approximate context windows for known model families (for compaction
# threshold math). Falls back to 200_000.
_CONTEXT_WINDOWS = {
    "claude-opus-4-7": 200_000,
    "claude-sonnet-4-6": 200_000,
    "claude-haiku-4-5-20251001": 200_000,
    "gpt-4o": 128_000,
    "gpt-4.1": 1_000_000,
}


def _context_window_for(agent: "Agent") -> int:
    """Resolve the context window: compaction override wins over the table default."""
    if agent.compaction is not None and agent.compaction.context_window is not None:
        return agent.compaction.context_window
    return _CONTEXT_WINDOWS.get(agent.model.model_name, 200_000)


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


def _docstring_from_instructions(peer: Agent) -> str:
    """Derive a tool docstring from the peer agent's instructions field."""
    instructions = peer.instructions or ""
    first_para = instructions.split("\n\n", 1)[0].strip()
    if not first_para:
        return f"Delegate to the {peer.name} agent."
    if len(first_para) > 200:
        return first_para[:200].rstrip() + "…"
    return first_para


def _generate_subagent_tools(agent: Agent) -> str:
    """Emit one async @tool wrapper per declared subagent."""
    if not agent.subagents:
        return ""
    blocks = []
    for peer in agent.subagents:
        tool_name = f"ask_{peer.name.replace('-', '_')}"
        docstring = _docstring_from_instructions(peer).replace('"""', '\\"\\"\\"')
        block = (
            "@tool\n"
            f"async def {tool_name}(question: str, config: RunnableConfig) -> str:\n"
            f'    """{docstring}"""\n'
            f"    session_id = (config.get('configurable') or {{}}).get('thread_id')\n"
            "    metadata = {'sessionId': session_id} if session_id else {}\n"
            f"    return await ask_agent({peer.name!r}, question, metadata=metadata)"
        )
        blocks.append(block)
    return "\n\n\n".join(blocks)


def _subagent_tool_names(agent: Agent) -> list[str]:
    """Tool function names that the subagent codegen emits."""
    return [f"ask_{p.name.replace('-', '_')}" for p in agent.subagents]


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


def _compaction_enabled(agent: Agent) -> bool:
    """True when codegen should emit compaction wiring."""
    return agent.compaction is not None and agent.compaction.mode != "off"


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
    subagent_tool_code = _generate_subagent_tools(agent)
    subagent_tool_names = _subagent_tool_names(agent)

    collisions = set(subagent_tool_names) & set(found_tool_names + stub_tool_names)
    if collisions:
        raise ValueError(
            f"Tool name conflict: {sorted(collisions)} are auto-generated "
            f"for subagents but also defined as user tools. "
            f"Remove the user tool or rename it."
        )

    all_tool_names = found_tool_names + stub_tool_names + subagent_tool_names
    tools_list = ", ".join(all_tool_names) if all_tool_names else ""

    # When a workspace is declared, the built-in tool wrappers in
    # builtin_tools.py (generated separately) expose an ALL_TOOLS list that
    # must be passed into create_react_agent alongside any user-defined tools.
    has_workspace = agent.workspace is not None

    # System prompt
    system_prompt = _collect_system_prompt(agent)

    # Checkpointer based on resources
    session_store = _get_session_store(agent)
    compaction_enabled = _compaction_enabled(agent)

    # Build the agent code
    lines = []
    lines.append(f'"""Vystak generated agent: {agent.name}."""\n')
    lines.append(f"{model_import}")

    # Import tool decorator if needed (stub tools or memory tools)
    if stub_tool_names or session_store or subagent_tool_code:
        lines.append("from langchain_core.tools import tool")

    if subagent_tool_code:
        lines.append("from langchain_core.runnables import RunnableConfig")

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
    if subagent_tool_code:
        lines.append("")
        lines.append("from vystak.transport import ask_agent")
    if has_mcp:
        lines.append("from langchain_mcp_adapters.client import MultiServerMCPClient")
        lines.append(_generate_mcp_config(agent))
    if compaction_enabled:
        lines.append("")
        lines.append("# Compaction (Layer 1 prune + Layer 2 autonomous middleware)")
        lines.append(
            "from vystak_adapter_langchain.compaction import "
            "prune_messages, maybe_compact, assign_vystak_msg_id, message_id, "
            "summarize as _vystak_summarize, resolve_preset"
        )
        lines.append("from langchain.agents.middleware import create_summarization_tool_middleware")
    lines.append("")
    lines.append("")
    lines.append("# Model")
    lines.append(f"model = {model_class}({model_kwargs_str})")
    lines.append("")

    if compaction_enabled:
        comp = agent.compaction
        summ_model = comp.summarizer or agent.model
        summ_import, summ_class = MODEL_PROVIDERS.get(
            summ_model.provider.type, MODEL_PROVIDERS["anthropic"]
        )
        # Avoid duplicate import.
        if summ_import not in "\n".join(lines):
            lines.append(summ_import)
        lines.append("")
        lines.append("# Compaction summarizer model")
        lines.append(
            f'_compaction_summarizer = {summ_class}(model="{summ_model.model_name}")'
        )
        lines.append("")
        lines.append("# Resolved compaction policy (preset + overrides)")
        lines.append("from vystak.schema.compaction import Compaction as _Compaction")
        lines.append(
            "_compaction_policy = resolve_preset(_Compaction("
            f"mode={comp.mode!r}, "
            f"trigger_pct={comp.trigger_pct!r}, "
            f"keep_recent_pct={comp.keep_recent_pct!r}, "
            f"prune_tool_output_bytes={comp.prune_tool_output_bytes!r}, "
            f"target_tokens={comp.target_tokens!r}), "
            f"context_window={_context_window_for(agent)})"
        )
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

    if subagent_tool_code:
        lines.append("")
        lines.append("")
        lines.append("# Auto-generated subagent delegation tools")
        lines.append(subagent_tool_code)
        lines.append("")

    if has_workspace:
        lines.append("")
        lines.append("# Built-in workspace tools (fs.*, exec.*, git.*)")
        lines.append("from builtin_tools import ALL_TOOLS as _builtin_tools")

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

    # Splice in built-in workspace tools at the end so they're always available
    # to the react agent when a workspace is declared.
    if has_workspace:
        full_tools_list = (
            f"{full_tools_list}, *_builtin_tools" if full_tools_list else "*_builtin_tools"
        )

    # Build middlewares kwarg for create_react_agent (Layer 2 compaction middleware).
    middlewares_kw = ""
    if compaction_enabled:
        middlewares_kw = (
            ", middlewares=[create_summarization_tool_middleware("
            "model=_compaction_summarizer, "
            "keep_last_n_messages=int(_compaction_policy.keep_recent_pct * 100))]"
        )

    # For persistent checkpointers, create agent via function (memory set at startup)
    # Use a prompt callable so memory recall is ephemeral (never saved to checkpoint state)
    uses_persistent_session_store = bool(
        session_store and session_store.engine in ("postgres", "sqlite")
    )
    if compaction_enabled and uses_persistent_session_store:
        # Compaction-aware prompt callable.
        # (Replaces the existing `_make_prompt(base_prompt, mem_store)` block.)
        lines.append("")
        lines.append("def _make_prompt(base_prompt, mem_store, compaction_store, compaction_policy, ctx_window):")
        lines.append('    """Prompt callable: recall + prune + threshold-compact + system."""')
        lines.append("    _next_msgid = {'value': 1}")
        lines.append("    async def prompt(state, config):")
        lines.append("        user_id = config.get('configurable', {}).get('user_id')")
        lines.append("        project_id = config.get('configurable', {}).get('project_id')")
        lines.append("        thread_id = config.get('configurable', {}).get('thread_id', 'unknown')")
        lines.append("        last_input_tokens = config.get('configurable', {}).get('last_input_tokens')")
        lines.append("        messages = list(state.get('messages', []))")
        lines.append("        # Stamp stable vystak_msg_id on any new messages.")
        lines.append("        _next_msgid['value'] = assign_vystak_msg_id(messages, thread_id=thread_id, start=_next_msgid['value'])")
        lines.append("")
        lines.append("        # Layer 1 — prune oversized tool outputs in older turns")
        lines.append("        messages = prune_messages(messages,")
        lines.append("            max_tool_output_bytes=compaction_policy.prune_tool_output_bytes,")
        lines.append("            keep_last_turns=3)")
        lines.append("")
        lines.append("        # Apply existing summary if any (Layer 2 or prior Layer 3 / manual)")
        lines.append("        latest = await compaction_store.latest(thread_id)")
        lines.append("        if latest is not None:")
        lines.append("            kept = []")
        lines.append("            past_cutoff = False")
        lines.append("            for m in messages:")
        lines.append("                if past_cutoff:")
        lines.append("                    kept.append(m)")
        lines.append("                elif message_id(m) == latest.up_to_message_id:")
        lines.append("                    past_cutoff = True")
        lines.append("            from langchain_core.messages import SystemMessage as _SM")
        lines.append("            messages = [_SM(content=latest.summary_text)] + kept")
        lines.append("")
        lines.append("        # Layer 3 — threshold pre-call summarize (with idempotency guard)")
        lines.append("        messages, fallback_reason = await maybe_compact(messages,")
        lines.append("            model=model,")
        lines.append("            last_input_tokens=last_input_tokens,")
        lines.append("            context_window=ctx_window,")
        lines.append("            trigger_pct=compaction_policy.trigger_pct,")
        lines.append("            keep_recent_pct=compaction_policy.keep_recent_pct,")
        lines.append("            target_tokens=compaction_policy.target_tokens,")
        lines.append("            summarizer=_compaction_summarizer,")
        lines.append("            summarize_fn=_vystak_summarize,")
        lines.append("            compaction_store=compaction_store,")
        lines.append("            thread_id=thread_id)")
        lines.append("        if fallback_reason is not None:")
        lines.append("            config.setdefault('configurable', {})['_vystak_compaction_fallback'] = fallback_reason")
        lines.append("")
        lines.append("        # Build system prompt from base + recalled memories")
        lines.append("        last_msg = ''")
        lines.append("        for m in reversed(state.get('messages', [])):")
        lines.append("            if hasattr(m, 'content') and isinstance(m.content, str) and getattr(m, 'type', '') == 'human':")
        lines.append("                last_msg = m.content")
        lines.append("                break")
        lines.append("        memories = []")
        lines.append("        if mem_store and last_msg:")
        lines.append("            if user_id:")
        lines.append("                results = await mem_store.asearch(('user', user_id, 'memories'), query=last_msg, limit=5)")
        lines.append("                for item in results:")
        lines.append("                    memories.append(f'[{item.key}] {item.value.get(\"data\", \"\")} (scope: user)')")
        lines.append("            if project_id:")
        lines.append("                results = await mem_store.asearch(('project', project_id, 'memories'), query=last_msg, limit=5)")
        lines.append("                for item in results:")
        lines.append("                    memories.append(f'[{item.key}] {item.value.get(\"data\", \"\")} (scope: project)')")
        lines.append("            results = await mem_store.asearch(('global', 'memories'), query=last_msg, limit=5)")
        lines.append("            for item in results:")
        lines.append("                memories.append(f'[{item.key}] {item.value.get(\"data\", \"\")} (scope: global)')")
        lines.append("        parts = []")
        lines.append("        if base_prompt:")
        lines.append("            parts.append(base_prompt)")
        lines.append("        if memories:")
        lines.append('            parts.append("Relevant memories:\\n" + "\\n".join(memories))')
        lines.append('        system_content = "\\n\\n".join(parts) if parts else "You are a helpful assistant."')
        lines.append('        return [{"role": "system", "content": system_content}] + messages')
        lines.append("    return prompt")
        lines.append("")
        # Compaction-aware factory.
        lines.append("def create_agent(checkpointer, store=None, compaction_store=None, mcp_tools=None):")
        lines.append(f"    all_tools = [{full_tools_list}]")
        lines.append("    if mcp_tools:")
        lines.append("        all_tools.extend(mcp_tools)")
        if system_prompt:
            lines.append(f"    prompt_fn = _make_prompt(system_prompt, store, compaction_store, _compaction_policy, {_context_window_for(agent)})")
        else:
            lines.append(f"    prompt_fn = _make_prompt(None, store, compaction_store, _compaction_policy, {_context_window_for(agent)})")
        lines.append(
            "    return create_react_agent(model, all_tools, checkpointer=checkpointer, store=store, prompt=prompt_fn"
            + middlewares_kw + ")"
        )
        lines.append("")
        lines.append("agent = None  # created during server lifespan")
    elif uses_persistent_session_store:
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
            "    return create_react_agent(model, all_tools, checkpointer=checkpointer, store=store, prompt=prompt_fn"
            + middlewares_kw + ")"
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
                "    return create_react_agent(model, all_tools, checkpointer=memory, prompt=system_prompt"
                + middlewares_kw + ")"
            )
        else:
            lines.append(
                "    return create_react_agent(model, all_tools, checkpointer=memory"
                + middlewares_kw + ")"
            )
        lines.append("")
        lines.append("agent = None  # created during server lifespan")
    else:
        if system_prompt:
            lines.append(
                f"agent = create_react_agent(model, [{full_tools_list}], checkpointer=memory, prompt=system_prompt"
                + middlewares_kw + ")"
            )
        else:
            lines.append(
                f"agent = create_react_agent(model, [{full_tools_list}], checkpointer=memory"
                + middlewares_kw + ")"
            )

    lines.append("")

    return "\n".join(lines)


def generate_server_py(agent: Agent) -> str:
    """Generate a FastAPI harness server file."""
    session_store = _get_session_store(agent)
    uses_persistent = session_store and session_store.engine in ("postgres", "sqlite")
    has_mcp = _has_mcp_servers(agent)
    compaction_enabled = _compaction_enabled(agent)

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
    lines.append("import logging")
    lines.append("import os")
    lines.append("import time")
    lines.append("import uuid")
    lines.append("from dataclasses import dataclass")
    lines.append("from types import SimpleNamespace")
    lines.append("from typing import Literal")
    lines.append("from langgraph.types import Command")
    lines.append("")
    lines.append("# Configure root logging so vystak.transport.nats (and other")
    lines.append("# module loggers) actually emit to stderr.")
    lines.append("logging.basicConfig(")
    lines.append('    level=os.environ.get("LOG_LEVEL", "INFO"),')
    lines.append('    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",')
    lines.append(")")
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

    if compaction_enabled:
        lines.append("from vystak_adapter_langchain.compaction import (")
        lines.append("    InMemoryCompactionStore,")
        if uses_persistent and session_store.engine == "postgres":
            lines.append("    PostgresCompactionStore,")
        elif uses_persistent and session_store.engine == "sqlite":
            lines.append("    SqliteCompactionStore,")
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
        if compaction_enabled:
            lines.append("_compaction_store = None")
        if has_mcp:
            lines.append("_mcp_client = None")
        lines.append("")
        lines.append("")
        lines.append("@asynccontextmanager")
        lines.append("async def lifespan(app):")
        if has_mcp:
            if compaction_enabled:
                lines.append("    global _agent, _store, _compaction_store, _mcp_client")
            else:
                lines.append("    global _agent, _store, _mcp_client")
        else:
            if compaction_enabled:
                lines.append("    global _agent, _store, _compaction_store")
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
            if compaction_enabled:
                if session_store.engine == "postgres":
                    lines.append("        # Compaction store on a separate connection")
                    lines.append("        import psycopg as _psycopg")
                    lines.append("        _comp_conn = await _psycopg.AsyncConnection.connect(DB_URI, autocommit=True)")
                    lines.append("        _compaction_store = PostgresCompactionStore(_comp_conn)")
                    lines.append("        await _compaction_store.setup()")
                else:
                    lines.append("        import aiosqlite as _aiosqlite")
                    lines.append("        _comp_db = await _aiosqlite.connect(DB_URI)")
                    lines.append("        _compaction_store = SqliteCompactionStore(_comp_db)")
                    lines.append("        await _compaction_store.setup()")
                lines.append(
                    "        _agent = create_agent(checkpointer, store=store, compaction_store=_compaction_store, mcp_tools=mcp_tools)"
                )
            else:
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
                if compaction_enabled:
                    lines.append("                # Compaction store on a separate connection")
                    lines.append("                import psycopg as _psycopg")
                    lines.append("                _comp_conn = await _psycopg.AsyncConnection.connect(DB_URI, autocommit=True)")
                    lines.append("                _compaction_store = PostgresCompactionStore(_comp_conn)")
                    lines.append("                await _compaction_store.setup()")
                    lines.append("                _agent = create_agent(checkpointer, store=store, compaction_store=_compaction_store)")
                else:
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
                if compaction_enabled:
                    lines.append("        import aiosqlite as _aiosqlite")
                    lines.append("        _comp_db = await _aiosqlite.connect(DB_URI)")
                    lines.append("        _compaction_store = SqliteCompactionStore(_comp_db)")
                    lines.append("        await _compaction_store.setup()")
                    lines.append("        _agent = create_agent(checkpointer, store=store, compaction_store=_compaction_store)")
                else:
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
        if compaction_enabled:
            lines.append("_compaction_store = InMemoryCompactionStore()")
        lines.append("")
        lines.append("")
        lines.append("@asynccontextmanager")
        lines.append("async def lifespan(app):")
        lines.append("    global _agent, _mcp_client")
        lines.append("    _mcp_client = MultiServerMCPClient(MCP_SERVERS)")
        if compaction_enabled:
            lines.append("    _agent = create_agent(mcp_tools=await _mcp_client.get_tools(), compaction_store=_compaction_store)")
        else:
            lines.append("    _agent = create_agent(mcp_tools=await _mcp_client.get_tools())")
        lines.append("    yield")
        lines.append("")
        lines.append("")
        lines.append(f'app = FastAPI(title="{agent.name}", lifespan=lifespan)')
    else:
        # Case 4: not persistent + no MCP
        if compaction_enabled:
            lines.append("from agent import create_agent")
            lines.append("from langgraph.checkpoint.memory import MemorySaver as _MS")
            lines.append("_memory_saver = _MS()")
            lines.append("")
            lines.append("_compaction_store = InMemoryCompactionStore()")
            lines.append("_agent = create_agent(checkpointer=_memory_saver, store=None, compaction_store=_compaction_store)")
        else:
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
    else:
        # Stateless agents (no sessions, no memory): emit _store = None and a no-op
        # handle_memory_actions stub so that the turn cores' `if _store is not None:`
        # guards work correctly and static analysis doesn't flag F821 NameErrors.
        lines.append("_store = None")
        lines.append("")
        lines.append("")
        lines.append(
            "async def handle_memory_actions(*_args, **_kwargs):"
        )
        lines.append('    """No-op stub for stateless agents — cores\' if _store is not None: guards skip the call anyway."""')
        lines.append("    return None")
        lines.append("")
        lines.append("")

    # Emit the shared turn cores. Every protocol layer (A2A,
    # chat_completions, /v1/responses) calls these instead of
    # duplicating _agent.ainvoke / handle_memory_actions logic per path.
    lines.append(emit_turn_core_helpers())
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
    lines.append("    # Stateless: random one-shot thread_id (still needed for streaming branch)")
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
    lines.append("    # Delegate to the shared one-shot core. Pass the full message history")
    lines.append("    # via the messages kwarg — chat completions are stateless so we replay")
    lines.append("    # the entire conversation each call.")
    lines.append("    metadata = {")
    lines.append('        "sessionId": str(uuid.uuid4()),  # stateless: fresh thread_id per call')
    lines.append('        "user_id": user_id,')
    lines.append('        "project_id": project_id,')
    lines.append("    }")
    lines.append("    turn = await process_turn('', metadata, messages=messages)")
    lines.append("    response_text = turn.response_text")
    lines.append("")
    lines.append("    # TODO: surface usage_metadata via TurnResult — currently zero; tracked separately.")
    lines.append("    usage = None")
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
    lines.append('    """Streaming /v1/chat/completions — delegates to process_turn_streaming.')
    lines.append("")
    lines.append("    Wire-shape translator: each TurnEvent token becomes one OpenAI")
    lines.append("    SSE chunk. The previous x_vystak extension events (tool_call_start,")
    lines.append("    tool_result, custom-mode messages, mid-stream usage_metadata) are")
    lines.append("    not preserved — this is a deliberate trade in exchange for a")
    lines.append("    single shared streaming core.")
    lines.append('    """')
    lines.append('    completion_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"')
    lines.append("")
    lines.append("    metadata = {")
    lines.append('        "sessionId": str(uuid.uuid4()),')
    lines.append('        "user_id": request.user_id,')
    lines.append('        "project_id": request.project_id,')
    lines.append("    }")
    lines.append("")
    lines.append("    async def event_generator():")
    lines.append("        async for ev in process_turn_streaming(")
    lines.append("            '', metadata, messages=messages,")
    lines.append("        ):")
    lines.append('            if ev.type == "token":')
    lines.append("                chunk = ChatCompletionChunk(")
    lines.append("                    id=completion_id,")
    lines.append("                    created=int(time.time()),")
    lines.append("                    model=MODEL_ID,")
    lines.append("                    choices=[ChunkChoice(delta=ChunkDelta(content=ev.text))],")
    lines.append("                ).model_dump()")
    lines.append('                yield {"data": json.dumps(chunk)}')
    lines.append('            elif ev.type == "interrupt":')
    lines.append("                # Surface interrupt as a final chunk with stop reason.")
    lines.append("                final = ChatCompletionChunk(")
    lines.append("                    id=completion_id,")
    lines.append("                    created=int(time.time()),")
    lines.append("                    model=MODEL_ID,")
    lines.append('                    choices=[ChunkChoice(delta=ChunkDelta(content=ev.text), finish_reason="stop")],')
    lines.append("                ).model_dump()")
    lines.append('                yield {"data": json.dumps(final)}')
    lines.append('                yield {"data": "[DONE]"}')
    lines.append("                return")
    lines.append('            elif ev.type == "final":')
    lines.append("                final = ChatCompletionChunk(")
    lines.append("                    id=completion_id,")
    lines.append("                    created=int(time.time()),")
    lines.append("                    model=MODEL_ID,")
    lines.append('                    choices=[ChunkChoice(delta=ChunkDelta(), finish_reason="stop")],')
    lines.append("                ).model_dump()")
    lines.append('                yield {"data": json.dumps(final)}')
    lines.append('                yield {"data": "[DONE]"}')
    lines.append("                return")
    lines.append("")
    lines.append("    return EventSourceResponse(event_generator())")
    lines.append("")
    lines.append("")

    # === Response storage + ResponsesHandler ===
    lines.append("# Response storage (in-memory, shared with ResponsesHandler)")
    lines.append("_responses: dict[str, dict] = {}")
    lines.append("")
    lines.append("")
    lines.append(generate_responses_handler_code(agent))
    lines.append("")
    lines.append(
        f"_responses_handler = ResponsesHandler(graph={agent_ref}, response_store=_responses)"
    )
    lines.append("")
    lines.append("")

    # === ServerDispatcher — routes incoming JSON-RPC methods to handlers ===
    lines.append("class ServerDispatcher:")
    lines.append('    """Routes incoming JSON-RPC methods to A2A or Responses handlers.')
    lines.append("")
    lines.append("    Implements ServerDispatcherProtocol (see vystak.transport.base).")
    lines.append('    """')
    lines.append("")
    lines.append("    def __init__(self, a2a_handler, responses_handler):")
    lines.append("        self._a2a = a2a_handler")
    lines.append("        self._responses = responses_handler")
    lines.append("")
    lines.append("    async def dispatch_a2a(self, message, metadata):")
    lines.append("        return await self._a2a.dispatch(message, metadata)")
    lines.append("")
    lines.append("    def dispatch_a2a_stream(self, message, metadata):")
    lines.append("        return self._a2a.dispatch_stream(message, metadata)")
    lines.append("")
    lines.append("    async def dispatch_responses_create(self, request, metadata):")
    lines.append("        return await self._responses.create(request, metadata)")
    lines.append("")
    lines.append("    def dispatch_responses_create_stream(self, request, metadata):")
    lines.append("        return self._responses.create_stream(request, metadata)")
    lines.append("")
    lines.append("    async def dispatch_responses_get(self, response_id):")
    lines.append("        return await self._responses.get(response_id)")
    lines.append("")
    lines.append("")

    # === POST /v1/responses — thin adapter over ResponsesHandler ===
    # The handler raises ``HTTPException`` (with an ``ErrorResponse`` detail
    # dict) for the previously-inline 404/400 error paths; we re-emit those
    # as ``JSONResponse`` with the original wire shape (``{"error": {...}}``)
    # so the API surface is unchanged.
    lines.append('@app.post("/v1/responses")')
    lines.append("async def create_response(request: CreateResponseRequest):")
    lines.append("    body = request.model_dump()")
    lines.append("    if body.get('stream'):")
    lines.append("        # Start the generator eagerly so pre-stream validation errors")
    lines.append("        # (HTTPException for 404/400) surface as HTTP status codes rather")
    lines.append("        # than mid-stream exceptions.")
    lines.append("        stream_iter = _responses_handler.create_stream(body, metadata={})")
    lines.append("        try:")
    lines.append("            first = await stream_iter.__anext__()")
    lines.append("        except _ResponsesHTTPException as exc:")
    lines.append("            return JSONResponse(status_code=exc.status_code, content=exc.detail)")
    lines.append("        except StopAsyncIteration:")
    lines.append("            return JSONResponse(status_code=204, content=None)")
    lines.append("")
    lines.append("        async def _sse():")
    lines.append("            if isinstance(first, str):")
    lines.append("                yield {'data': first}")
    lines.append("            else:")
    lines.append("                yield {'data': json.dumps(first)}")
    lines.append("            async for chunk in stream_iter:")
    lines.append("                if isinstance(chunk, str):")
    lines.append("                    yield {'data': chunk}")
    lines.append("                else:")
    lines.append("                    yield {'data': json.dumps(chunk)}")
    lines.append("        return EventSourceResponse(_sse())")
    lines.append("    try:")
    lines.append("        result = await _responses_handler.create(body, metadata={})")
    lines.append("    except _ResponsesHTTPException as exc:")
    lines.append("        return JSONResponse(status_code=exc.status_code, content=exc.detail)")
    lines.append("    return result")
    lines.append("")
    lines.append("")

    # === GET /v1/responses/{response_id} — thin adapter over ResponsesHandler ===
    lines.append('@app.get("/v1/responses/{response_id}")')
    lines.append("async def get_response(response_id: str):")
    lines.append("    result = await _responses_handler.get(response_id)")
    lines.append("    if result is None:")
    lines.append("        return JSONResponse(")
    lines.append("            status_code=404,")
    lines.append("            content=ErrorResponse(error=ErrorDetail(")
    lines.append("                message=f\"Response '{response_id}' not found\",")
    lines.append('                type="invalid_request_error", code="response_not_found",')
    lines.append("            )).model_dump(),")
    lines.append("        )")
    lines.append("    return result")
    lines.append("")
    lines.append("")

    if compaction_enabled:
        lines.append("")
        lines.append("# === Compaction routes ===")
        lines.append("class CompactRequest(BaseModel):")
        lines.append("    instructions: str | None = None")
        lines.append("")
        lines.append("")
        lines.append('@app.post("/v1/sessions/{thread_id}/compact")')
        lines.append("async def compact_session(thread_id: str, body: CompactRequest):")
        lines.append("    from vystak_adapter_langchain.compaction import (")
        lines.append("        summarize as _vsummarize, message_id as _msgid,")
        lines.append("        CompactionError as _CErr,")
        lines.append("    )")
        lines.append("    state = await _agent.aget_state({'configurable': {'thread_id': thread_id}})")
        lines.append("    messages = list(state.values.get('messages', [])) if state else []")
        lines.append("    if not messages:")
        lines.append("        return JSONResponse(status_code=404, content=ErrorResponse(error=ErrorDetail(")
        lines.append('            message=f"thread \'{thread_id}\' not found",')
        lines.append('            type="invalid_request_error", code="thread_not_found",')
        lines.append("        )).model_dump())")
        lines.append("    try:")
        lines.append("        summary = await _vsummarize(_compaction_summarizer, messages, instructions=body.instructions)")
        lines.append("    except _CErr as exc:")
        lines.append("        return JSONResponse(status_code=502, content=ErrorResponse(error=ErrorDetail(")
        lines.append("            message=exc.reason,")
        lines.append('            type="server_error", code="compaction_failed",')
        lines.append("        )).model_dump())")
        lines.append("    last_id = _msgid(messages[-1]) or ''")
        lines.append("    gen = await _compaction_store.write(")
        lines.append("        thread_id=thread_id, summary_text=summary.text,")
        lines.append("        up_to_message_id=last_id, trigger='manual',")
        lines.append("        summarizer_model=summary.model_id, usage=summary.usage,")
        lines.append("    )")
        lines.append("    return {")
        lines.append("        'thread_id': thread_id, 'generation': gen,")
        lines.append("        'summary_preview': summary.text[:200],")
        lines.append("        'messages_compacted': len(messages),")
        lines.append("    }")
        lines.append("")
        lines.append("")
        lines.append('@app.get("/v1/sessions/{thread_id}/compactions")')
        lines.append("async def list_compactions(thread_id: str):")
        lines.append("    rows = await _compaction_store.list(thread_id)")
        lines.append("    return {'thread_id': thread_id, 'compactions': [")
        lines.append("        {")
        lines.append("            'generation': r.generation, 'trigger': r.trigger,")
        lines.append("            'created_at': r.created_at.isoformat(),")
        lines.append("            'summary_preview': r.summary_text[:200],")
        lines.append("            'summarizer_model': r.summarizer_model,")
        lines.append("            'input_tokens': r.input_tokens, 'output_tokens': r.output_tokens,")
        lines.append("        } for r in rows")
        lines.append("    ]}")
        lines.append("")
        lines.append("")
        lines.append('@app.get("/v1/sessions/{thread_id}/compactions/{generation}")')
        lines.append("async def get_compaction(thread_id: str, generation: int):")
        lines.append("    row = await _compaction_store.get(thread_id, generation=generation)")
        lines.append("    if row is None:")
        lines.append("        return JSONResponse(status_code=404, content=ErrorResponse(error=ErrorDetail(")
        lines.append('            message=f"compaction {generation} not found for thread \'{thread_id}\'",')
        lines.append('            type="invalid_request_error", code="compaction_not_found",')
        lines.append("        )).model_dump())")
        lines.append("    return {")
        lines.append("        'thread_id': thread_id, 'generation': row.generation,")
        lines.append("        'trigger': row.trigger, 'summary_text': row.summary_text,")
        lines.append("        'up_to_message_id': row.up_to_message_id,")
        lines.append("        'created_at': row.created_at.isoformat(),")
        lines.append("        'summarizer_model': row.summarizer_model,")
        lines.append("        'input_tokens': row.input_tokens, 'output_tokens': row.output_tokens,")
        lines.append("    }")
        lines.append("")

    # A2A Protocol (unchanged)
    lines.append(generate_task_manager_code())
    lines.append(generate_agent_card_code(agent))
    lines.append(generate_a2a_handler_code(agent))

    # --- Transport bootstrap ---
    lines.append("")
    lines.append("# --- Transport bootstrap ---")
    lines.append("import os as _os")
    lines.append("import json as _json")
    lines.append("import asyncio as _asyncio")
    lines.append("from vystak.transport import AgentClient as _AgentClient")
    lines.append("from vystak.transport import client as _vystak_client_module")
    lines.append("")
    lines.append("_routes_raw = _json.loads(_os.environ.get('VYSTAK_ROUTES_JSON', '{}'))")
    lines.append("# Short-name → canonical-name map for AgentClient:")
    lines.append("_client_routes = {k: v['canonical'] for k, v in _routes_raw.items()}")
    lines.append("# Canonical-name → wire-address map for HttpTransport:")
    lines.append("_http_routes = {v['canonical']: v['address'] for v in _routes_raw.values()}")
    lines.append("")
    lines.append("def _build_transport_from_env():")
    lines.append("    transport_type = _os.environ.get('VYSTAK_TRANSPORT_TYPE', 'http')")
    lines.append("    if transport_type == 'http':")
    lines.append("        from vystak_transport_http import HttpTransport")
    lines.append("        return HttpTransport(routes=_http_routes)")
    lines.append("    if transport_type == 'nats':")
    lines.append("        from vystak_transport_nats import NatsTransport")
    lines.append("        url = _os.environ['VYSTAK_NATS_URL']")
    lines.append("        prefix = _os.environ.get('VYSTAK_NATS_SUBJECT_PREFIX', 'vystak')")
    lines.append("        return NatsTransport(url=url, subject_prefix=prefix)")
    lines.append("    raise RuntimeError(f'unsupported VYSTAK_TRANSPORT_TYPE={transport_type}')")
    lines.append("")
    lines.append("_transport = _build_transport_from_env()")
    lines.append(f'AGENT_CANONICAL_NAME = "{agent.canonical_name}"')
    lines.append("")
    lines.append("_vystak_client_module._DEFAULT_CLIENT = _AgentClient(")
    lines.append("    transport=_transport,")
    lines.append("    routes=_client_routes,")
    lines.append(")")
    lines.append("")
    lines.append("_server_dispatcher = ServerDispatcher(")
    lines.append("    a2a_handler=_a2a_handler,")
    lines.append("    responses_handler=_responses_handler,")
    lines.append(")")
    lines.append("")
    lines.append("@app.on_event('startup')")
    lines.append("async def _start_transport_listener():")
    lines.append("    if _transport.type != 'http':")
    lines.append("        _asyncio.create_task(")
    lines.append(
        "            _transport.serve(canonical_name=AGENT_CANONICAL_NAME, handler=_server_dispatcher)"
    )
    lines.append("        )")

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

    # asyncssh is the transport for the agent → workspace JSON-RPC channel
    # (used by builtin_tools when agent.workspace is declared).
    workspace_pkg = "\nasyncssh>=2.18" if agent.workspace is not None else ""

    # When compaction is enabled, the langchain 1.x ecosystem requires the
    # newer langgraph-prebuilt (which uses APIs added in langgraph 1.0.12).
    # Pin both langchain-core and langgraph to the 1.x line so pip doesn't
    # resolve to a mid-1.0 langgraph that's incompatible with the prebuilt
    # package langchain 1.x pulls in.
    if _compaction_enabled(agent):
        core_pin = "langchain-core>=1.0,<2.0"
        graph_pin = "langgraph>=1.0,<2.0"
        compaction_pkg = "\nlangchain>=1.0,<1.2"
    else:
        core_pin = "langchain-core>=0.3"
        graph_pin = "langgraph>=0.2"
        compaction_pkg = ""

    # vystak + vystak_transport_http + vystak_transport_nats are bundled as
    # source by DockerAgentNode (on PYTHONPATH via COPY . . in the Dockerfile).
    # nats-py is the runtime dependency for NatsTransport; included
    # unconditionally so NATS-deployment containers work without a separate
    # requirements pass.
    return dedent(f"""\
        {core_pin}
        {graph_pin}
        {provider_pkg}
        fastapi>=0.115
        uvicorn>=0.34
        sse-starlette>=2.0
        nats-py>=2.6{checkpoint_pkg}{mcp_pkg}{workspace_pkg}{compaction_pkg}{tool_deps}
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
