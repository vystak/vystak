"""Call the peer weather-agent via Vystak's transport abstraction (NATS)."""

from vystak.transport import ask_agent


async def ask_weather_agent(question: str) -> str:
    """Ask the weather specialist agent a question.

    Use this tool when the user asks about weather conditions.
    """
    return await ask_agent("weather-agent", question)
