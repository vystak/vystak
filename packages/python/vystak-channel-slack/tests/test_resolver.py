import pytest
from unittest.mock import MagicMock
from vystak_channel_slack.resolver import Event, ResolverConfig, resolve


@pytest.fixture
def store():
    s = MagicMock()
    s.channel_binding.return_value = None
    s.user_pref.return_value = None
    return s


@pytest.fixture
def cfg():
    return ResolverConfig(
        agents=["weather-agent", "support-agent"],
        group_policy="open", dm_policy="open",
        allow_from=[], allow_bots=False,
        channel_overrides={},
        default_agent="weather-agent",
        ai_fallback=None,
    )


def _evt(**kw):
    base = dict(team="T", channel="C", user="U", text="hi",
                is_dm=False, is_bot=False, channel_name="general")
    base.update(kw)
    return Event(**base)


def test_dm_with_user_pref_uses_pref(cfg, store):
    store.user_pref.return_value = "support-agent"
    assert resolve(_evt(is_dm=True), cfg, store) == "support-agent"


def test_dm_without_pref_uses_default(cfg, store):
    assert resolve(_evt(is_dm=True), cfg, store) == "weather-agent"


def test_channel_override_pin_short_circuits(cfg, store):
    cfg.channel_overrides = {"C": MagicMock(agent="support-agent")}
    assert resolve(_evt(), cfg, store) == "support-agent"


def test_runtime_binding_used_when_no_override(cfg, store):
    store.channel_binding.return_value = "support-agent"
    assert resolve(_evt(), cfg, store) == "support-agent"


def test_falls_through_to_default(cfg, store):
    assert resolve(_evt(), cfg, store) == "weather-agent"


def test_returns_none_when_no_default(cfg, store):
    cfg.default_agent = None
    assert resolve(_evt(), cfg, store) is None


def test_disabled_group_policy_drops(cfg, store):
    cfg.group_policy = "disabled"
    assert resolve(_evt(), cfg, store) is None


def test_disabled_dm_policy_drops(cfg, store):
    cfg.dm_policy = "disabled"
    assert resolve(_evt(is_dm=True), cfg, store) is None


def test_allowlist_policy_with_unlisted_user_drops(cfg, store):
    cfg.group_policy = "allowlist"
    cfg.allow_from = ["U-other"]
    assert resolve(_evt(), cfg, store) is None


def test_allowlist_policy_with_listed_user_passes(cfg, store):
    cfg.group_policy = "allowlist"
    cfg.allow_from = ["U"]
    assert resolve(_evt(), cfg, store) == "weather-agent"


def test_bot_message_dropped_by_default(cfg, store):
    assert resolve(_evt(is_bot=True), cfg, store) is None


def test_bot_message_allowed_when_flag_set(cfg, store):
    cfg.allow_bots = True
    assert resolve(_evt(is_bot=True), cfg, store) == "weather-agent"


def test_ai_fallback_called_before_default(cfg, store):
    cfg.ai_fallback = MagicMock(pick=MagicMock(return_value="support-agent"))
    assert resolve(_evt(), cfg, store) == "support-agent"
    cfg.ai_fallback.pick.assert_called_once()
