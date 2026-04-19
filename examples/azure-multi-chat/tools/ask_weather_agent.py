import os
import uuid

import httpx

WEATHER_AGENT_URL = os.environ.get(
    "WEATHER_AGENT_URL", "http://vystak-weather-agent:8000"
).rstrip("/")


async def ask_weather_agent(question: str) -> str:
    """Ask the weather specialist agent about weather conditions.

    Use this when the user asks anything related to weather in a city.
    Pass the weather question as-is; the weather agent has access to
    real-time weather data.
    """
    payload = {
        "jsonrpc": "2.0",
        "method": "tasks/send",
        "id": 1,
        "params": {
            "id": str(uuid.uuid4()),
            "message": {"role": "user", "parts": [{"text": question}]},
        },
    }
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(f"{WEATHER_AGENT_URL}/a2a", json=payload)
            data = resp.json()
    except Exception as e:
        return f"Could not reach weather agent at {WEATHER_AGENT_URL}: {e}"

    result = data.get("result", {}) or {}
    message = (result.get("status") or {}).get("message") or {}
    parts = message.get("parts", []) or []
    texts: list[str] = []
    for part in parts:
        if not isinstance(part, dict):
            continue
        if part.get("type") and part.get("type") != "text":
            continue
        text = part.get("text", "")
        if isinstance(text, str):
            texts.append(text)
        elif isinstance(text, list):
            for block in text:
                if isinstance(block, dict) and block.get("type") == "text":
                    texts.append(block.get("text", ""))
    return "".join(texts) or "No response from weather agent"
