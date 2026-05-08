"""Subagent tool generation using a2a-sdk's native client.

For each subagent declared in agent.subagents, produces a LangChain @tool
named `ask_<subagent_name>` that talks to the subagent over A2A using the
SDK's `create_client(card_url)`. The card URL is read from the
`VYSTAK_ROUTES_JSON` env var, which the provider populates per-agent.
"""

import contextlib
import json
import os
from typing import Any

from a2a.client import create_client
from a2a.types import Message, Part, Role, SendMessageRequest
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
        card_url = _resolve_card_url(routes.get(name) or {})
        if not card_url:
            continue
        tools.append(_make_tool(name, card_url, _docstring_for(sub)))
    return tools


def _load_routes() -> dict:
    raw = os.environ.get("VYSTAK_ROUTES_JSON", "{}")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def _resolve_card_url(route: dict) -> str | None:
    """Return the agent-card URL for a route entry.

    Prefers the explicit `card_url` field (new shape, emitted by
    vystak-provider-docker after Phase 10). Falls back to deriving the
    card URL from `address` (which still points at the RPC endpoint
    `http://host:port/a2a` in older provider versions).
    """
    card_url = route.get("card_url")
    if card_url:
        return card_url
    address = route.get("address")
    if not address:
        return None
    base = address.rstrip("/").removesuffix("/a2a")
    return f"{base}/.well-known/agent.json"


def _docstring_for(sub: Any) -> str:
    if isinstance(sub, str):
        return f"Ask the {sub} subagent. Pass the user's full question verbatim."
    instructions = getattr(sub, "instructions", "") or ""
    first_line = instructions.split("\n", 1)[0].strip()
    name = getattr(sub, "name", "subagent")
    if first_line:
        return f"Ask the {name} subagent. {first_line}"
    return f"Ask the {name} subagent. Pass the user's full question verbatim."


def _make_tool(subagent_name: str, card_url: str, description: str):
    sanitized = subagent_name.replace("-", "_")
    tool_name = f"ask_{sanitized}"

    @tool(tool_name)
    async def _call(query: str) -> str:
        """{description}"""
        client = None
        try:
            client = await create_client(agent=card_url)
            request = SendMessageRequest(
                message=Message(
                    role=Role.ROLE_USER,
                    parts=[Part(text=query)],
                ),
            )
            collected: list[str] = []
            async for event in client.send_message(request):
                # Each StreamResponse is one of task | message | status_update |
                # artifact_update. The completed task carries the final text
                # in status.message.parts[0].text.
                if event.HasField("task"):
                    msg = event.task.status.message
                    if msg and msg.parts:
                        for p in msg.parts:
                            if p.text:
                                collected.append(p.text)
                elif event.HasField("message"):
                    for p in event.message.parts:
                        if p.text:
                            collected.append(p.text)
            return "".join(collected) or "(no response)"
        except Exception as e:  # noqa: BLE001
            return f"[{subagent_name} error] {e}"
        finally:
            close = getattr(client, "close", None) if client is not None else None
            if close is not None:
                # Close errors must not mask the call result.
                with contextlib.suppress(Exception):
                    await close()

    _call.__doc__ = description
    return _call
