"""Delegate a weather question to the peer weather-agent via A2A."""

from vystak.transport import ask_agent


async def ask_weather_agent(question: str) -> str:
    """Ask the weather specialist agent a question.

    Use this tool whenever the user asks about weather, temperature,
    forecast, climate, or related conditions. Pass the user's full
    question through verbatim and return the agent's reply without
    paraphrasing.
    """
    return await ask_agent("weather-agent", question)
