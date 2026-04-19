import os
import uuid

import httpx

TIME_AGENT_URL = os.environ.get(
    "TIME_AGENT_URL", "http://vystak-time-agent:8000"
).rstrip("/")


async def ask_time_agent(question: str) -> str:
    """Ask the time specialist agent for the current time.

    Use this when the user asks about the time. The time agent returns
    UTC-based answers.
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
            resp = await client.post(f"{TIME_AGENT_URL}/a2a", json=payload)
            data = resp.json()
    except Exception as e:
        return f"Could not reach time agent at {TIME_AGENT_URL}: {e}"

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
    return "".join(texts) or "No response from time agent"
