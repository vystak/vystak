"""LangChain/LangGraph framework adapter."""

from pathlib import Path

from vystak.providers.base import FrameworkAdapter, GeneratedCode, ValidationError
from vystak.schema.agent import Agent

from vystak_adapter_langchain.builtin_tools import BUILTIN_SPECS, generate_builtin_tools
from vystak_adapter_langchain.templates import (
    MODEL_PROVIDERS,
    _get_session_store,
    generate_agent_py,
    generate_requirements_txt,
    generate_server_py,
    generate_store_py,
)
from vystak_adapter_langchain.tools import (
    discover_tools,
    generate_tools_init,
    get_tool_requirements,
    read_tool_file,
    scaffold_missing_tools,
)

_WORKSPACE_BOOTSTRAP = (
    "\n\n"
    "# --- Workspace bootstrap (Spec 1) ---\n"
    "import os\n"
    "from vystak_adapter_langchain.workspace_client import WorkspaceRpcClient\n"
    "from vystak_adapter_langchain import builtin_tools as _bt\n"
    "\n"
    "_ws_host = os.environ.get('VYSTAK_WORKSPACE_HOST')\n"
    "if _ws_host:\n"
    "    _bt.workspace_client = WorkspaceRpcClient(\n"
    "        host=_ws_host,\n"
    "        port=22,\n"
    "        username='vystak-agent',\n"
    "        client_keys=['/vystak/ssh/id_ed25519'],\n"
    "        known_hosts='/vystak/ssh/known_hosts',\n"
    "    )\n"
    "    # connect() is lazy — WorkspaceRpcClient.invoke() calls it on first\n"
    "    # RPC. This avoids running an event loop at module import time\n"
    "    # (asyncio.get_event_loop() is deprecated on Python 3.12+ and removed\n"
    "    # on 3.14 when there is no running loop).\n"
    "# --- end Workspace bootstrap ---\n"
)


class LangChainAdapter(FrameworkAdapter):
    """Generates LangGraph agent code + FastAPI harness from an Agent schema."""

    def generate(self, agent: Agent, base_dir: Path | None = None) -> GeneratedCode:
        """Generate deployable LangGraph agent code."""
        found_tools: dict[str, Path] = {}
        missing_tools: list[str] = []
        tool_reqs: str | None = None

        # When a workspace is declared, built-in tool names (fs.*, exec.*, git.*)
        # are handled by builtin_tools.py rather than by user-defined tool files.
        # They must be excluded from the discovery/scaffolding path, since names
        # containing '.' aren't valid Python identifiers for user-tool files.
        has_workspace = agent.workspace is not None

        if base_dir:
            found_tools, missing_tools = discover_tools(agent, base_dir)
            if has_workspace:
                missing_tools = [m for m in missing_tools if m not in BUILTIN_SPECS]
                found_tools = {k: v for k, v in found_tools.items() if k not in BUILTIN_SPECS}

            # Scaffold missing tools on disk (never overwrites existing files)
            if missing_tools:
                scaffold_missing_tools(missing_tools, base_dir)
                # Re-discover — scaffolded tools are now "found"
                found_tools, missing_tools = discover_tools(agent, base_dir)
                if has_workspace:
                    missing_tools = [m for m in missing_tools if m not in BUILTIN_SPECS]
                    found_tools = {
                        k: v for k, v in found_tools.items() if k not in BUILTIN_SPECS
                    }

            tool_reqs = get_tool_requirements(base_dir)
        else:
            seen = set()
            for skill in agent.skills:
                for tool_name in skill.tools:
                    if tool_name not in seen:
                        seen.add(tool_name)
                        missing_tools.append(tool_name)
            if has_workspace:
                missing_tools = [m for m in missing_tools if m not in BUILTIN_SPECS]

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

        # Workspace: emit built-in tool wrappers and inject bootstrap into server.py.
        if has_workspace:
            all_skill_tools: list[str] = []
            for skill in agent.skills:
                all_skill_tools.extend(skill.tools)
            builtin_files = generate_builtin_tools(skill_tool_names=all_skill_tools)
            files.update(builtin_files)
            files["server.py"] = files["server.py"] + _WORKSPACE_BOOTSTRAP

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
