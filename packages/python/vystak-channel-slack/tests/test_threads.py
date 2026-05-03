"""Tests for threads.py — the on-message routing policy."""

from __future__ import annotations

from vystak_channel_runtime.store import MemoryChannelStore
from vystak_channel_slack.threads import route_thread_message


async def _make_store(
    bindings: dict[tuple[str, str, str], str] | None = None,
) -> MemoryChannelStore:
    """Build a MemoryChannelStore pre-seeded with given bindings."""
    store = MemoryChannelStore()
    if bindings:
        for (team, channel, thread_ts), agent in bindings.items():
            await store.set_thread_binding("slack", team, f"{channel}:{thread_ts}", agent)
    return store


async def _call(**overrides):
    """Build a route_thread_message call with sensible defaults."""
    default_bindings = {("T1", "C1", "1700.111"): "weather-agent"}
    store = overrides.pop("store", await _make_store(default_bindings))
    args = {
        "is_dm": False,
        "require_explicit_mention": False,
        "team": "T1",
        "channel": "C1",
        "thread_ts": "1700.111",
        "text": "hey",
        "bot_user_id": "UBOT",
        "store": store,
    }
    args.update(overrides)
    return await route_thread_message(**args)


async def test_routes_to_bound_agent_when_thread_is_bound():
    assert await _call() == "weather-agent"


async def test_returns_none_for_dm():
    assert await _call(is_dm=True) is None


async def test_returns_none_when_explicit_mention_required():
    assert await _call(require_explicit_mention=True) is None


async def test_returns_none_when_no_thread_ts():
    assert await _call(thread_ts=None) is None


async def test_returns_none_when_text_mentions_bound_bot():
    """on_mention will already handle these — avoid double-reply."""
    assert await _call(text="hi <@UBOT> please help") is None


async def test_text_mentioning_other_agent_still_routes_to_bound_agent():
    """Sticky binding: <@U_other> in text doesn't release the thread."""
    assert await _call(text="<@U_OTHER> what about you?") == "weather-agent"


async def test_returns_none_when_thread_unbound():
    empty_store = await _make_store({})
    assert await _call(store=empty_store) is None


async def test_empty_bot_user_id_does_not_short_circuit():
    """A misconfigured BOT_USER_ID="" must not block all routing."""
    # text contains "<@>" which would never appear from real Slack; this just
    # checks the empty-string guard.
    result = await _call(bot_user_id="", text="hello <@> world")
    assert result == "weather-agent"
