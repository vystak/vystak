"""Agent API client — invoke and stream responses."""

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass

import httpx


@dataclass
class InvokeResult:
    response: str
    session_id: str
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
    type: str  # "token", "tool_call_start", "tool_result", "done"
    token: str = ""
    tool: str = ""
    result: str = ""
    usage: dict | None = None


async def invoke(url: str, message: str, session_id: str, model: str = "") -> InvokeResult:
    """Send a message and get a complete response with usage info."""
    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(
            f"{url}/v1/chat/completions",
            json={
                "model": model,
                "messages": [{"role": "user", "content": message}],
                "stream": False,
                "session_id": session_id,
            },
        )
        response.raise_for_status()
        data = response.json()
        content = data["choices"][0]["message"]["content"] or ""
        usage = data.get("usage") or {}
        return InvokeResult(
            response=content,
            session_id=session_id,
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            total_tokens=usage.get("total_tokens", 0),
        )


async def stream_events(
    url: str, message: str, session_id: str, result: StreamResult | None = None, model: str = ""
) -> AsyncIterator[StreamEvent]:
    """Stream all events — tokens, tool calls, tool results, done."""
    async with httpx.AsyncClient(timeout=120.0) as client:
        async with client.stream(
            "POST",
            f"{url}/v1/chat/completions",
            json={
                "model": model,
                "messages": [{"role": "user", "content": message}],
                "stream": True,
                "session_id": session_id,
            },
        ) as response:
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

                choices = data.get("choices", [])
                if not choices:
                    continue
                delta = choices[0].get("delta", {})
                finish_reason = choices[0].get("finish_reason")

                # Extension events (tool calls, sub-agent activity)
                x = data.get("x_agentstack")
                if x:
                    event_type = x.get("type", "")
                    if event_type == "tool_call_start":
                        yield StreamEvent(type="tool_call_start", tool=x.get("tool", ""))
                    elif event_type == "tool_result":
                        yield StreamEvent(type="tool_result", tool=x.get("tool", ""), result=x.get("result", ""))
                    continue

                content = delta.get("content")
                if content:
                    yield StreamEvent(type="token", token=content)

                if finish_reason == "stop":
                    yield StreamEvent(type="done")
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


async def list_models(url: str) -> list[dict]:
    """List available models from the agent."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{url}/v1/models")
            response.raise_for_status()
            return response.json().get("data", [])
    except Exception:
        return []


async def gateway_routes(gateway_url: str) -> list[dict]:
    """Get all routes from a gateway — discovers deployed agents."""
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
