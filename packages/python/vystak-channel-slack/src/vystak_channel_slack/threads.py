"""On-message routing policy for Slack threads.

Decides whether a non-mention message in a Slack channel should be
forwarded to an agent bound to that thread. Pure function — the caller
hands in everything (event facts + a store) and gets back the agent
name or None.

Mirrors the resolver.py pattern: small, pure, unit-tested in isolation;
the slack-bolt runtime in server_template.py just calls it.
"""

from __future__ import annotations

from typing import Protocol


class _ThreadStore(Protocol):
    def thread_binding(
        self, team: str, channel: str, thread_ts: str
    ) -> str | None: ...


def route_thread_message(
    *,
    is_dm: bool,
    require_explicit_mention: bool,
    team: str,
    channel: str,
    thread_ts: str | None,
    text: str,
    bot_user_id: str,
    store: _ThreadStore,
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
    return store.thread_binding(team, channel, thread_ts)
