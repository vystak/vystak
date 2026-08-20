"""Human-in-the-loop approval gate for skill tools.

A tool named in a skill's `needs_approval` is wrapped so the run parks
(via LangGraph interrupt()) BEFORE the tool executes. The resume value is
the decision: {"approved": bool, "decided_by": str, "note": str | null}.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from langchain_core.tools import StructuredTool
from langchain_core.tools import tool as _tool_decorator
from langgraph.types import interrupt


def load_approval_map(agent: Any, project_root: Path | str) -> dict[str, str]:
    """tool name -> skill name for every gated tool.

    Prefers the typed `Skill.needs_approval` field; falls back to the raw
    bundled agent.json because a pip-installed `vystak` older than the
    field silently drops it (pydantic extra="ignore").
    """
    out: dict[str, str] = {}
    for skill in getattr(agent, "skills", None) or []:
        for tool_name in getattr(skill, "needs_approval", None) or []:
            out[tool_name] = skill.name
    if out:
        return out
    bundled = Path(project_root) / "agent.json"
    if bundled.exists():
        try:
            raw = json.loads(bundled.read_text())
        except (OSError, json.JSONDecodeError):
            return out
        for skill in raw.get("skills") or []:
            for tool_name in skill.get("needs_approval") or []:
                out[tool_name] = skill.get("name", "")
    return out


def _denied_result(decision: dict) -> str:
    who = decision.get("decided_by") or "unknown"
    note = decision.get("note") or "no reason given"
    return f"Denied by {who}: {note}"


def _dispatch_name(t: Any) -> str | None:
    """The name LangGraph will register `t` under once it's actually a
    tool. LangChain tool objects (StructuredTool, `@tool`-decorated) carry
    `.name`. Plain callables from `load_user_tools` (raw `async def`
    functions loaded straight from `tools/*.py` -- the common case for
    every `Skill.tools` entry) don't; `create_react_agent` coerces those
    into tools internally using the function's `__name__`, so that's the
    name to match against here too. Without this fallback, every plain
    `tools/*.py` function silently passes the gate unwrapped -- verified
    live: `getattr(fn, "name", None)` is always `None` for a bare function,
    so it never matched an entry in `approval_map` and the gate was a
    no-op for exactly the tools the docker-approvals example demonstrates.
    """
    name = getattr(t, "name", None)
    if name is not None:
        return name
    return getattr(t, "__name__", None)


def wrap_tools_with_approval(tools: list, approval_map: dict[str, str]) -> list:
    if not approval_map:
        return list(tools)

    wrapped = []
    for t in tools:
        name = _dispatch_name(t)
        if name not in approval_map:
            wrapped.append(t)
            continue
        # Coerce a plain callable into a real LangChain tool before
        # wrapping -- `_wrap_one` reads `.name` / `.description` /
        # `.args_schema` / `.ainvoke`, none of which a bare function has.
        original = t if hasattr(t, "name") else _tool_decorator(t)
        wrapped.append(_wrap_one(original, approval_map[name]))
    return wrapped


def _wrap_one(original: Any, skill_name: str) -> StructuredTool:
    async def _gated(**kwargs: Any) -> Any:
        decision = interrupt({
            "kind": "tool_approval",
            "tool": original.name,
            "args": kwargs,
            "skill": skill_name,
        })
        if isinstance(decision, dict) and decision.get("approved"):
            return await original.ainvoke(kwargs)
        return _denied_result(decision if isinstance(decision, dict) else {})

    return StructuredTool.from_function(
        coroutine=_gated,
        name=original.name,
        description=original.description,
        args_schema=original.args_schema,
    )
