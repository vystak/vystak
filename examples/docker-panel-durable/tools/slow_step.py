import asyncio


async def slow_step(label: str) -> str:
    """Take a slow step in a multi-step job. Call once per step, in order."""
    await asyncio.sleep(20)
    return f"step {label} complete"
