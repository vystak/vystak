"""Subagent tool generation.

For each subagent declared in agent.subagents, produces a LangChain @tool
named `ask_<subagent_name>` that POSTs an A2A `tasks/send` request to the
subagent's address (read from the `VYSTAK_ROUTES_JSON` env var).
"""

import json
import os
import uuid
from typing import Any

import httpx
from langchain_core.tools import tool


def build_subagent_tools(agent: Any) -> list[Any]:
    """Return LangChain @tool functions, one per declared subagent."""
    subagents = getattr(agent, "subagents", []) or []
    if not subagents:
        return []

    routes = _load_routes()

    tools: list[Any] = []
    for sub in subagents:
        name = sub if isinstance(sub, str) else getattr(sub, "name", None)
        if not name:
            continue
        url = (routes.get(name) or {}).get("address")
        if not url:
            continue
        tools.append(_make_tool(name, url, _docstring_for(sub)))
    return tools


def _load_routes() -> dict:
    raw = os.environ.get("VYSTAK_ROUTES_JSON", "{}")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def _docstring_for(sub: Any) -> str:
    if isinstance(sub, str):
        return f"Ask the {sub} subagent. Pass the user's full question verbatim."
    instructions = getattr(sub, "instructions", "") or ""
    first_line = instructions.split("\n", 1)[0].strip()
    name = getattr(sub, "name", "subagent")
    if first_line:
        return f"Ask the {name} subagent. {first_line}"
    return f"Ask the {name} subagent. Pass the user's full question verbatim."


def _make_tool(subagent_name: str, url: str, description: str):
    sanitized = subagent_name.replace("-", "_")
    tool_name = f"ask_{sanitized}"

    @tool(tool_name)
    async def _call(query: str) -> str:
        """{description}"""
        rpc_id = uuid.uuid4().hex[:12]
        payload = {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "method": "tasks/send",
            "params": {
                "id": f"sub-{rpc_id}",
                "message": {
                    "role": "user",
                    "parts": [{"text": query}],
                },
            },
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, json=payload)
        resp.raise_for_status()
        body = resp.json()
        if "error" in body:
            return f"[{subagent_name} error] {body['error'].get('message', 'unknown')}"

        result = body.get("result") or {}
        message = (result.get("status") or {}).get("message") or {}
        parts = message.get("parts") or []
        out: list[str] = []
        for p in parts:
            text = p.get("text") if isinstance(p, dict) else None
            if isinstance(text, str):
                out.append(text)
        return "".join(out) or "(no response)"

    _call.__doc__ = description
    return _call
