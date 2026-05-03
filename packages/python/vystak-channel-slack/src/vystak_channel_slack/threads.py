"""On-message routing policy for Slack threads.

Decides whether a non-mention message in a Slack channel should be
forwarded to an agent bound to that thread. Pure function — the caller
hands in everything (event facts + a store) and gets back the agent
name or None.

Mirrors the resolver.py pattern: small, pure, unit-tested in isolation;
the slack-bolt runtime in server_template.py just calls it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from vystak_channel_runtime.store import ChannelStore


async def route_thread_message(
    *,
    is_dm: bool,
    require_explicit_mention: bool,
    team: str,
    channel: str,
    thread_ts: str | None,
    text: str,
    bot_user_id: str,
    store: ChannelStore,
) -> str | None:
    """Return the agent name to forward to, or None to ignore the message.

    None on any of:
        - DMs (the DM branch handles its own routing)
        - thread.require_explicit_mention=True (opt-out)
        - message is not in a thread (no thread_ts)
        - bot is directly mentioned in text (on_mention will handle it;
          avoid double-reply)
        - thread is not bound to any agent
    """
    if is_dm or require_explicit_mention:
        return None
    if not thread_ts:
        return None
    if bot_user_id and f"<@{bot_user_id}>" in text:
        return None
    return await store.get_thread_binding("slack", team, f"{channel}:{thread_ts}")


def register(
    app: Any,
    config: dict,
    store: ChannelStore,
) -> None:
    """Register thread routing as a no-op hook (routing handled in message events).

    The thread routing logic is called directly by SlackChannelRuntime.handle_event
    (via the parent ChannelRuntime). This register() exists to satisfy the
    symmetric register() contract; actual bolt event wiring lives in runtime.py.
    """
    # Thread routing is handled by the ChannelRuntime base class which calls
    # store.get_thread_binding via route(). No additional bolt event registration
    # is needed here — the message handler in runtime.start() already calls
    # handle_event which flows into the store lookups.
    pass  # intentional no-op
