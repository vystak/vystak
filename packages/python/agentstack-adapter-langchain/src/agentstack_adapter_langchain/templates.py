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

    # Build the agent code
    lines = []
    lines.append(f'"""AgentStack generated agent: {agent.name}."""\n')
    lines.append(f"{model_import}")

    if tool_names:
        lines.append("from langchain_core.tools import tool")

    lines.append("from langgraph.checkpoint.memory import MemorySaver")
    lines.append("from langgraph.prebuilt import create_react_agent")
    lines.append("")
    lines.append("")
    lines.append(f"# Model")
    lines.append(f"model = {model_class}({model_kwargs_str})")
    lines.append("")
    lines.append("# Session memory")
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
        lines.append(
            f"agent = create_react_agent(model, [{tools_list}], checkpointer=memory, prompt=system_prompt)"
        )
    else:
        lines.append(f"agent = create_react_agent(model, [{tools_list}], checkpointer=memory)")

    lines.append("")

    return "\n".join(lines)


def generate_server_py(agent: Agent) -> str:
    """Generate a FastAPI harness server file."""
    return dedent(f"""\
        \"\"\"AgentStack harness server for {agent.name}.\"\"\"

        import asyncio
        import json
        import os
        import uuid

        from fastapi import FastAPI
        from pydantic import BaseModel
        from sse_starlette.sse import EventSourceResponse

        from agent import agent

        app = FastAPI(title="{agent.name}")

        AGENT_NAME = os.environ.get("AGENTSTACK_AGENT_NAME", "{agent.name}")
        HOST = os.environ.get("HOST", "0.0.0.0")
        PORT = int(os.environ.get("PORT", "8000"))


        class InvokeRequest(BaseModel):
            message: str
            session_id: str | None = None


        class InvokeResponse(BaseModel):
            response: str
            session_id: str


        @app.get("/health")
        async def health():
            return {{"status": "ok", "agent": AGENT_NAME, "version": "0.1.0"}}


        @app.post("/invoke", response_model=InvokeResponse)
        async def invoke(request: InvokeRequest):
            session_id = request.session_id or str(uuid.uuid4())
            result = await agent.ainvoke(
                {{"messages": [("user", request.message)]}},
                config={{"configurable": {{"thread_id": session_id}}}},
            )
            content = result["messages"][-1].content
            if isinstance(content, list):
                response_text = "".join(
                    block.get("text", "") if isinstance(block, dict) else str(block)
                    for block in content
                )
            else:
                response_text = str(content)
            return InvokeResponse(response=response_text, session_id=session_id)


        @app.post("/stream")
        async def stream(request: InvokeRequest):
            session_id = request.session_id or str(uuid.uuid4())

            async def event_generator():
                async for event in agent.astream_events(
                    {{"messages": [("user", request.message)]}},
                    config={{"configurable": {{"thread_id": session_id}}}},
                    version="v2",
                ):
                    if event["event"] == "on_chat_model_stream":
                        token = event["data"]["chunk"].content
                        if token:
                            yield {{"data": json.dumps({{"token": token, "session_id": session_id}})}}
                yield {{"data": json.dumps({{"done": True, "session_id": session_id}})}}

            return EventSourceResponse(event_generator())


        if __name__ == "__main__":
            import uvicorn

            uvicorn.run(app, host=HOST, port=PORT)
    """)


def generate_requirements_txt(agent: Agent) -> str:
    """Generate a requirements.txt based on the agent's model provider."""
    provider_type = agent.model.provider.type
    provider_pkg = PROVIDER_PACKAGES.get(provider_type, PROVIDER_PACKAGES["anthropic"])

    return dedent(f"""\
        langchain-core>=0.3
        langgraph>=0.2
        {provider_pkg}
        fastapi>=0.115
        uvicorn>=0.34
        sse-starlette>=2.0
    """)
