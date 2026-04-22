"""tool.* service — discovers and invokes user-defined tools from tools/."""

import asyncio
import importlib.util
import inspect
import sys
from pathlib import Path


def register_tool(server, tools_dir: Path) -> None:
    """Tools are Python files in tools_dir/<name>.py containing a function
    named <name>. Invoked synchronously in-process."""
    tools_root = Path(tools_dir)

    async def invoke(params: dict) -> object:
        name = params["name"]
        args = params.get("args", {})
        tool_path = tools_root / f"{name}.py"
        if not tool_path.exists():
            raise FileNotFoundError(f"Tool {name}.py not found in {tools_root}")

        # Load module
        spec = importlib.util.spec_from_file_location(f"vystak_tool_{name}", tool_path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[f"vystak_tool_{name}"] = module
        spec.loader.exec_module(module)

        fn = getattr(module, name, None)
        if fn is None:
            raise AttributeError(f"Tool {name}.py must define function '{name}'")

        # Call sync or async, returning Python value
        if inspect.iscoroutinefunction(fn):
            return await fn(**args)
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: fn(**args))

    async def list_tools(params: dict) -> list[dict]:
        if not tools_root.exists():
            return []
        result = []
        for entry in sorted(tools_root.iterdir()):
            if entry.suffix != ".py":
                continue
            if entry.stem.startswith("_"):
                continue
            result.append({"name": entry.stem, "path": str(entry.relative_to(tools_root))})
        return result

    server.register("tool.invoke", invoke)
    server.register("tool.list", list_tools)
