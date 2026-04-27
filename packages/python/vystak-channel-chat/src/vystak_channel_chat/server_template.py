"""Literal source for the chat channel FastAPI server.

Emitted as `server.py` inside the channel container image. Kept as a plain
string so the channel container has zero dependency on the vystak source tree.
"""

SERVER_PY = '''\
"""Chat channel — OpenAI-compatible endpoint routing to agents via A2A."""

import json
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

# Configure root logging so module loggers (incl. vystak.transport.nats,
# vystak.channel.chat) actually emit. Uvicorn has its own handlers for
# uvicorn.* but propagation to root is what vystak.* needs.
logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

logger = logging.getLogger("vystak.channel.chat")

ROUTES_PATH = Path(os.environ.get("ROUTES_PATH", "/app/routes.json"))


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
# Canonical-name → wire-address map for HttpTransport and the /v1/responses
# byte-level proxy.
_http_routes: dict[str, str] = {
    entry["canonical"]: entry["address"] for entry in _ROUTES_RAW.values()
}
# Short-name → direct HTTP URL for the /v1/responses byte-proxy and for
# /health + /v1/models listings. Agents run FastAPI on port 8000 regardless
# of A2A transport (Plan A's "FastAPI always-on" principle), so the HTTP
# endpoint is reachable even when the A2A path goes over NATS. On Docker,
# container DNS is `vystak-<agent_name>` on vystak-net.
ROUTES: dict[str, str] = {
    short: f"http://vystak-{short}:8000" for short in _ROUTES_RAW
}

# response_id -> agent_name. Populated by /v1/responses proxy so GETs for a
# stored response land on the agent that created it. In-memory and non-HA:
# restart drops the map and old IDs 404 until the client retries.
_RESPONSE_OWNERS: dict[str, str] = {}


class ChatMessage(BaseModel):
    role: str
    content: str | None = None


class ChatCompletionRequest(BaseModel):
    model: str
    messages: list[ChatMessage]
    stream: bool = False


app = FastAPI(title="vystak-channel-chat")


# --- Transport bootstrap ---
# Install the process-level AgentClient BEFORE any route handlers that call
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


@app.get("/health")
async def health():
    return {"status": "ok", "agents": list(ROUTES.keys())}


@app.get("/v1/models")
async def list_models():
    return {
        "object": "list",
        "data": [
            {
                "id": f"vystak/{name}",
                "object": "model",
                "created": int(time.time()),
                "owned_by": "vystak",
            }
            for name in ROUTES
        ],
    }


def _coerce_text(value) -> str:
    """LangGraph sometimes packs content as a list of blocks. Flatten to a string."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            if isinstance(item, str):
                out.append(item)
            elif isinstance(item, dict):
                if item.get("type") and item["type"] != "text":
                    continue
                inner = item.get("text", "")
                if isinstance(inner, str) and inner:
                    out.append(inner)
        return "".join(out)
    return str(value)


def _pick_last_user(messages: list[ChatMessage]) -> str:
    for msg in reversed(messages):
        if msg.role == "user" and msg.content:
            return msg.content
    return ""


def _not_found(model: str) -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content={
            "error": {
                "message": f"Model '{model}' not found",
                "type": "invalid_request_error",
                "code": "model_not_found",
            }
        },
    )


@app.post("/v1/chat/completions")
async def chat_completions(request: ChatCompletionRequest):
    agent_name = request.model.removeprefix("vystak/")

    if agent_name not in ROUTES:
        return _not_found(request.model)

    last_user = _pick_last_user(request.messages)
    session_id = str(uuid.uuid4())

    if request.stream:
        return StreamingResponse(
            _stream_chunks(agent_name, request.model, session_id, last_user),
            media_type="text/event-stream",
        )

    response_text = await _default_client().send_task(
        agent_name,
        last_user,
        metadata={"sessionId": session_id},
    )

    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": request.model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": response_text},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        },
    }


async def _stream_chunks(agent_name: str, model: str, session_id: str, text: str):
    """Translate A2A stream events → OpenAI chat.completion.chunk SSE."""
    completion_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    created = int(time.time())

    def _chunk(delta: dict, finish_reason=None) -> str:
        payload = {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "choices": [
                {"index": 0, "delta": delta, "finish_reason": finish_reason},
            ],
        }
        return f"data: {json.dumps(payload)}\\n\\n"

    finished = False
    try:
        async for event in _default_client().stream_task(
            agent_name,
            text,
            metadata={"sessionId": session_id},
        ):
            # A2AEvent carries (type, text, data, final). Only text-bearing
            # content translates to an OpenAI chunk delta.
            if event.text:
                yield _chunk({"content": event.text})
            if event.final:
                yield _chunk({}, finish_reason="stop")
                yield "data: [DONE]\\n\\n"
                finished = True
                return
    except Exception as e:
        err = {
            "error": {
                "message": f"Upstream agent error: {e}",
                "type": "upstream_error",
                "code": "agent_unreachable",
            }
        }
        yield f"data: {json.dumps(err)}\\n\\n"
        yield "data: [DONE]\\n\\n"
        finished = True
        return
    finally:
        if not finished:
            # Agent closed the stream without a terminal `final: true` event.
            # Still emit finish + [DONE] so OpenAI clients don't hang.
            yield _chunk({}, finish_reason="stop")
            yield "data: [DONE]\\n\\n"


@app.post("/v1/responses")
async def create_response(request: Request):
    """Route OpenAI Responses API to the target agent via AgentClient.

    Unlike /v1/chat/completions we don't translate A2A — agents already emit
    the Responses API shape (the LangChain adapter's /v1/responses endpoint).
    Routes by `model` through the configured transport (HTTP or NATS).
    """
    try:
        body: dict[str, Any] = await request.json()
    except Exception:
        return JSONResponse(
            status_code=400,
            content={
                "error": {
                    "message": "Invalid JSON body",
                    "type": "invalid_request_error",
                    "code": "invalid_request",
                }
            },
        )

    model = body.get("model", "") or ""
    agent_name = model.removeprefix("vystak/")
    if agent_name not in ROUTES:
        return _not_found(model)

    streaming = bool(body.get("stream", False))

    # Guard cross-agent response chaining — previous_response_id is only valid
    # on the agent that created it.
    prev_id = body.get("previous_response_id")
    if prev_id:
        owner = _RESPONSE_OWNERS.get(prev_id)
        if owner is not None and owner != agent_name:
            return JSONResponse(
                status_code=400,
                content={
                    "error": {
                        "message": (
                            f"previous_response_id belongs to agent '{owner}' — "
                            f"cannot chain to agent '{agent_name}'"
                        ),
                        "type": "invalid_request_error",
                        "code": "invalid_previous_response",
                    }
                },
            )

    if streaming:
        return StreamingResponse(
            _stream_responses(agent_name, body),
            media_type="text/event-stream",
        )

    session_id = str(uuid.uuid4())
    try:
        result = await _default_client().create_response(
            agent_name, body, metadata={"sessionId": session_id},
        )
    except Exception as e:
        return JSONResponse(
            status_code=502,
            content={
                "error": {
                    "message": f"Upstream agent error: {e}",
                    "type": "upstream_error",
                    "code": "agent_unreachable",
                }
            },
        )

    if isinstance(result, dict) and result.get("id") and body.get("store", True):
        _RESPONSE_OWNERS[result["id"]] = agent_name

    return JSONResponse(result)


async def _stream_responses(agent_name: str, body: dict):
    """Stream /v1/responses SSE from agent through to client via AgentClient."""
    try:
        async for chunk in _default_client().create_response_stream(
            agent_name, body, metadata={}, timeout=300,
        ):
            # Chunk is already an OpenAI response-stream event dict.
            # Emit as SSE to the client.
            yield f"data: {json.dumps(chunk)}\\n\\n"

            # Capture response_id for GET routing when we see response.created.
            if chunk.get("type") == "response.created":
                resp = chunk.get("response", {})
                if isinstance(resp, dict) and resp.get("id") and body.get("store", True):
                    _RESPONSE_OWNERS[resp["id"]] = agent_name
    except Exception as e:
        err = {
            "type": "error",
            "error": {"message": str(e)},
        }
        yield f"data: {json.dumps(err)}\\n\\n"


@app.get("/v1/responses/{response_id}")
async def get_response(response_id: str):
    """Look up the owning agent from the in-memory map and retrieve via AgentClient."""
    owner = _RESPONSE_OWNERS.get(response_id)
    if owner is None:
        return JSONResponse(
            status_code=404,
            content={
                "error": {
                    "message": (
                        f"Response '{response_id}' not found on this chat channel. "
                        f"Responses created before restart are not retained."
                    ),
                    "type": "invalid_request_error",
                    "code": "response_not_found",
                }
            },
        )

    try:
        result = await _default_client().get_response(owner, response_id)
    except Exception as e:
        return JSONResponse(
            status_code=502,
            content={
                "error": {
                    "message": f"Upstream agent error: {e}",
                    "type": "upstream_error",
                    "code": "agent_unreachable",
                }
            },
        )

    if result is None:
        return JSONResponse(
            status_code=404,
            content={
                "error": {
                    "code": "response_not_found",
                    "message": f"{response_id} not found",
                }
            },
        )

    return JSONResponse(result)


async def _resolve_agent_for_thread(thread_id: str) -> str | None:
    """Return the HTTP base URL for the agent that owns *thread_id*.

    The thread_id is opaque to the chat channel — we cannot look it up in
    _RESPONSE_OWNERS (which is keyed by response_id, not thread_id).  The
    strategy is:
    - If exactly one agent is routed, use it unconditionally (single-agent
      deployments, the overwhelmingly common case).
    - Otherwise return None, letting the caller respond with 404.
    """
    if len(ROUTES) == 1:
        agent_name = next(iter(ROUTES))
        return ROUTES[agent_name]
    return None


@app.post("/v1/sessions/{thread_id}/compact")
async def proxy_compact(thread_id: str, request: Request):
    target = await _resolve_agent_for_thread(thread_id)
    if target is None:
        return JSONResponse(status_code=404, content={"error": {"message": f"thread '{thread_id}' not routed", "type": "invalid_request_error", "code": "thread_not_found"}})
    body = await request.body()
    import httpx
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(f"{target}/v1/sessions/{thread_id}/compact", content=body, headers={"content-type": "application/json"})
    return JSONResponse(status_code=resp.status_code, content=resp.json())


@app.get("/v1/sessions/{thread_id}/compactions")
async def proxy_list_compactions(thread_id: str):
    target = await _resolve_agent_for_thread(thread_id)
    if target is None:
        return JSONResponse(status_code=404, content={"error": {"message": f"thread '{thread_id}' not routed", "type": "invalid_request_error", "code": "thread_not_found"}})
    import httpx
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(f"{target}/v1/sessions/{thread_id}/compactions")
    return JSONResponse(status_code=resp.status_code, content=resp.json())


@app.get("/v1/sessions/{thread_id}/compactions/{generation}")
async def proxy_get_compaction(thread_id: str, generation: int):
    target = await _resolve_agent_for_thread(thread_id)
    if target is None:
        return JSONResponse(status_code=404, content={"error": {"message": f"thread '{thread_id}' not routed", "type": "invalid_request_error", "code": "thread_not_found"}})
    import httpx
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(f"{target}/v1/sessions/{thread_id}/compactions/{generation}")
    return JSONResponse(status_code=resp.status_code, content=resp.json())


if __name__ == "__main__":
    import uvicorn

    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8080"))
    uvicorn.run(app, host=host, port=port)
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
httpx>=0.27
sse-starlette>=2.0
pydantic>=2.0
pyyaml>=6.0
aiosqlite>=0.20
nats-py>=2.6
"""
