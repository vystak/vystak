"""Subagent tool generation using a2a-sdk's native client.

For each subagent declared in agent.subagents, produces a LangChain @tool
named `ask_<subagent_name>` that talks to the subagent over A2A using the
SDK's `create_client(card_url)`. The card URL is read from the
`VYSTAK_ROUTES_JSON` env var, which the provider populates per-agent.
"""

import contextlib
import json
import os
import uuid
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
        target = _resolve_target(routes.get(name) or {})
        if target is None:
            continue
        base_url, card_path = target
        tools.append(_make_tool(name, base_url, card_path, _docstring_for(sub)))
    return tools


def _load_routes() -> dict:
    raw = os.environ.get("VYSTAK_ROUTES_JSON", "{}")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def _resolve_target(route: dict) -> tuple[str, str] | None:
    """Return ``(base_url, relative_card_path)`` for a route entry.

    The a2a-sdk's ``create_client(url)`` treats *url* as the agent's
    *base URL* and appends a relative card path (default
    ``/.well-known/agent-card.json``). We split our route entry into
    those two halves so the SDK's resolver hits the right URL — our
    deployed agents serve the card at ``/.well-known/agent.json`` (with
    the dot, kept for back-compat).

    Prefers the explicit ``card_url`` field; falls back to deriving from
    ``address`` (which points at the RPC endpoint).
    """
    card_url = route.get("card_url")
    if not card_url:
        address = route.get("address")
        if not address:
            return None
        base = address.rstrip("/").removesuffix("/a2a")
        card_url = f"{base}/.well-known/agent.json"

    # Split full card URL into (scheme://host:port, /well-known/...).
    from urllib.parse import urlparse

    parsed = urlparse(card_url)
    if not parsed.scheme or not parsed.netloc:
        return None
    base_url = f"{parsed.scheme}://{parsed.netloc}"
    relative_path = parsed.path or "/.well-known/agent.json"
    return base_url, relative_path


def _docstring_for(sub: Any) -> str:
    if isinstance(sub, str):
        return f"Ask the {sub} subagent. Pass the user's full question verbatim."
    instructions = getattr(sub, "instructions", "") or ""
    first_line = instructions.split("\n", 1)[0].strip()
    name = getattr(sub, "name", "subagent")
    if first_line:
        return f"Ask the {name} subagent. {first_line}"
    return f"Ask the {name} subagent. Pass the user's full question verbatim."


def _make_tool(subagent_name: str, base_url: str, card_path: str, description: str):
    sanitized = subagent_name.replace("-", "_")
    tool_name = f"ask_{sanitized}"

    @tool(tool_name)
    async def _call(query: str) -> str:
        """{description}"""
        client = None
        try:
            client = await create_client(agent=base_url, relative_card_path=card_path)
            request = SendMessageRequest(
                message=Message(
                    role=Role.ROLE_USER,
                    # message_id is required by the v0.3 wire conversion;
                    # an empty string triggers `Validation failed`.
                    message_id=uuid.uuid4().hex,
                    parts=[Part(text=query)],
                ),
            )
            # Each StreamResponse is one of: task | message |
            # status_update | artifact_update. The completion (state=COMPLETED)
            # arrives as a status_update carrying message.parts[]. We capture
            # only the LAST status_update message — earlier ones may be
            # transient working-state pings without a message.
            final_text_parts: list[str] = []
            async for event in client.send_message(request):
                kind = event.WhichOneof("payload")
                if kind == "task":
                    msg = event.task.status.message
                    if msg and msg.parts:
                        final_text_parts = [p.text for p in msg.parts if p.text]
                elif kind == "status_update":
                    msg = event.status_update.status.message
                    if msg and msg.parts:
                        # Replace, not append — last completed status wins.
                        final_text_parts = [p.text for p in msg.parts if p.text]
                elif kind == "message":
                    final_text_parts = [p.text for p in event.message.parts if p.text]
            return "".join(final_text_parts) or "(no response)"
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
