"""Call the peer time-agent via Vystak's transport abstraction (NATS)."""

from vystak.transport import ask_agent


async def ask_time_agent(question: str) -> str:
    """Ask the time specialist agent a question.

    Use this tool when the user asks about the current time.
    """
    return await ask_agent("time-agent", question)
