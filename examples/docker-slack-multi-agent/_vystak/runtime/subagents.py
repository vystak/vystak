"""Subagent tool generation using a2a-sdk's native client.

For each subagent declared in agent.subagents, produces a LangChain @tool
named `ask_<subagent_name>` that talks to the subagent over A2A using the
SDK's `create_client(card_url)`. The card URL is read from the
`VYSTAK_ROUTES_JSON` env var, which the provider populates per-agent.

Tool descriptions are **card-driven**: at boot, each subagent's
`/.well-known/agent.json` is fetched and its `description` + `skills` are
folded into the @tool's docstring. The LLM sees the peer's own
self-description rather than vystak boilerplate, so routing decisions key
off accurate, agent-authored guidance. If a peer is unreachable at boot
(slow startup / DNS race), the tool falls back to local boilerplate
derived from the parent agent's `subagents` declaration.
"""

import contextlib
import json
import logging
import os
import time
import uuid
from typing import Any

import httpx
from a2a.client import create_client
from a2a.types import Message, Part, Role, SendMessageRequest
from langchain_core.tools import tool

logger = logging.getLogger("vystak.runtime.subagents")


def build_subagent_tools(agent: Any) -> list[Any]:
    """Return LangChain @tool functions, one per declared subagent.

    Performs a synchronous, best-effort GET on each peer's agent card so the
    tool's docstring carries the peer's own description. Total bootstrap
    cost is bounded — ~3 retries per peer with short timeouts; on failure
    we keep the local boilerplate description and proceed.
    """
    subagents = getattr(agent, "subagents", []) or []
    if not subagents:
        return []

    routes = _load_routes()

    tools: list[Any] = []
    with httpx.Client(timeout=2.0) as client:
        for sub in subagents:
            name = sub if isinstance(sub, str) else getattr(sub, "name", None)
            if not name:
                continue
            target = _resolve_target(routes.get(name) or {})
            if target is None:
                continue
            base_url, card_path = target
            card = _fetch_card_with_retries(client, base_url + card_path)
            description = _description_from_card(card) if card else _docstring_for(sub)
            tools.append(_make_tool(name, base_url, card_path, description))
    return tools


def _fetch_card_with_retries(
    client: httpx.Client,
    url: str,
    *,
    max_attempts: int = 3,
    base_backoff: float = 0.5,
) -> dict | None:
    """GET an agent card with bounded retry. Returns None on all failures.

    Race window: peers may still be booting when this fires. Three attempts
    with exponential backoff (~0.5s, 1.0s, 2.0s) covers the typical Docker
    container start-up + uvicorn ready window.
    """
    last_err: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            resp = client.get(url)
            resp.raise_for_status()
            return resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            last_err = exc
            if attempt < max_attempts:
                time.sleep(base_backoff * (2 ** (attempt - 1)))
    logger.warning(
        "subagent card fetch failed after %d attempts: %s (%s)",
        max_attempts, url, last_err,
    )
    return None


def _description_from_card(card: dict) -> str:
    """Build a tool docstring from an agent card.

    Pattern: `<name> — <description>. Skills: <skill1>: <s1desc>; ...`.
    Falls back gracefully on missing fields.
    """
    name = card.get("name") or "subagent"
    desc = (card.get("description") or "").strip()
    skills = card.get("skills") or []

    head = f"{name}"
    if desc:
        head = f"{name} — {desc.splitlines()[0].strip()}"

    skill_strs: list[str] = []
    for s in skills:
        if not isinstance(s, dict):
            continue
        s_name = s.get("name") or s.get("id") or ""
        s_desc = (s.get("description") or "").strip()
        if s_name and s_desc:
            skill_strs.append(f"{s_name}: {s_desc}")
        elif s_name:
            skill_strs.append(s_name)

    if skill_strs:
        return f"{head}. Skills: {'; '.join(skill_strs)}"
    return head


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

    @tool(tool_name, description=description)
    async def _call(query: str) -> str:
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

    return _call
