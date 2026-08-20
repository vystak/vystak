"""Subagent tool generation using a2a-sdk's native client.

For each subagent declared in agent.subagents, produces a LangChain @tool
named `ask_<subagent_name>` that talks to the subagent over A2A.

Two transport paths share this module:

* **HTTP** (default) — uses a2a-sdk's `create_client(card_url)`. Tool
  descriptions are card-driven: at boot, each subagent's
  `/.well-known/agent.json` is fetched and its `description` + `skills`
  are folded into the @tool's docstring. The LLM sees the peer's own
  self-description.

* **NATS** (when `VYSTAK_TRANSPORT_TYPE=nats`) — publishes JSON-RPC
  envelopes on the peer's NATS subject (read from
  `routes[<peer>].address`) and parses the reply. Cards are not
  discoverable over NATS, so descriptions fall back to the local
  boilerplate derived from `agent.subagents`.

The route map is read from the `VYSTAK_ROUTES_JSON` env var, which the
provider populates per-agent.
"""

import contextlib
import json
import logging
import os
import time
import uuid
from typing import Any

import httpx
from a2a.client import ClientConfig, create_client
from a2a.types import Message, Part, Role, SendMessageRequest, TaskState
from langchain_core.tools import tool

logger = logging.getLogger("vystak.runtime.subagents")


def _approval_pending_reply(marker: Any) -> str | None:
    """If *marker* is the `{"kind": "approval_pending", ...}` JSON a gated
    peer's `input-required` task end carries as its message text (see
    `a2a_native/executor.py`'s interrupt handling, and the same detection
    idiom in `vystak-channel-runtime/agent_client.py`'s
    `_reply_from_jsonrpc`), return a friendly string for the calling LLM
    instead of feeding it the raw marker JSON — an orchestrator has no way
    to act on `{"kind": "approval_pending", "payload": {...}}` and would
    otherwise either hallucinate a response or retry pointlessly. Returns
    None when *marker* isn't that shape, so the caller falls through to
    its normal text handling."""
    if not isinstance(marker, dict) or marker.get("kind") != "approval_pending":
        return None
    payload = marker.get("payload") or {}
    tool_name = payload.get("tool") or "a tool"
    return (
        f"The sub-agent is waiting for human approval of tool '{tool_name}' "
        "and cannot proceed. A human must approve it in the panel or Slack."
    )


def build_subagent_tools(agent: Any) -> list[Any]:
    """Return LangChain @tool functions, one per declared subagent.

    Dispatches to the HTTP or NATS implementation based on
    ``VYSTAK_TRANSPORT_TYPE``.
    """
    transport_type = os.environ.get("VYSTAK_TRANSPORT_TYPE", "http")
    if transport_type == "nats":
        return _build_nats_subagent_tools(agent)
    return _build_http_subagent_tools(agent)


