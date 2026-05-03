"""Discord welcome + single-agent auto-bind on join."""

from __future__ import annotations

from vystak_channel_runtime.store import ChannelStore


async def auto_bind_single_agent(
    store: ChannelStore, scope_id: str, agents: list[str]
) -> None:
    """If exactly one agent is declared, set it as the route pref for the scope.

    Idempotent: if a route pref already exists, do nothing.
    """
    if len(agents) != 1:
        return
    existing = await store.get_route_pref("discord", scope_id)
    if existing is not None:
        return
    await store.set_route_pref("discord", scope_id, agents[0])


def render_welcome(message: str | None, agents: list[str]) -> str:
    """Build the welcome string posted when bot joins a guild/channel."""
    if message:
        return message
    if len(agents) == 1:
        return (
            f"Hi! I'm here with agent **{agents[0]}**. "
            "Mention me to start a conversation."
        )
    if not agents:
        return (
            "Hi! No agents are configured for this Vystak deployment yet. "
            "Use `/vystak route` to bind one."
        )
    listed = ", ".join(f"`{a}`" for a in agents)
    return (
        f"Hi! I have multiple agents available: {listed}. "
        "Use `/vystak route <agent>` to bind one to this channel."
    )
