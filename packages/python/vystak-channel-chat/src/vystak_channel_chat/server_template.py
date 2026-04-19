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

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

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
# Short-name → wire-address map kept for /v1/responses proxying and the
# /health + /v1/models listings (backward compatible with the old ROUTES dict).
ROUTES: dict[str, str] = {
    short: entry["address"] for short, entry in _ROUTES_RAW.items()
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
    """Proxy OpenAI Responses API to the target agent.

    Unlike /v1/chat/completions we don't translate A2A — agents already emit
    the Responses API shape (the LangChain adapter's /v1/responses endpoint).
    Just route by `model` and forward the bytes. This is a direct HTTP proxy,
    not an A2A dispatch, so it stays on httpx.
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

    agent_url = ROUTES[agent_name]
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
            _proxy_responses_stream(agent_url, agent_name, body),
            media_type="text/event-stream",
        )

    try:
        async with httpx.AsyncClient(timeout=300) as client:
            resp = await client.post(f"{agent_url}/v1/responses", json=body)
    except httpx.HTTPError as e:
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

    try:
        payload = resp.json()
    except Exception:
        return JSONResponse(
            status_code=502,
            content={
                "error": {
                    "message": "Upstream returned non-JSON response",
                    "type": "upstream_error",
                    "code": "agent_unreachable",
                }
            },
        )

    resp_id = payload.get("id") if isinstance(payload, dict) else None
    if resp_id:
        _RESPONSE_OWNERS[resp_id] = agent_name

    return JSONResponse(status_code=resp.status_code, content=payload)


async def _proxy_responses_stream(agent_url: str, agent_name: str, body: dict):
    """Stream /v1/responses SSE from agent through to client byte-for-byte."""
    try:
        async with httpx.AsyncClient(timeout=300) as client:
            async with client.stream(
                "POST", f"{agent_url}/v1/responses", json=body
            ) as resp:
                async for line in resp.aiter_lines():
                    # Preserve line structure; SSE is line-delimited
                    if not line:
                        yield "\\n"
                        continue

                    if line.startswith("data: "):
                        data_str = line[6:]
                        if data_str and data_str != "[DONE]":
                            try:
                                event = json.loads(data_str)
                            except json.JSONDecodeError:
                                event = None
                            if isinstance(event, dict):
                                resp_obj = event.get("response")
                                if isinstance(resp_obj, dict):
                                    rid = resp_obj.get("id")
                                    if isinstance(rid, str):
                                        _RESPONSE_OWNERS[rid] = agent_name

                    yield line + "\\n"
    except httpx.HTTPError as e:
        err = {
            "error": {
                "message": f"Upstream agent error: {e}",
                "type": "upstream_error",
                "code": "agent_unreachable",
            }
        }
        yield f"data: {json.dumps(err)}\\n\\n"
        yield "data: [DONE]\\n\\n"


@app.get("/v1/responses/{response_id}")
async def get_response(response_id: str):
    """Look up the owning agent from the in-memory map and proxy the GET."""
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

    if owner not in ROUTES:
        return JSONResponse(
            status_code=502,
            content={
                "error": {
                    "message": f"Owning agent '{owner}' is no longer routed",
                    "type": "upstream_error",
                    "code": "agent_unreachable",
                }
            },
        )

    agent_url = ROUTES[owner]
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(f"{agent_url}/v1/responses/{response_id}")
    except httpx.HTTPError as e:
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

    try:
        return JSONResponse(status_code=resp.status_code, content=resp.json())
    except Exception:
        return JSONResponse(status_code=resp.status_code, content={"id": response_id})


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


REQUIREMENTS = """\
fastapi>=0.115
uvicorn>=0.34
httpx>=0.28
pydantic>=2.0
vystak>=0.1
vystak-transport-http>=0.1
"""
