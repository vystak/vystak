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
from fastapi.responses import JSONResponse
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


@app.post("/v1/chat/completions")
async def chat_completions(request: ChatCompletionRequest):
    agent_name = request.model.removeprefix("vystak/")

    if agent_name not in ROUTES:
        return JSONResponse(
            status_code=404,
            content={
                "error": {
                    "message": f"Model '{request.model}' not found",
                    "type": "invalid_request_error",
                    "code": "model_not_found",
                }
            },
        )

    last_user = ""
    for msg in reversed(request.messages):
        if msg.role == "user" and msg.content:
            last_user = msg.content
            break

    session_id = str(uuid.uuid4())
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

    agent_url = ROUTES[agent_name]
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(f"{agent_url}/a2a", json=a2a_request)
        a2a_resp = resp.json()

    response_text = ""
    result = a2a_resp.get("result", {})
    status = result.get("status", {})
    status_message = status.get("message", {})
    parts = status_message.get("parts", [])
    if parts:
        response_text = parts[0].get("text", "")

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
