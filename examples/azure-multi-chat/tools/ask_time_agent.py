"""Ask the peer time-agent for the current time via Vystak's transport abstraction."""

from vystak.transport import ask_agent


async def ask_time_agent(question: str) -> str:
    """Ask the time specialist agent a question.

    Use this tool when the user asks about the current time.
    """
    return await ask_agent("time-agent", question)
