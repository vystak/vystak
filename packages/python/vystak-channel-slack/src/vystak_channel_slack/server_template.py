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
import re
import uuid
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from slack_bolt.async_app import AsyncApp

logging.basicConfig(
    level=os.environ.get("VYSTAK_LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("vystak.channel.slack")

ROUTES_PATH = Path(os.environ.get("ROUTES_PATH", "/app/routes.json"))
CHANNEL_CONFIG_PATH = Path(os.environ.get("CHANNEL_CONFIG_PATH", "/app/channel_config.json"))


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


def _load_channel_config() -> dict:
    if CHANNEL_CONFIG_PATH.exists():
        return json.loads(CHANNEL_CONFIG_PATH.read_text())
    return {}


_channel_config: dict = _load_channel_config()

# --- Store bootstrap ---
from vystak.schema.service import Sqlite as _Sqlite  # noqa: E402
from vystak_channel_slack.store import make_store as _make_store  # noqa: E402
from vystak_channel_slack.resolver import ResolverConfig as _ResolverConfig  # noqa: E402
from vystak_channel_slack.resolver import resolve as _resolve  # noqa: E402
from vystak_channel_slack.resolver import Event as _Event  # noqa: E402
from vystak_channel_slack import commands as _commands  # noqa: E402
from vystak_channel_slack import welcome as _welcome  # noqa: E402

_state_cfg = _channel_config.get("state") or {"type": "sqlite", "path": "/data/channel-state.db"}
_store = _make_store(_Sqlite(**{k: v for k, v in _state_cfg.items() if k in ("name", "path", "type")}) if _state_cfg.get("type") == "sqlite" else __import__("vystak.schema.service", fromlist=["Postgres"]).Postgres(**_state_cfg))
_store.migrate()


def _build_resolver_config() -> _ResolverConfig:
    cfg = _channel_config
    return _ResolverConfig(
        agents=cfg.get("agents", []),
        group_policy=cfg.get("group_policy", "open"),
        dm_policy=cfg.get("dm_policy", "open"),
        allow_from=cfg.get("allow_from", []),
        allow_bots=cfg.get("allow_bots", False),
        channel_overrides=cfg.get("channel_overrides", {}),
        default_agent=cfg.get("default_agent"),
        ai_fallback=None,
    )


_resolver_cfg: _ResolverConfig = _build_resolver_config()


def _load_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text())


BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN", "")
APP_TOKEN = os.environ.get("SLACK_APP_TOKEN", "")
BOT_USER_ID = os.environ.get("SLACK_BOT_USER_ID", "")

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


def _session_id(channel: str | None, thread_ts: str | None, ts: str | None, user: str | None) -> str:
    if channel is None and user:
        return f"slack:dm:{user}"
    if thread_ts:
        return f"slack:{channel}:{thread_ts}"
    return f"slack:{channel}:{ts}"


_FENCE_RE = re.compile(r"```[\\s\\S]*?```|`[^`]*`")
_HEADING_RE = re.compile(r"^\\s{0,3}#{1,6}\\s+(.+?)\\s*#*\\s*$", re.MULTILINE)
_BOLD_RE = re.compile(r"\\*\\*(.+?)\\*\\*", re.DOTALL)
_UNDERSCORE_BOLD_RE = re.compile(r"__(.+?)__", re.DOTALL)
_STRIKE_RE = re.compile(r"~~(.+?)~~", re.DOTALL)
_LINK_RE = re.compile(r"\\[([^\\]]+?)\\]\\(([^)]+?)\\)")
_BULLET_RE = re.compile(r"^(\\s*)[*+-]\\s+", re.MULTILINE)


def _to_slack_mrkdwn(text: str) -> str:
    """Convert the agent's GitHub-flavored Markdown reply to Slack mrkdwn.

    Slack's mrkdwn differs from GFM in enough ways that posting raw GFM
    renders as literal syntax ("# Hello", "**bold**"). This converter
    handles the common cases:

    - # / ## / ### headings -> *bold* (Slack has no heading syntax)
    - **bold** / __bold__     -> *bold*
    - bare *italic* / _italic_ -> _italic_
    - ~~strike~~              -> ~strike~
    - [text](url)             -> <url|text>
    - - / * / + bullet        -> • bullet (U+2022)
    - Fenced ``` blocks and inline `code` pass through unchanged
      (Slack renders them natively).

    Code regions are masked before other conversions so inline markers
    inside code (e.g. `**literal**`) don't get rewritten.
    """
    # 1. Mask code regions with placeholders so other passes skip them.
    masks: list[str] = []

    def _stash(m):
        masks.append(m.group(0))
        return f"\\x00CODE{len(masks) - 1}\\x00"

    out = _FENCE_RE.sub(_stash, text)

    # 2. Headings -> *bold* line
    out = _HEADING_RE.sub(r"*\\1*", out)

    # 3. Bold: ** ** and __ __ -> * *
    out = _BOLD_RE.sub(r"*\\1*", out)
    out = _UNDERSCORE_BOLD_RE.sub(r"*\\1*", out)

    # 4. Italic is NOT converted — GFM `*x*` (italic) and Slack `*x*`
    #    (bold) share syntax, so any rewrite here would swap
    #    bold/italic where the agent used GFM italic. GFM `_x_` already
    #    renders as Slack italic as-is. The tradeoff: GFM `*italic*`
    #    reaches Slack as bold, which reads fine in practice.

    # 5. Strikethrough: ~~x~~ -> ~x~
    out = _STRIKE_RE.sub(r"~\\1~", out)

    # 6. Links: [text](url) -> <url|text>
    out = _LINK_RE.sub(r"<\\2|\\1>", out)

    # 7. Bullets: "- item" / "* item" / "+ item" -> "• item"
    _BULLET = "\\u2022"  # Unicode BULLET; not using re replacement \\uXXXX
    out = _BULLET_RE.sub(r"\\1" + _BULLET + " ", out)

    # 8. Unmask code regions.
    for i, original in enumerate(masks):
        out = out.replace(f"\\x00CODE{i}\\x00", original)

    return out


_PLACEHOLDER_TEXT = "_Responding..._"


async def _post_placeholder(say, *, thread_ts: str | None) -> dict | None:
    """Post a 'Responding...' placeholder, returning {channel, ts} or None on failure.

    Slack's chat.update needs both channel and ts to edit a message. say()
    returns the AsyncSlackResponse from chat.postMessage which carries both
    in its payload. If the post fails for any reason we still want to send
    the eventual reply, so the caller falls back to a fresh say() in that case.
    """
    try:
        kwargs = {"text": _PLACEHOLDER_TEXT}
        if thread_ts:
            kwargs["thread_ts"] = thread_ts
        resp = await say(**kwargs)
        ts = resp.get("ts") if hasattr(resp, "get") else None
        ch = resp.get("channel") if hasattr(resp, "get") else None
        if ts and ch:
            return {"channel": ch, "ts": ts}
        logger.warning("placeholder post returned no ts/channel; falling back")
        return None
    except Exception as exc:
        logger.warning("placeholder post failed: %s; falling back", exc)
        return None


async def _finalize(client, say, placeholder, *, text: str, thread_ts: str | None) -> None:
    """Replace the placeholder with the final text, or post fresh if no placeholder."""
    if placeholder is not None:
        await client.chat_update(
            channel=placeholder["channel"],
            ts=placeholder["ts"],
            text=text,
        )
        return
    kwargs = {"text": text}
    if thread_ts:
        kwargs["thread_ts"] = thread_ts
    await say(**kwargs)


# Catch-all middleware: log every event Slack delivers so missing
# subscriptions / scopes are visible in the container logs without
# needing to enable trace-level Bolt logging.
@slack_app.middleware
async def _log_event_type(req, next_):
    body = req.body or {}
    payload = body.get("event") or {}
    logger.info(
        "slack event=%s subtype=%s channel=%s channel_type=%s user=%s",
        payload.get("type") or body.get("type") or "?",
        payload.get("subtype") or "-",
        payload.get("channel") or "-",
        payload.get("channel_type") or "-",
        payload.get("user") or "-",
    )
    await next_()


@slack_app.event("app_mention")
async def on_mention(event, say, client):
    channel = event.get("channel", "")
    channel_name = event.get("channel_name") or channel
    user = event.get("user", "")
    is_dm = event.get("channel_type") == "im"
    is_bot = bool(event.get("bot_id"))

    ev = _Event(
        team=event.get("team", ""),
        channel=channel,
        user=user,
        text=event.get("text", ""),
        is_dm=is_dm,
        is_bot=is_bot,
        channel_name=channel_name,
    )
    agent_name = _resolve(ev, _resolver_cfg, _store)
    logger.info(
        "mention resolve channel=%s user=%s text=%r -> agent=%s known_routes=%s",
        channel, user, ev.text[:80], agent_name, list(ROUTES.keys()),
    )
    if agent_name is None:
        logger.warning(
            "mention unrouted: no binding for channel=%s, no default_agent",
            channel,
        )
        await say(
            text=(
                "No agent is bound to this channel yet. Run "
                "`/vystak route <agent>` to pick one. Available agents: "
                + (", ".join(f"`{a}`" for a in _resolver_cfg.agents) or "_none declared_")
            ),
            thread_ts=event.get("thread_ts") or event.get("ts"),
        )
        return
    if agent_name not in ROUTES:
        logger.warning(
            "mention misrouted: agent=%s declared but not in transport routes %s",
            agent_name, list(ROUTES.keys()),
        )
        await say(
            text=(
                f"Agent `{agent_name}` is bound to this channel but isn't reachable "
                f"on the transport. Known routes: "
                + (", ".join(f"`{a}`" for a in ROUTES) or "_none_")
            ),
            thread_ts=event.get("thread_ts") or event.get("ts"),
        )
        return

    session_id = _session_id(
        channel,
        event.get("thread_ts"),
        event.get("ts"),
        user,
    )
    text = event.get("text", "")
    reply_thread_ts = event.get("thread_ts") or event.get("ts")
    placeholder = await _post_placeholder(say, thread_ts=reply_thread_ts)
    logger.info("mention forward agent=%s session=%s", agent_name, session_id)
    try:
        raw_reply = await _forward_to_agent(agent_name, text, session_id)
    except Exception as exc:
        logger.exception("mention forward failed agent=%s: %s", agent_name, exc)
        await _finalize(
            client, say, placeholder,
            text=f"Sorry, I hit an error talking to *{agent_name}*: `{exc}`",
            thread_ts=reply_thread_ts,
        )
        return
    logger.info("mention reply len=%d preview=%r", len(raw_reply or ""), (raw_reply or "")[:120])
    reply = _to_slack_mrkdwn(raw_reply)
    try:
        await _finalize(client, say, placeholder, text=reply, thread_ts=reply_thread_ts)
        logger.info("mention posted ok")
    except Exception as exc:
        logger.exception("mention post failed: %s", exc)


@slack_app.event("message")
async def on_message(event, say, client):
    if event.get("bot_id") or event.get("subtype"):
        logger.debug(
            "message ignored: bot_id=%s subtype=%s",
            event.get("bot_id"), event.get("subtype"),
        )
        return

    channel = event.get("channel", "")
    channel_name = event.get("channel_name") or channel
    user = event.get("user", "")
    is_dm = event.get("channel_type") == "im"

    if not is_dm:
        logger.debug("message ignored: not a DM (channel_type=%s)", event.get("channel_type"))
        return  # mentions are already handled by on_mention

    ev = _Event(
        team=event.get("team", ""),
        channel=channel,
        user=user,
        text=event.get("text", ""),
        is_dm=True,
        is_bot=False,
        channel_name=channel_name,
    )
    agent_name = _resolve(ev, _resolver_cfg, _store)
    logger.info(
        "dm resolve user=%s text=%r -> agent=%s known_routes=%s",
        user, ev.text[:80], agent_name, list(ROUTES.keys()),
    )
    if agent_name is None:
        logger.warning(
            "dm unrouted: no user pref, no default_agent (user=%s)", user,
        )
        await say(
            text=(
                "No default agent is configured for DMs. Either an admin "
                "needs to set `default_agent=<agent>` on the Channel "
                "declaration, or you can pick one yourself with "
                "`/vystak prefer <agent>`. Available agents: "
                + (", ".join(f"`{a}`" for a in _resolver_cfg.agents) or "_none declared_")
            ),
        )
        return
    if agent_name not in ROUTES:
        logger.warning(
            "dm misrouted: agent=%s declared but not in transport routes %s",
            agent_name, list(ROUTES.keys()),
        )
        await say(
            text=(
                f"Agent `{agent_name}` is set as your DM target but isn't reachable "
                f"on the transport. Known routes: "
                + (", ".join(f"`{a}`" for a in ROUTES) or "_none_")
            ),
        )
        return

    session_id = _session_id(
        None,
        event.get("thread_ts"),
        event.get("ts"),
        user,
    )
    text = event.get("text", "")
    placeholder = await _post_placeholder(say, thread_ts=None)
    logger.info("dm forward agent=%s session=%s", agent_name, session_id)
    try:
        raw_reply = await _forward_to_agent(agent_name, text, session_id)
    except Exception as exc:
        logger.exception("dm forward failed agent=%s: %s", agent_name, exc)
        await _finalize(
            client, say, placeholder,
            text=f"Sorry, I hit an error talking to *{agent_name}*: `{exc}`",
            thread_ts=None,
        )
        return
    logger.info("dm reply len=%d preview=%r", len(raw_reply or ""), (raw_reply or "")[:120])
    reply = _to_slack_mrkdwn(raw_reply)
    try:
        await _finalize(client, say, placeholder, text=reply, thread_ts=None)
        logger.info("dm posted ok")
    except Exception as exc:
        logger.exception("dm post failed: %s", exc)


@slack_app.event("member_joined_channel")
async def on_member_joined(event, client):
    await _welcome.on_member_joined(
        bot_user_id=BOT_USER_ID,
        joined_user_id=event.get("user", ""),
        inviter_id=event.get("inviter"),
        team=event.get("team", ""),
        channel=event.get("channel", ""),
        agents=_resolver_cfg.agents,
        single_agent_auto_bind=len(_resolver_cfg.agents) == 1,
        welcome_template=_channel_config.get("welcome_message") or "Hello! I can route your messages to: {agent_mentions}",
        slack=client,
        store=_store,
    )


@slack_app.command("/vystak")
async def on_slash_command(ack, body, client):
    await ack()
    team = body.get("team_id", "")
    channel = body.get("channel_id", "")
    user = body.get("user_id", "")
    text = body.get("text", "")
    cmd = body.get("command", "/vystak")
    try:
        result = _commands.handle_command(
            cmd=cmd,
            args=text,
            team=team,
            channel=channel,
            user=user,
            agents=_resolver_cfg.agents,
            route_authority=_channel_config.get("route_authority", "inviter"),
            store=_store,
        )
        await client.chat_postEphemeral(channel=channel, user=user, text=result.message)
    except _commands.NotAuthorized as exc:
        await client.chat_postEphemeral(channel=channel, user=user, text=str(exc))


health_app = FastAPI(title="vystak-channel-slack")


@health_app.get("/health")
async def health():
    return {
        "status": "ok",
        "agents": _resolver_cfg.agents,
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
RUN mkdir -p /data
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
psycopg[binary]>=3.0
"""
