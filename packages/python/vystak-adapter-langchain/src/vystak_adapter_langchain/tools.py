"""Tool file discovery, reading, and packaging."""

import ast as python_ast
from pathlib import Path

from vystak.schema.agent import Agent


def discover_tools(agent: Agent, base_dir: Path) -> tuple[dict[str, Path], list[str]]:
    """Discover which tools have real implementations on disk.

    Returns:
        found: dict of tool_name -> file path
        missing: list of tool names without implementations
    """
    tools_dir = base_dir / "tools"
    found: dict[str, Path] = {}
    missing: list[str] = []

    seen = set()
    all_tools = []
    for skill in agent.skills:
        for tool_name in skill.tools:
            if tool_name not in seen:
                seen.add(tool_name)
                all_tools.append(tool_name)

    for tool_name in all_tools:
        tool_path = tools_dir / f"{tool_name}.py"
        if tool_path.exists():
            found[tool_name] = tool_path
        else:
            missing.append(tool_name)

    return found, missing


def read_tool_file(path: Path, expected_name: str) -> str:
    """Read a tool file and validate it contains the expected function."""
    if not path.exists():
        raise FileNotFoundError(f"Tool file not found: {path}")

    content = path.read_text()
    tree = python_ast.parse(content)
    function_names = [
        node.name for node in python_ast.walk(tree)
        if isinstance(node, (python_ast.FunctionDef, python_ast.AsyncFunctionDef))
    ]

    if expected_name not in function_names:
        raise ValueError(
            f"Tool file {path} does not contain a function named '{expected_name}'. "
            f"Found: {function_names}"
        )

    return content


def generate_tools_init(tool_names: list[str]) -> str:
    """Generate tools/__init__.py that imports and wraps tools with @tool."""
    lines = []
    lines.append('"""Auto-generated tool exports."""')
    lines.append("")

    if not tool_names:
        lines.append("")
        return "\n".join(lines)

    lines.append("from langchain_core.tools import tool")
    lines.append("")

    for name in tool_names:
        lines.append(f"from tools.{name} import {name}")

    lines.append("")

    for name in tool_names:
        lines.append(f"{name} = tool({name})")

    lines.append("")

    return "\n".join(lines)


def scaffold_missing_tools(missing_tools: list[str], base_dir: Path) -> list[str]:
    """Scaffold tool files for missing tools. Never overwrites existing files.

    Returns list of tool names that were scaffolded.
    """
    if not missing_tools:
        return []

    tools_dir = base_dir / "tools"
    tools_dir.mkdir(exist_ok=True)

    scaffolded = []
    for tool_name in missing_tools:
        tool_path = tools_dir / f"{tool_name}.py"
        if tool_path.exists():
            continue

        docstring = tool_name.replace("_", " ").title() + "."
        content = (
            f"def {tool_name}(input: str) -> str:\n"
            f'    """{docstring}"""\n'
            f"    # TODO: implement this tool\n"
            f'    return f"{tool_name} called with {{input}}"\n'
        )
        tool_path.write_text(content)
        scaffolded.append(tool_name)

    return scaffolded


def get_tool_requirements(base_dir: Path) -> str | None:
    """Read tools/requirements.txt if it exists."""
    req_path = base_dir / "tools" / "requirements.txt"
    if req_path.exists():
        return req_path.read_text().strip()
    return None
