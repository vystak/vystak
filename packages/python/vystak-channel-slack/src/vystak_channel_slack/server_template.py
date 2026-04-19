"""Literal source for the Slack channel runtime.

Emitted as `server.py` inside the channel container image. The container's
main process runs a slack-bolt AsyncSocketModeHandler alongside a small
FastAPI health sidecar.
"""

SERVER_PY = '''\
"""Slack channel — Socket Mode runner forwarding events to agents via A2A."""

import asyncio
import json
import os
import uuid
from pathlib import Path

import httpx
import uvicorn
from fastapi import FastAPI
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from slack_bolt.async_app import AsyncApp

ROUTES_PATH = Path(os.environ.get("ROUTES_PATH", "/app/routes.json"))
RULES_PATH = Path(os.environ.get("RULES_PATH", "/app/rules.json"))


def _load_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text())


ROUTES: dict[str, str] = _load_json(ROUTES_PATH, {})
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


async def _forward_to_agent(agent_url: str, text: str, session_id: str) -> str:
    a2a_request = {
        "jsonrpc": "2.0",
        "method": "tasks/send",
        "id": 1,
        "params": {
            "id": session_id,
            "sessionId": session_id,
            "message": {"role": "user", "parts": [{"text": text}]},
        },
    }
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(f"{agent_url}/a2a", json=a2a_request)
        payload = resp.json()
    result = payload.get("result", {})
    parts = result.get("status", {}).get("message", {}).get("parts", [])
    return parts[0].get("text", "") if parts else ""


BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN", "")
APP_TOKEN = os.environ.get("SLACK_APP_TOKEN", "")

slack_app = AsyncApp(token=BOT_TOKEN)


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
    reply = await _forward_to_agent(ROUTES[agent_name], text, session_id)
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
    reply = await _forward_to_agent(ROUTES[agent_name], text, session_id)
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


REQUIREMENTS = """\
fastapi>=0.115
uvicorn>=0.34
httpx>=0.28
slack-bolt>=1.21
aiohttp>=3.9
pydantic>=2.0
"""
