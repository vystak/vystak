"""Agent API client — invoke and stream responses."""

import json
from collections.abc import AsyncIterator

import httpx


async def invoke(url: str, message: str, session_id: str) -> str:
    """Send a message and get a complete response."""
    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(
            f"{url}/invoke",
            json={"message": message, "session_id": session_id},
        )
        response.raise_for_status()
        return response.json()["response"]


async def stream(url: str, message: str, session_id: str) -> AsyncIterator[str]:
    """Send a message and stream the response token by token."""
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
                    return
                token = data.get("token", "")
                if token:
                    yield token


async def health(url: str) -> dict | None:
    """Check agent health."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{url}/health")
            response.raise_for_status()
            return response.json()
    except Exception:
        return None
