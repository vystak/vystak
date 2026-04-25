"""Tests for threads.py — the on-message routing policy."""

from __future__ import annotations

from vystak_channel_slack.threads import route_thread_message


class _FakeStore:
    """Minimal store stub exposing only thread_binding()."""

    def __init__(self, bindings: dict[tuple[str, str, str], str] | None = None):
        self._b = bindings or {}

    def thread_binding(self, team: str, channel: str, thread_ts: str) -> str | None:
        return self._b.get((team, channel, thread_ts))


def _call(**overrides):
    """Build a route_thread_message call with sensible defaults."""
    args = {
        "is_dm": False,
        "require_explicit_mention": False,
        "team": "T1",
        "channel": "C1",
        "thread_ts": "1700.111",
        "text": "hey",
        "bot_user_id": "UBOT",
        "store": _FakeStore({("T1", "C1", "1700.111"): "weather-agent"}),
    }
    args.update(overrides)
    return route_thread_message(**args)


def test_routes_to_bound_agent_when_thread_is_bound():
    assert _call() == "weather-agent"


def test_returns_none_for_dm():
    assert _call(is_dm=True) is None


def test_returns_none_when_explicit_mention_required():
    assert _call(require_explicit_mention=True) is None


def test_returns_none_when_no_thread_ts():
    assert _call(thread_ts=None) is None


def test_returns_none_when_text_mentions_bound_bot():
    """on_mention will already handle these — avoid double-reply."""
    assert _call(text="hi <@UBOT> please help") is None


def test_text_mentioning_other_agent_still_routes_to_bound_agent():
    """Sticky binding: <@U_other> in text doesn't release the thread."""
    assert _call(text="<@U_OTHER> what about you?") == "weather-agent"


def test_returns_none_when_thread_unbound():
    assert _call(store=_FakeStore({})) is None


def test_empty_bot_user_id_does_not_short_circuit():
    """A misconfigured BOT_USER_ID="" must not block all routing."""
    # text contains "<@>" which would never appear from real Slack; this just
    # checks the empty-string guard.
    result = _call(bot_user_id="", text="hello <@> world")
    assert result == "weather-agent"
