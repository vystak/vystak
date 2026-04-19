"""Literal source for the chat channel FastAPI server.

Emitted as `server.py` inside the channel container image. Kept as a plain
string so the channel container has zero dependency on the vystak source tree.
"""

SERVER_PY = '''\
"""Chat channel — OpenAI-compatible endpoint routing to agents via A2A."""

import json
import os
import time
import uuid
from pathlib import Path

import httpx
from fastapi import FastAPI
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

ROUTES_PATH = Path(os.environ.get("ROUTES_PATH", "/app/routes.json"))


def _load_routes() -> dict:
    if not ROUTES_PATH.exists():
        return {}
    return json.loads(ROUTES_PATH.read_text())


ROUTES: dict[str, str] = _load_routes()


class ChatMessage(BaseModel):
    role: str
    content: str | None = None


class ChatCompletionRequest(BaseModel):
    model: str
    messages: list[ChatMessage]
    stream: bool = False


app = FastAPI(title="vystak-channel-chat")


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


def _extract_text(a2a_resp: dict) -> str:
    """Return the final text response from an A2A tasks/send payload."""
    result = a2a_resp.get("result", {}) or {}
    status = result.get("status", {}) or {}
    status_message = status.get("message", {}) or {}
    parts = status_message.get("parts", []) or []
    collected: list[str] = []
    for part in parts:
        if not isinstance(part, dict):
            continue
        if part.get("type") and part.get("type") != "text":
            continue
        collected.append(_coerce_text(part.get("text", "")))
    return "".join(collected)


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
    agent_url = ROUTES[agent_name]

    if request.stream:
        return StreamingResponse(
            _stream_chunks(agent_url, request.model, session_id, last_user),
            media_type="text/event-stream",
        )

    a2a_request = {
        "jsonrpc": "2.0",
        "method": "tasks/send",
        "id": 1,
        "params": {
            "id": session_id,
            "sessionId": session_id,
            "message": {"role": "user", "parts": [{"text": last_user}]},
        },
    }

    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(f"{agent_url}/a2a", json=a2a_request)
        a2a_resp = resp.json()

    response_text = _extract_text(a2a_resp)

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


async def _stream_chunks(agent_url: str, model: str, session_id: str, text: str):
    """Translate A2A SSE (tasks/sendSubscribe) → OpenAI chat.completion.chunk SSE."""
    a2a_request = {
        "jsonrpc": "2.0",
        "method": "tasks/sendSubscribe",
        "id": 1,
        "params": {
            "id": session_id,
            "sessionId": session_id,
            "message": {"role": "user", "parts": [{"text": text}]},
        },
    }

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
        async with httpx.AsyncClient(timeout=120) as client:
            async with client.stream("POST", f"{agent_url}/a2a", json=a2a_request) as resp:
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    try:
                        event = json.loads(line[6:])
                    except json.JSONDecodeError:
                        continue

                    result = event.get("result", {})
                    artifact = result.get("artifact") or {}
                    for part in artifact.get("parts", []):
                        if not isinstance(part, dict):
                            continue
                        # A2A artifact parts can be text, thinking, tool_use,
                        # input_json_delta, etc. (LangGraph streams all event
                        # types). Only text is meaningful content for an
                        # OpenAI Chat Completions client — drop the rest.
                        if part.get("type") and part.get("type") != "text":
                            continue
                        text_part = _coerce_text(part.get("text", ""))
                        if text_part:
                            yield _chunk({"content": text_part})

                    if result.get("final"):
                        yield _chunk({}, finish_reason="stop")
                        yield "data: [DONE]\\n\\n"
                        finished = True
                        return
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
        finished = True
        return
    finally:
        if not finished:
            # Agent closed the stream without a terminal `final: true` event
            # (common when LangGraph ends without emitting the A2A sentinel).
            # Still emit finish + [DONE] so OpenAI clients don't hang.
            yield _chunk({}, finish_reason="stop")
            yield "data: [DONE]\\n\\n"


if __name__ == "__main__":
    import uvicorn

    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8080"))
    uvicorn.run(app, host=host, port=port)
'''


DOCKERFILE = '''\
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["python", "server.py"]
'''


REQUIREMENTS = '''\
fastapi>=0.115
uvicorn>=0.34
httpx>=0.28
pydantic>=2.0
'''
