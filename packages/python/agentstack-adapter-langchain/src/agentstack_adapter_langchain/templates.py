"""Code generation templates for LangChain/LangGraph agents."""

from textwrap import dedent

from agentstack.schema.agent import Agent

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


def _generate_tool_stubs(agent: Agent) -> str:
    """Generate @tool stub functions from agent skills."""
    tools = []
    seen = set()
    for skill in agent.skills:
        for tool_name in skill.tools:
            if tool_name in seen:
                continue
            seen.add(tool_name)
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
    """Collect system prompt from agent instructions and skill prompts."""
    prompts = []
    if agent.instructions:
        prompts.append(agent.instructions)
    for skill in agent.skills:
        if skill.prompt:
            prompts.append(skill.prompt)
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


def generate_agent_py(agent: Agent) -> str:
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

    # Build tool stubs
    tool_stubs = _generate_tool_stubs(agent)

    # Collect tool names
    tool_names = []
    seen = set()
    for skill in agent.skills:
        for tool_name in skill.tools:
            if tool_name not in seen:
                seen.add(tool_name)
                tool_names.append(tool_name)

    tools_list = ", ".join(tool_names) if tool_names else ""

    # System prompt
    system_prompt = _collect_system_prompt(agent)

    # Checkpointer based on resources
    session_store = _get_session_store(agent)

    # Build the agent code
    lines = []
    lines.append(f'"""AgentStack generated agent: {agent.name}."""\n')
    lines.append(f"{model_import}")

    if tool_names:
        lines.append("from langchain_core.tools import tool")

    if session_store and session_store.engine == "postgres":
        lines.append("import os")
        lines.append("")
        lines.append("from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver")
    elif session_store and session_store.engine == "sqlite":
        lines.append("from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver")
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
    elif session_store and session_store.engine == "sqlite":
        lines.append("# Session persistence (SQLite) — initialized at startup via lifespan")
        lines.append(f'DB_URI = "/data/{session_store.name}.db"')
        lines.append("memory = None  # set during server lifespan")
    else:
        lines.append("# Session memory (in-memory, not persisted)")
        lines.append("memory = MemorySaver()")

    lines.append("")

    if tool_stubs:
        lines.append("")
        lines.append("# Tools")
        lines.append(tool_stubs)

    lines.append("")
    lines.append("# Agent")

    if system_prompt:
        escaped_prompt = system_prompt.replace('"""', '\\"\\"\\"')
        lines.append(f'system_prompt = """{escaped_prompt}"""')
        lines.append("")

    # For persistent checkpointers, create agent via function (memory set at startup)
    if session_store and session_store.engine in ("postgres", "sqlite"):
        if system_prompt:
            lines.append(f"def create_agent(checkpointer):")
            lines.append(f"    return create_react_agent(model, [{tools_list}], checkpointer=checkpointer, prompt=system_prompt)")
        else:
            lines.append(f"def create_agent(checkpointer):")
            lines.append(f"    return create_react_agent(model, [{tools_list}], checkpointer=checkpointer)")
        lines.append("")
        lines.append("agent = None  # created during server lifespan")
    else:
        if system_prompt:
            lines.append(
                f"agent = create_react_agent(model, [{tools_list}], checkpointer=memory, prompt=system_prompt)"
            )
        else:
            lines.append(f"agent = create_react_agent(model, [{tools_list}], checkpointer=memory)")

    lines.append("")

    return "\n".join(lines)


def generate_server_py(agent: Agent) -> str:
    """Generate a FastAPI harness server file."""
    session_store = _get_session_store(agent)
    uses_persistent = session_store and session_store.engine in ("postgres", "sqlite")

    if uses_persistent:
        saver_class = "AsyncPostgresSaver" if session_store.engine == "postgres" else "AsyncSqliteSaver"
        saver_module = "postgres.aio" if session_store.engine == "postgres" else "sqlite.aio"
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
    lines.append("from fastapi import FastAPI")
    lines.append("from pydantic import BaseModel")
    lines.append("from sse_starlette.sse import EventSourceResponse")
    lines.append("")

    if uses_persistent:
        lines.append("from contextlib import asynccontextmanager")
        lines.append(f"from langgraph.checkpoint.{saver_module} import {saver_class}")
        lines.append("")
        lines.append("from agent import create_agent, DB_URI")
        lines.append("")
        lines.append("")
        lines.append("_agent = None")
        lines.append("")
        lines.append("")
        lines.append("@asynccontextmanager")
        lines.append("async def lifespan(app):")
        lines.append("    global _agent")
        lines.append(f"    async with {saver_class}.from_conn_string(DB_URI) as checkpointer:")
        lines.append("        await checkpointer.setup()")
        lines.append("        _agent = create_agent(checkpointer)")
        lines.append("        yield")
        lines.append("")
        lines.append("")
        lines.append(f'app = FastAPI(title="{agent.name}", lifespan=lifespan)')
    else:
        lines.append("from agent import agent")
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
    lines.append("")
    lines.append("")
    lines.append("class InvokeResponse(BaseModel):")
    lines.append("    response: str")
    lines.append("    session_id: str")
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
    lines.append("    return InvokeResponse(response=response_text, session_id=session_id)")
    lines.append("")
    lines.append("")
    lines.append('@app.post("/stream")')
    lines.append("async def stream(request: InvokeRequest):")
    lines.append("    session_id = request.session_id or str(uuid.uuid4())")
    lines.append("")
    lines.append("    async def event_generator():")
    lines.append(f"        async for event in {agent_ref}.astream_events(")
    lines.append('            {"messages": [("user", request.message)]},')
    lines.append('            config={"configurable": {"thread_id": session_id}},')
    lines.append('            version="v2",')
    lines.append("        ):")
    lines.append('            if event["event"] == "on_chat_model_stream":')
    lines.append('                token = event["data"]["chunk"].content')
    lines.append("                if token:")
    lines.append('                    yield {"data": json.dumps({"token": token, "session_id": session_id})}')
    lines.append('        yield {"data": json.dumps({"done": True, "session_id": session_id})}')
    lines.append("")
    lines.append("    return EventSourceResponse(event_generator())")
    lines.append("")
    lines.append("")
    lines.append('if __name__ == "__main__":')
    lines.append("    import uvicorn")
    lines.append("")
    lines.append("    uvicorn.run(app, host=HOST, port=PORT)")
    lines.append("")

    return "\n".join(lines)


def generate_requirements_txt(agent: Agent) -> str:
    """Generate a requirements.txt based on the agent's model provider."""
    provider_type = agent.model.provider.type
    provider_pkg = PROVIDER_PACKAGES.get(provider_type, PROVIDER_PACKAGES["anthropic"])

    session_store = _get_session_store(agent)
    checkpoint_pkg = ""
    if session_store and session_store.engine == "postgres":
        checkpoint_pkg = "\nlanggraph-checkpoint-postgres>=2.0\npsycopg[binary]>=3.0"
    elif session_store and session_store.engine == "sqlite":
        checkpoint_pkg = "\nlanggraph-checkpoint-sqlite>=2.0"

    return dedent(f"""\
        langchain-core>=0.3
        langgraph>=0.2
        {provider_pkg}
        fastapi>=0.115
        uvicorn>=0.34
        sse-starlette>=2.0{checkpoint_pkg}
    """)
