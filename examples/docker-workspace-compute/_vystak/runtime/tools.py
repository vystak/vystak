"""Discover and import user-defined @tool functions from tools/."""

import importlib.util
import sys
from pathlib import Path
from typing import Any


def load_user_tools(agent: Any, tools_dir: Path) -> list[Any]:
    if not tools_dir.exists() or not tools_dir.is_dir():
        return []

    needed: set[str] = set()
    for skill in getattr(agent, "skills", []):
        needed.update(skill.tools)

    found: list[Any] = []
    for name in needed:
        candidate = tools_dir / f"{name}.py"
        if not candidate.exists():
            continue
        module = _load_module(candidate, f"_vystak_user_tools.{name}")
        fn = getattr(module, name, None)
        if fn is not None:
            found.append(fn)
    return found


def _load_module(path: Path, qualified_name: str) -> Any:
    spec = importlib.util.spec_from_file_location(qualified_name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[qualified_name] = module
    spec.loader.exec_module(module)
    return module
