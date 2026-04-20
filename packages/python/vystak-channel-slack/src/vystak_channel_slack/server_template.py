"""Literal source for the Slack channel runtime.

Emitted as `server.py` inside the channel container image. The container's
main process runs a slack-bolt AsyncSocketModeHandler alongside a small
FastAPI health sidecar.
"""

SERVER_PY = '''\
"""Slack channel — Socket Mode runner forwarding events to agents via A2A."""

import asyncio
import json
import logging
import os
import uuid
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from slack_bolt.async_app import AsyncApp

logger = logging.getLogger("vystak.channel.slack")

ROUTES_PATH = Path(os.environ.get("ROUTES_PATH", "/app/routes.json"))
RULES_PATH = Path(os.environ.get("RULES_PATH", "/app/rules.json"))


def _load_routes_raw() -> dict:
    """Load the transport route table.

    Canonical shape (Task 14+):
        VYSTAK_ROUTES_JSON={"<short>": {"canonical": "...", "address": "..."}}

    Fallback (pre-Task-17 providers still emit `routes.json` with the old
    `{short: URL}` map; we convert it here). Task 17/18 will rewrite the
    providers to populate the env var directly and drop the fallback.
    """
    env_raw = os.environ.get("VYSTAK_ROUTES_JSON")
    if env_raw:
        raw = json.loads(env_raw)
        if raw and isinstance(next(iter(raw.values())), dict) and "canonical" in next(iter(raw.values())):
            return raw
        # Env var was set but holds legacy {short: URL} shape — convert.
        return {
            short: {"canonical": f"{short}.agents.default", "address": value}
            for short, value in raw.items()
        }

    if ROUTES_PATH.exists():
        logger.warning(
            "Using routes.json fallback; VYSTAK_ROUTES_JSON not set"
        )
        raw = json.loads(ROUTES_PATH.read_text())
        if raw and isinstance(next(iter(raw.values())), dict) and "canonical" in next(iter(raw.values())):
            # Already in the new shape — short-circuit.
            return raw
        # Old shape: short → URL. Derive a canonical name. Wrong for
        # non-default namespaces, but acceptable during migration.
        return {
            short: {"canonical": f"{short}.agents.default", "address": value}
            for short, value in raw.items()
        }

    return {}


_ROUTES_RAW: dict = _load_routes_raw()

# Short-name → canonical-name map for AgentClient.
_client_routes: dict[str, str] = {
    short: entry["canonical"] for short, entry in _ROUTES_RAW.items()
}
# Canonical-name → wire-address map for HttpTransport.
_http_routes: dict[str, str] = {
    entry["canonical"]: entry["address"] for entry in _ROUTES_RAW.values()
}
# Short-name → direct HTTP URL for /health listings. Agents run FastAPI
# on port 8000 regardless of A2A transport; on Docker, container DNS is
# `vystak-<agent_name>` on vystak-net.
ROUTES: dict[str, str] = {
    short: f"http://vystak-{short}:8000" for short in _ROUTES_RAW
}


def _load_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text())


RULES: list[dict] = _load_json(RULES_PATH, [])


def _match_rule(slack_channel: str | None, is_dm: bool) -> str | None:
    """Return agent name for the first matching rule, or None."""
    for rule in RULES:
        match = rule.get("match") or {}

        if match.get("dm") is True and is_dm:
            return rule.get("agent")
        if "slack_channel" in match and match["slack_channel"] == slack_channel:
            return rule.get("agent")
        if not match:
            return rule.get("agent")
    return None


def _session_id(channel: str | None, thread_ts: str | None, ts: str | None, user: str | None) -> str:
    if channel is None and user:
        return f"slack:dm:{user}"
    if thread_ts:
        return f"slack:{channel}:{thread_ts}"
    return f"slack:{channel}:{ts}"


BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN", "")
APP_TOKEN = os.environ.get("SLACK_APP_TOKEN", "")

slack_app = AsyncApp(token=BOT_TOKEN)

# --- Transport bootstrap ---
# Install the process-level AgentClient BEFORE any event handlers that call
# _default_client(). Mirrors the bootstrap emitted by the LangChain adapter.
from vystak.transport import AgentClient as _AgentClient  # noqa: E402
from vystak.transport import client as _vystak_client_module  # noqa: E402


def _build_transport_from_env():
    transport_type = os.environ.get("VYSTAK_TRANSPORT_TYPE", "http")
    if transport_type == "http":
        from vystak_transport_http import HttpTransport

        return HttpTransport(routes=_http_routes)
    if transport_type == "nats":
        from vystak_transport_nats import NatsTransport

        url = os.environ["VYSTAK_NATS_URL"]
        prefix = os.environ.get("VYSTAK_NATS_SUBJECT_PREFIX", "vystak")
        return NatsTransport(url=url, subject_prefix=prefix)
    raise RuntimeError(
        f"unsupported VYSTAK_TRANSPORT_TYPE={transport_type}"
    )


_transport = _build_transport_from_env()
_vystak_client_module._DEFAULT_CLIENT = _AgentClient(
    transport=_transport,
    routes=_client_routes,
)


def _default_client() -> _AgentClient:
    return _vystak_client_module._default_client()


async def _forward_to_agent(agent_name: str, text: str, session_id: str) -> str:
    return await _default_client().send_task(
        agent_name,
        text,
        metadata={"sessionId": session_id},
    )


@slack_app.event("app_mention")
async def on_mention(event, say):
    channel = event.get("channel", "")
    is_dm = event.get("channel_type") == "im"
    agent_name = _match_rule(channel, is_dm)
    if agent_name is None or agent_name not in ROUTES:
        return

    session_id = _session_id(
        channel,
        event.get("thread_ts"),
        event.get("ts"),
        event.get("user"),
    )
    text = event.get("text", "")
    reply = await _forward_to_agent(agent_name, text, session_id)
    await say(text=reply, thread_ts=event.get("thread_ts") or event.get("ts"))


@slack_app.event("message")
async def on_message(event, say):
    if event.get("bot_id") or event.get("subtype"):
        return

    channel = event.get("channel", "")
    is_dm = event.get("channel_type") == "im"

    if not is_dm:
        return  # mentions are already handled by on_mention

    agent_name = _match_rule(None, is_dm=True)
    if agent_name is None or agent_name not in ROUTES:
        return

    session_id = _session_id(
        None,
        event.get("thread_ts"),
        event.get("ts"),
        event.get("user"),
    )
    text = event.get("text", "")
    reply = await _forward_to_agent(agent_name, text, session_id)
    await say(text=reply)


health_app = FastAPI(title="vystak-channel-slack")


@health_app.get("/health")
async def health():
    return {
        "status": "ok",
        "agents": list(ROUTES.keys()),
        "rules": len(RULES),
        "socket_mode": bool(BOT_TOKEN and APP_TOKEN),
    }


async def _run():
    if not BOT_TOKEN or not APP_TOKEN:
        raise RuntimeError(
            "SLACK_BOT_TOKEN and SLACK_APP_TOKEN must be set in the channel container environment"
        )

    handler = AsyncSocketModeHandler(slack_app, APP_TOKEN)
    port = int(os.environ.get("PORT", "8080"))
    config = uvicorn.Config(health_app, host="0.0.0.0", port=port, log_level="info")
    server = uvicorn.Server(config)

    await asyncio.gather(handler.start_async(), server.serve())


if __name__ == "__main__":
    asyncio.run(_run())
'''


DOCKERFILE = """\
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["python", "server.py"]
"""


# vystak + vystak_transport_http are bundled as source by DockerChannelNode
# (they're on PYTHONPATH via COPY . . in the Dockerfile).
# pyyaml + aiosqlite are vystak's own runtime deps — needed because
# vystak/__init__.py eagerly imports schema.loader (yaml) and stores (aiosqlite).
REQUIREMENTS = """\
fastapi>=0.115
uvicorn>=0.34
httpx>=0.28
slack-bolt>=1.21
aiohttp>=3.9
pydantic>=2.0
pyyaml>=6.0
aiosqlite>=0.20
nats-py>=2.6
"""
