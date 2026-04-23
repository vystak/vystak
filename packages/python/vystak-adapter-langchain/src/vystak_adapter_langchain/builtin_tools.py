"""Generates LangChain @tool wrappers for built-in workspace services
(fs.*, exec.*, git.*). User-defined tools (under tool.*) are generated
by the existing tools discovery path."""

# Built-in method specs: (local_function_name, positional_params, streams)
BUILTIN_SPECS: dict[str, tuple[str, list[str], bool]] = {
    "fs.readFile": ("read_file", ["path"], False),
    "fs.writeFile": ("write_file", ["path", "content"], False),
    "fs.appendFile": ("append_file", ["path", "content"], False),
    "fs.deleteFile": ("delete_file", ["path"], False),
    "fs.listDir": ("list_dir", ["path"], False),
    "fs.stat": ("stat_file", ["path"], False),
    "fs.exists": ("exists", ["path"], False),
    "fs.mkdir": ("mkdir", ["path"], False),
    "fs.move": ("move", ["src", "dst"], False),
    "fs.edit": ("edit_file", ["path", "old_str", "new_str"], False),
    "exec.run": ("run", ["cmd"], True),
    "exec.shell": ("shell", ["script"], True),
    "exec.which": ("which", ["name"], False),
    "git.status": ("git_status", [], False),
    "git.log": ("git_log", [], False),
    "git.diff": ("git_diff", [], False),
    "git.add": ("git_add", ["paths"], False),
    "git.commit": ("git_commit", ["message"], False),
    "git.branch": ("git_branch", [], False),
}


def generate_builtin_tools(skill_tool_names: list[str]) -> dict[str, str]:
    """Given the set of tool names referenced by all skills, emit a
    builtin_tools.py file defining @tool-decorated async functions that
    delegate to WorkspaceRpcClient, plus a sibling workspace_client.py
    that is a verbatim copy of the adapter's source module so the generated
    code can import it without needing vystak_adapter_langchain installed
    in the agent container.

    Each generated tool wraps the RPC call in try/except so failures
    surface to the LLM as a plain ``"Error calling <method>: ..."`` string
    (which LangGraph turns into a ToolMessage). That lets the react loop
    retry with corrected arguments instead of the whole graph crashing.

    The emitted builtin_tools.py self-initializes its workspace_client
    from the VYSTAK_WORKSPACE_HOST env var (set by DockerAgentNode), so
    agent.py can just `from builtin_tools import ALL_TOOLS` at import
    time without any bootstrap plumbing elsewhere.
    """
    recognized = [n for n in skill_tool_names if n in BUILTIN_SPECS]

    lines = [
        '"""Auto-generated built-in tool wrappers for workspace services."""',
        "",
        "import os",
        "",
        "from langchain_core.tools import tool",
        "",
        "from workspace_client import WorkspaceRpcClient",
        "",
        "# Auto-initialized from VYSTAK_WORKSPACE_HOST — set by DockerAgentNode.",
        "workspace_client: WorkspaceRpcClient | None = None",
        "_ws_host = os.environ.get('VYSTAK_WORKSPACE_HOST')",
        "if _ws_host:",
        "    workspace_client = WorkspaceRpcClient(",
        "        host=_ws_host,",
        "        port=22,",
        "        username='vystak-agent',",
        "        client_keys=['/vystak/ssh/id_ed25519'],",
        "        known_hosts='/vystak/ssh/known_hosts',",
        "    )",
        "",
        "",
        "def _require_client() -> WorkspaceRpcClient:",
        "    if workspace_client is None:",
        "        raise RuntimeError(",
        "            'WorkspaceRpcClient not initialized: "
        "VYSTAK_WORKSPACE_HOST env var is not set'",
        "        )",
        "    return workspace_client",
        "",
    ]

    for rpc_method in recognized:
        local_name, params, streams = BUILTIN_SPECS[rpc_method]
        sig_params = ", ".join(f"{p}" for p in params) if params else ""
        lines.append("@tool")
        lines.append(f"async def {local_name}({sig_params}) -> object:")
        lines.append(f'    """Workspace {rpc_method}"""')
        lines.append("    try:")
        lines.append("        c = _require_client()")
        if streams:
            lines.append("        result = None")
            if params:
                kwargs = ", ".join(f"{p}={p}" for p in params)
                lines.append(
                    f"        async for item in c.invoke_stream('{rpc_method}', {kwargs}):"
                )
            else:
                lines.append(
                    f"        async for item in c.invoke_stream('{rpc_method}'):"
                )
            lines.append("            result = item")
            lines.append("        return result")
        else:
            if params:
                kwargs = ", ".join(f"{p}={p}" for p in params)
                lines.append(f"        return await c.invoke('{rpc_method}', {kwargs})")
            else:
                lines.append(f"        return await c.invoke('{rpc_method}')")
        lines.append("    except Exception as e:")
        lines.append(
            f"        return f'Error calling {rpc_method}: "
            "{type(e).__name__}: {e}'"
        )
        lines.append("")

    # ALL_TOOLS: flat list of the generated @tool-decorated functions so
    # agent.py can do `from builtin_tools import ALL_TOOLS` in one shot.
    if recognized:
        tool_names = [BUILTIN_SPECS[n][0] for n in recognized]
        lines.append(f"ALL_TOOLS = [{', '.join(tool_names)}]")
    else:
        lines.append("ALL_TOOLS: list = []")
    lines.append("")

    # Bundle the adapter's workspace_client.py verbatim as a sibling file so
    # generated builtin_tools.py can import it by plain module name in the
    # agent container (where vystak_adapter_langchain is not installed).
    from pathlib import Path

    import vystak_adapter_langchain.workspace_client as _ws_client
    ws_client_src = Path(_ws_client.__file__).read_text()

    return {
        "builtin_tools.py": "\n".join(lines),
        "workspace_client.py": ws_client_src,
    }
