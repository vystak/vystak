import json
import uuid
from urllib.request import urlopen, Request


WEATHER_AGENT_URL = "http://agentstack-weather-agent:8000/a2a"


def ask_weather_agent(question: str) -> str:
    """Ask the weather specialist agent a question via A2A protocol.

    Use this tool when the user asks about weather in any city.
    Pass the weather question as-is to the weather agent.
    """
    try:
        payload = json.dumps({
            "jsonrpc": "2.0",
            "method": "tasks/send",
            "id": 1,
            "params": {
                "id": str(uuid.uuid4()),
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

        # Extract the agent's response from A2A result
        task_result = result.get("result", {})
        status = task_result.get("status", {})
        message = status.get("message", {})
        parts = message.get("parts", [])

        texts = [p.get("text", "") for p in parts if "text" in p]
        return " ".join(texts) if texts else "No response from weather agent"

    except Exception as e:
        return f"Could not reach weather agent: {e}"
