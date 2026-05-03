"""Discord native-thread + forum-channel helpers."""

from __future__ import annotations

from typing import Any


def _type_name(channel_type: Any) -> str:
    """Coerce discord.ChannelType enum or plain string to its name string."""
    if channel_type is None:
        return ""
    return getattr(channel_type, "name", str(channel_type))


def is_thread_channel(channel_type: Any) -> bool:
    """Return True for any thread-like discord channel type.

    Accepts a `discord.ChannelType` enum (production), a plain string (tests),
    or anything with a `.name` attribute. discord.py's enum members for
    threads are `public_thread`, `private_thread`, `news_thread`. The plain
    string `"thread"` is also accepted for test stubs.
    """
    return _type_name(channel_type) in {
        "public_thread", "private_thread", "news_thread", "thread",
    }


def is_forum_channel(channel_type: Any) -> bool:
    """Return True for forum-like discord channel types (forum + media).

    Accepts the same input shapes as `is_thread_channel`.
    """
    return _type_name(channel_type) in {"forum", "media"}


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