def _build_http_subagent_tools(agent: Any) -> list[Any]:
    """HTTP path — card-driven descriptions via /.well-known/agent.json.

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


def _build_nats_subagent_tools(agent: Any) -> list[Any]:
    """NATS path — publish JSON-RPC envelopes on peer subjects.

    Cards are not discoverable over NATS, so tool descriptions fall back
    to the local boilerplate derived from `agent.subagents`. The
    address field in each route entry IS the NATS subject (no scheme,
    no port — e.g. `vystak.default.agents.weather.tasks`).
    """
    subagents = getattr(agent, "subagents", []) or []
    if not subagents:
        return []

    nats_url = os.environ.get("VYSTAK_NATS_URL")
    if not nats_url:
        logger.warning(
            "VYSTAK_TRANSPORT_TYPE=nats but VYSTAK_NATS_URL unset; "
            "subagent tools will be skipped",
        )
        return []

    routes = _load_routes()
    tools: list[Any] = []
    for sub in subagents:
        name = sub if isinstance(sub, str) else getattr(sub, "name", None)
        if not name:
            continue
        subject = (routes.get(name) or {}).get("address")
        if not subject:
            logger.warning("subagent %s has no NATS address in routes; skipping", name)
            continue
        description = _docstring_for(sub)
        tools.append(_make_nats_tool(name, subject, nats_url, description))
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
        http_client = None
        try:
            # httpx's ~5s default read timeout kills delegation to slow
            # children (MCP lookups, long tool chains). Match the transport
            # client's 120s ceiling instead.
            http_client = httpx.AsyncClient(timeout=httpx.Timeout(120.0))
            client = await create_client(
                agent=base_url,
                client_config=ClientConfig(httpx_client=http_client),
                relative_card_path=card_path,
            )
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
            last_state: int | None = None
            async for event in client.send_message(request):
                kind = event.WhichOneof("payload")
                if kind == "task":
                    last_state = event.task.status.state
                    msg = event.task.status.message
                    if msg and msg.parts:
                        final_text_parts = [p.text for p in msg.parts if p.text]
                elif kind == "status_update":
                    last_state = event.status_update.status.state
                    msg = event.status_update.status.message
                    if msg and msg.parts:
                        # Replace, not append — last completed status wins.
                        final_text_parts = [p.text for p in msg.parts if p.text]
                elif kind == "message":
                    final_text_parts = [p.text for p in event.message.parts if p.text]
            text = "".join(final_text_parts)
            if last_state == TaskState.TASK_STATE_INPUT_REQUIRED and text:
                try:
                    marker = json.loads(text)
                except (ValueError, TypeError):
                    marker = None
                friendly = _approval_pending_reply(marker)
                if friendly is not None:
                    return friendly
            return text or "(no response)"
        except Exception as e:  # noqa: BLE001
            return f"[{subagent_name} error] {e}"
        finally:
            close = getattr(client, "close", None) if client is not None else None
            if close is not None:
                # Close errors must not mask the call result.
                with contextlib.suppress(Exception):
                    await close()
            if http_client is not None:
                with contextlib.suppress(Exception):
                    await http_client.aclose()

    return _call


def _inject_otel_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    """Inject the active span's W3C traceparent into envelope metadata.

    Returns the same dict (mutated in place) so callers can chain. No-op
    when OTel isn't initialized — ``inject`` writes nothing into the
    carrier when no active span context exists.
    """
    try:
        from opentelemetry.propagate import inject

        inject(metadata)
    except Exception:  # noqa: BLE001
        # Telemetry must never break the data path. Logged at debug.
        logger.debug("traceparent injection failed", exc_info=True)
    return metadata


def _make_nats_tool(
    subagent_name: str, subject: str, nats_url: str, description: str,
):
    """Build an `ask_<name>` LangChain tool that talks to a peer over NATS.

    Each call:
      1. Connects (or re-uses cached connection) to the broker.
      2. Publishes a JSON-RPC `message/send` envelope on the peer's subject.
      3. Awaits the reply on the auto-generated reply inbox (60s timeout).
      4. Extracts text from `result.status.message.parts[].text`.

    The envelope's ``params.message.metadata`` carries the current
    span's W3C traceparent so the receiving agent's bridge can extract
    it and continue the trace under a single root.

    Errors (timeout, no responders, malformed reply) are returned as a
    `[<name> error] ...` string — same UX as the HTTP path so the LLM
    can surface failures in its reply rather than crashing the turn.
    """
    sanitized = subagent_name.replace("-", "_")
    tool_name = f"ask_{sanitized}"

    @tool(tool_name, description=description)
    async def _call(query: str) -> str:
        import nats

        rpc_id = uuid.uuid4().hex
        envelope = {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "method": "message/send",
            "params": {
                "message": {
                    "kind": "message",
                    "messageId": uuid.uuid4().hex,
                    "role": "user",
                    "parts": [{"kind": "text", "text": query}],
                    "metadata": _inject_otel_metadata({}),
                },
            },
        }
        nc = None
        # Wrap nc.request in an OTel span so the publish appears as a
        # child of the current LangChain tool span (when telemetry is
        # configured). When OTel isn't initialized the no-op tracer
        # creates inert spans — zero overhead.
        try:
            from opentelemetry import trace as _otel_trace

            tracer = _otel_trace.get_tracer("vystak.runtime.subagents")
        except Exception:  # noqa: BLE001
            tracer = None  # type: ignore[assignment]
        try:
            nc = await nats.connect(nats_url)
            payload = json.dumps(envelope).encode()
            if tracer is not None:
                with tracer.start_as_current_span(
                    f"nats.request {subject}",
                    attributes={
                        "messaging.system": "nats",
                        "messaging.destination": subject,
                        "messaging.operation": "send",
                    },
                ):
                    reply = await nc.request(subject, payload, timeout=60)
            else:
                reply = await nc.request(subject, payload, timeout=60)
            try:
                body = json.loads(reply.data)
            except (json.JSONDecodeError, ValueError) as e:
                return f"[{subagent_name} error] invalid reply: {e}"
            if "error" in body:
                err = body["error"]
                return f"[{subagent_name} error] {err.get('message', '?')}"
            result = body.get("result") or {}
            status = result.get("status") or {}
            msg = status.get("message") or {}
            parts = msg.get("parts") or []
            text = "".join(p.get("text", "") for p in parts if isinstance(p, dict))
            state_value = status.get("state")
            if state_value in ("input-required", "input_required") and text:
                try:
                    marker = json.loads(text)
                except (json.JSONDecodeError, ValueError, TypeError):
                    marker = None
                friendly = _approval_pending_reply(marker)
                if friendly is not None:
                    return friendly
            return text or "(no response)"
        except Exception as e:  # noqa: BLE001
            return f"[{subagent_name} error] {e}"
        finally:
            if nc is not None:
                with contextlib.suppress(Exception):
                    await nc.close()

    return _call
