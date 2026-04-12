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


@dataclass
class StreamResult:
    """Collected after streaming completes."""
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


async def stream(url: str, message: str, session_id: str, result: StreamResult | None = None) -> AsyncIterator[str]:
    """Send a message and stream the response token by token.

    Pass a StreamResult instance to collect usage info after streaming completes.
    """
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
                if data.get("done"):
                    if result is not None:
                        usage = data.get("usage", {})
                        result.input_tokens = usage.get("input_tokens", 0)
                        result.output_tokens = usage.get("output_tokens", 0)
                        result.total_tokens = usage.get("total_tokens", 0)
                    return
                token = data.get("token", "")
                if token:
                    yield token


async def invoke_with_usage(url: str, message: str, session_id: str) -> InvokeResult:
    """Invoke and return full result with token usage."""
    return await invoke(url, message, session_id)


async def health(url: str) -> dict | None:
    """Check agent health."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{url}/health")
            response.raise_for_status()
            return response.json()
    except Exception:
        return None
