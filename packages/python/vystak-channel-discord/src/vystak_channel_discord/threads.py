"""Discord native-thread + forum-channel helpers."""

from __future__ import annotations


def is_thread_channel(channel_type: str | None) -> bool:
    return channel_type == "thread"


def is_forum_channel(channel_type: str | None) -> bool:
    return channel_type == "forum"


def should_respond_in_thread(
    *,
    require_explicit_mention: bool,
    mentions_bot: bool,
    is_in_thread: bool,
) -> bool:
    """Apply the thread.require_explicit_mention policy.

    If the message is not in a thread, this helper returns True; the runtime's
    main authorize pipeline still applies. Inside a thread:
      * require_explicit_mention=False -> always True (follow the thread)
      * require_explicit_mention=True  -> only when the bot is mentioned
    """
    if not is_in_thread:
        return True
    if not require_explicit_mention:
        return True
    return mentions_bot
