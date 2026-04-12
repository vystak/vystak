import json
import uuid
from urllib.request import urlopen, Request

from langgraph.config import get_stream_writer


WEATHER_AGENT_URL = "http://agentstack-weather-agent:8000/a2a"


def ask_weather_agent(question: str) -> str:
    """Ask the weather specialist agent a question via A2A protocol.

    Use this tool when the user asks about weather in any city.
    Pass the weather question as-is to the weather agent.
    """
    writer = get_stream_writer()
    task_id = str(uuid.uuid4())

    # Signal tool start
    writer({
        "type": "agent_call",
        "agent": "weather-agent",
        "status": "started",
        "question": question,
    })

    try:
        # Use streaming A2A (tasks/sendSubscribe) via SSE
        payload = json.dumps({
            "jsonrpc": "2.0",
            "method": "tasks/sendSubscribe",
            "id": 1,
            "params": {
                "id": task_id,
                "message": {
                    "role": "user",
                    "parts": [{"text": question}],
                },
            },
        }).encode()

        req = Request(
            WEATHER_AGENT_URL,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
            },
        )

        full_response = ""

        with urlopen(req, timeout=60) as response:
            buffer = ""
            for line_bytes in response:
                line = line_bytes.decode("utf-8", errors="replace").rstrip("\n\r")

                if line.startswith("data: "):
                    data_str = line[6:]
                    try:
                        event = json.loads(data_str)

                        # Stream artifact tokens to the client
                        if "artifact" in event:
                            parts = event["artifact"].get("parts", [])
                            for part in parts:
                                token = part.get("text", "")
                                if token:
                                    full_response += token
                                    writer({
                                        "type": "agent_token",
                                        "agent": "weather-agent",
                                        "token": token,
                                    })

                        # Stream status updates
                        if "status" in event:
                            state = event["status"].get("state", "")
                            if state == "completed":
                                msg = event["status"].get("message", {})
                                parts = msg.get("parts", [])
                                for part in parts:
                                    text = part.get("text", "")
                                    if text and not full_response:
                                        full_response = text

                    except json.JSONDecodeError:
                        pass

        if not full_response:
            # Fallback: try sync tasks/send
            full_response = _sync_fallback(question, task_id)

        writer({
            "type": "agent_call",
            "agent": "weather-agent",
            "status": "completed",
            "response_preview": full_response[:100],
        })

        return full_response

    except Exception as e:
        writer({
            "type": "agent_call",
            "agent": "weather-agent",
            "status": "failed",
            "error": str(e),
        })
        # Fallback to sync
        try:
            return _sync_fallback(question, str(uuid.uuid4()))
        except Exception as e2:
            return f"Could not reach weather agent: {e2}"


def _sync_fallback(question: str, task_id: str) -> str:
    """Fallback to synchronous A2A call."""
    payload = json.dumps({
        "jsonrpc": "2.0",
        "method": "tasks/send",
        "id": 1,
        "params": {
            "id": task_id,
            "message": {
                "role": "user",
                "parts": [{"text": question}],
            },
        },
    }).encode()

    req = Request(
        WEATHER_AGENT_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
    )

    with urlopen(req, timeout=30) as response:
        result = json.loads(response.read())

    task_result = result.get("result", {})
    status = task_result.get("status", {})
    message = status.get("message", {})
    parts = message.get("parts", [])
    texts = [p.get("text", "") for p in parts if "text" in p]
    return " ".join(texts) if texts else "No response from weather agent"
