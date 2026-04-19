"""Agent API client — OpenAI Responses API + Chat Completions."""

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass

import httpx


@dataclass
class ResponseResult:
    response: str
    response_id: str
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


@dataclass
class StreamResult:
    """Collected after streaming completes."""

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


@dataclass
class StreamEvent:
    """A single event from the stream."""

    type: (
        str  # "token", "function_call_start", "function_call_args", "function_call_output", "done"
    )
    token: str = ""
    tool: str = ""
    args: str = ""
    result: str = ""
    usage: dict | None = None
    response_id: str = ""


async def send_response(
    url: str,
    message: str,
    model: str = "",
    previous_response_id: str | None = None,
    user_id: str | None = None,
    project_id: str | None = None,
) -> ResponseResult:
    """Send a message via /v1/responses (non-streaming, store=true)."""
    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(
            f"{url}/v1/responses",
            json={
                "model": model,
                "input": message,
                "previous_response_id": previous_response_id,
                "store": True,
                "stream": False,
                "user_id": user_id,
                "project_id": project_id,
            },
        )
        response.raise_for_status()
        data = response.json()
        output = data.get("output", [])
        content = output[0]["content"] if output else ""
        usage = data.get("usage") or {}
        return ResponseResult(
            response=content,
            response_id=data["id"],
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            total_tokens=usage.get("total_tokens", 0),
        )


async def stream_response(
    url: str,
    message: str,
    model: str = "",
    previous_response_id: str | None = None,
    result: StreamResult | None = None,
    user_id: str | None = None,
) -> AsyncIterator[StreamEvent]:
    """Stream via /v1/responses with stream=true."""
    async with (
        httpx.AsyncClient(timeout=120.0) as client,
        client.stream(
            "POST",
            f"{url}/v1/responses",
            json={
                "model": model,
                "input": message,
                "previous_response_id": previous_response_id,
                "store": True,
                "stream": True,
                "user_id": user_id,
            },
        ) as response,
    ):
        response.raise_for_status()
        async for line in response.aiter_lines():
            if not line.startswith("data: "):
                continue
            data_str = line[6:]
            if data_str == "[DONE]":
                yield StreamEvent(type="done")
                return
            try:
                data = json.loads(data_str)
            except json.JSONDecodeError:
                continue

            event_type = data.get("type", "")

            if event_type == "response.output_text.delta":
                yield StreamEvent(type="token", token=data.get("delta", ""))

            elif event_type == "response.output_item.added":
                item = data.get("item", {})
                if item.get("type") == "function_call":
                    yield StreamEvent(type="function_call_start", tool=item.get("name", ""))
                elif item.get("type") == "function_call_output":
                    yield StreamEvent(type="function_call_output", result=item.get("output", ""))

            elif event_type == "response.function_call_arguments.delta":
                yield StreamEvent(type="function_call_args", args=data.get("delta", ""))

            elif event_type == "response.completed":
                resp = data.get("response", {})
                usage = resp.get("usage") or {}
                if result is not None:
                    result.input_tokens = usage.get("input_tokens", 0)
                    result.output_tokens = usage.get("output_tokens", 0)
                    result.total_tokens = usage.get("total_tokens", 0)
                yield StreamEvent(
                    type="done",
                    response_id=resp.get("id", ""),
                    usage=usage,
                )
                return


async def get_response(url: str, response_id: str) -> dict | None:
    """Get a response by ID (for background polling)."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{url}/v1/responses/{response_id}")
            response.raise_for_status()
            return response.json()
    except Exception:
        return None


async def list_models(url: str) -> list[dict]:
    """Get available models from /v1/models."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{url}/v1/models")
            response.raise_for_status()
            return response.json().get("data", [])
    except Exception:
        return []


async def send_chat_completion(
    url: str,
    model: str,
    messages: list[dict],
) -> ResponseResult:
    """Send via /v1/chat/completions (non-streaming) — for chat channels.

    `messages` is an OpenAI-shaped list: [{"role": "user", "content": "..."}, ...].
    `response_id` maps to the completion id (no stored-response chain — chat
    channels are stateless, conversation history lives in `messages`).
    """
    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(
            f"{url}/v1/chat/completions",
            json={"model": model, "messages": messages, "stream": False},
        )
        response.raise_for_status()
        data = response.json()
        choices = data.get("choices") or []
        content = choices[0]["message"]["content"] if choices else ""
        usage = data.get("usage") or {}
        return ResponseResult(
            response=content,
            response_id=data.get("id", ""),
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            total_tokens=usage.get("total_tokens", 0),
        )


async def stream_chat_completion(
    url: str,
    model: str,
    messages: list[dict],
    result: StreamResult | None = None,
) -> AsyncIterator[StreamEvent]:
    """Stream via /v1/chat/completions with stream=true — for chat channels."""
    async with (
        httpx.AsyncClient(timeout=120.0) as client,
        client.stream(
            "POST",
            f"{url}/v1/chat/completions",
            json={"model": model, "messages": messages, "stream": True},
        ) as response,
    ):
        response.raise_for_status()
        completion_id = ""
        async for line in response.aiter_lines():
            if not line.startswith("data: "):
                continue
            data_str = line[6:]
            if data_str == "[DONE]":
                yield StreamEvent(type="done", response_id=completion_id)
                return
            try:
                data = json.loads(data_str)
            except json.JSONDecodeError:
                continue

            if data.get("id") and not completion_id:
                completion_id = data["id"]

            choices = data.get("choices") or []
            if not choices:
                continue
            choice = choices[0]
            delta = choice.get("delta") or {}

            if "content" in delta and delta["content"]:
                yield StreamEvent(type="token", token=delta["content"])

            if choice.get("finish_reason"):
                if result is not None:
                    # Chat Completions usage isn't surfaced per-chunk; leave zeros.
                    pass
                yield StreamEvent(type="done", response_id=completion_id)
                return


async def health(url: str) -> dict | None:
    """Check agent health."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{url}/health")
            response.raise_for_status()
            return response.json()
    except Exception:
        return None


async def gateway_routes(gateway_url: str) -> list[dict]:
    """Get all routes from a gateway."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{gateway_url}/routes")
            response.raise_for_status()
            return response.json()
    except Exception:
        return []


async def gateway_health(gateway_url: str) -> dict | None:
    """Check gateway health."""
    return await health(gateway_url)
