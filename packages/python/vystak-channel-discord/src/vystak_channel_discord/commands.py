"""/vystak slash-command handlers — pure store mutations, easy to unit-test."""

from __future__ import annotations

from vystak_channel_runtime.store import ChannelStore


async def handle_route(
    store: ChannelStore, scope_id: str, thread_id: str, agent: str
) -> str:
    await store.set_thread_binding("discord", scope_id, thread_id, agent)
    return f"Routed thread to agent **{agent}**."


async def handle_unroute(
    store: ChannelStore, scope_id: str, thread_id: str
) -> str:
    await store.delete_thread_binding("discord", scope_id, thread_id)
    return "Thread routing removed."


async def handle_prefer(
    store: ChannelStore, scope_id: str, agent: str
) -> str:
    await store.set_route_pref("discord", scope_id, agent)
    return f"Preference set: agent **{agent}**."


async def handle_unprefer(
    store: ChannelStore, scope_id: str
) -> str:
    await store.delete_route_pref("discord", scope_id)
    return "Preference removed."


async def handle_status(
    store: ChannelStore, scope_id: str
) -> str:
    bindings = await store.list_thread_bindings("discord", scope_id)
    pref = await store.get_route_pref("discord", scope_id)
    parts = []
    if pref:
        parts.append(f"Default agent: **{pref}**")
    if bindings:
        lines = "\n".join(f"- `{b.thread_id}` → **{b.agent_name}**" for b in bindings)
        parts.append(f"Thread bindings:\n{lines}")
    return "\n\n".join(parts) or "No bindings configured for this scope."
