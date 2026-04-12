"""LangChain/LangGraph framework adapter."""

from pathlib import Path

from agentstack.providers.base import FrameworkAdapter, GeneratedCode, ValidationError
from agentstack.schema.agent import Agent

from agentstack_adapter_langchain.templates import (
    MODEL_PROVIDERS,
    _get_session_store,
    generate_agent_py,
    generate_requirements_txt,
    generate_server_py,
    generate_store_py,
)
from agentstack_adapter_langchain.tools import (
    discover_tools,
    generate_tools_init,
    get_tool_requirements,
    read_tool_file,
    scaffold_missing_tools,
)


class LangChainAdapter(FrameworkAdapter):
    """Generates LangGraph agent code + FastAPI harness from an Agent schema."""

    def generate(self, agent: Agent, base_dir: Path | None = None) -> GeneratedCode:
        """Generate deployable LangGraph agent code."""
        found_tools: dict[str, Path] = {}
        missing_tools: list[str] = []
        tool_reqs: str | None = None

        if base_dir:
            found_tools, missing_tools = discover_tools(agent, base_dir)

            # Scaffold missing tools on disk (never overwrites existing files)
            if missing_tools:
                scaffold_missing_tools(missing_tools, base_dir)
                # Re-discover — scaffolded tools are now "found"
                found_tools, missing_tools = discover_tools(agent, base_dir)

            tool_reqs = get_tool_requirements(base_dir)
        else:
            seen = set()
            for skill in agent.skills:
                for tool_name in skill.tools:
                    if tool_name not in seen:
                        seen.add(tool_name)
                        missing_tools.append(tool_name)

        files = {
            "agent.py": generate_agent_py(
                agent,
                found_tool_names=list(found_tools.keys()),
                stub_tool_names=missing_tools,
            ),
            "server.py": generate_server_py(agent),
            "requirements.txt": generate_requirements_txt(agent, tool_reqs),
        }

        if found_tools:
            files["tools/__init__.py"] = generate_tools_init(list(found_tools.keys()))
            for name, path in found_tools.items():
                files[f"tools/{name}.py"] = read_tool_file(path, name)

        session_store = _get_session_store(agent)
        if session_store and session_store.engine == "sqlite":
            files["store.py"] = generate_store_py()

        return GeneratedCode(files=files, entrypoint="server.py")

    def validate(self, agent: Agent) -> list[ValidationError]:
        """Validate that the agent can be deployed with LangChain."""
        errors = []
        provider_type = agent.model.provider.type
        if provider_type not in MODEL_PROVIDERS:
            supported = ", ".join(MODEL_PROVIDERS.keys())
            errors.append(
                ValidationError(
                    field="model.provider.type",
                    message=f"Unsupported provider '{provider_type}'. Supported: {supported}",
                )
            )
        return errors
