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


async def invoke(url: str, message: str, session_id: str) -> InvokeResult:
    """Send a message and get a complete response with usage info."""
    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(
            f"{url}/invoke",
            json={"message": message, "session_id": session_id},
        )
        response.raise_for_status()
        data = response.json()
        usage = data.get("usage") or {}
        return InvokeResult(
            response=data["response"],
            session_id=data["session_id"],
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            total_tokens=usage.get("total_tokens", 0),
        )


async def stream_events(
    url: str, message: str, session_id: str, result: StreamResult | None = None
) -> AsyncIterator[StreamEvent]:
    """Stream all events — tokens, tool calls, tool results, done."""
    async with httpx.AsyncClient(timeout=120.0) as client:
        async with client.stream(
            "POST",
            f"{url}/stream",
            json={"message": message, "session_id": session_id},
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data_str = line[6:]
                try:
                    data = json.loads(data_str)
                except json.JSONDecodeError:
                    continue

                event_type = data.get("type", "")

                if event_type == "token":
                    yield StreamEvent(type="token", token=data.get("token", ""))

                elif event_type == "tool_call_start":
                    yield StreamEvent(type="tool_call_start", tool=data.get("tool", ""))

                elif event_type == "tool_result":
                    yield StreamEvent(
                        type="tool_result",
                        tool=data.get("tool", ""),
                        result=data.get("result", ""),
                    )

                elif event_type == "done" or data.get("done"):
                    if result is not None:
                        usage = data.get("usage", {})
                        result.input_tokens = usage.get("input_tokens", 0)
                        result.output_tokens = usage.get("output_tokens", 0)
                        result.total_tokens = usage.get("total_tokens", 0)
                    yield StreamEvent(type="done", usage=data.get("usage"))
                    return

                # Backward compat: old servers send {"token": "..."} without "type"
                elif "token" in data and data["token"]:
                    yield StreamEvent(type="token", token=data["token"])

                elif data.get("done"):
                    if result is not None:
                        usage = data.get("usage", {})
                        result.input_tokens = usage.get("input_tokens", 0)
                        result.output_tokens = usage.get("output_tokens", 0)
                        result.total_tokens = usage.get("total_tokens", 0)
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
