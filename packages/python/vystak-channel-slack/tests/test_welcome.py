from unittest.mock import MagicMock

from vystak_channel_slack.welcome import on_member_joined, render_welcome


def test_render_welcome_substitutes_agent_mentions():
    out = render_welcome(
        template="Routes: {agent_mentions}",
        agents=["weather-agent", "support-agent"],
    )
    assert "weather-agent" in out and "support-agent" in out


def test_on_member_joined_records_inviter_and_posts_welcome():
    store = MagicMock()
    slack = MagicMock()
    on_member_joined(
        bot_user_id="B",
        joined_user_id="B",
        inviter_id="U-inviter",
        team="T",
        channel="C",
        agents=["weather-agent"],
        single_agent_auto_bind=True,
        welcome_template="hi {agent_mentions}",
        slack=slack,
        store=store,
    )
    store.record_inviter.assert_called_once_with("T", "C", "U-inviter")
    store.set_channel_binding.assert_called_once()
    slack.chat_postMessage.assert_called()


def test_no_auto_bind_when_multiple_agents():
    store = MagicMock()
    slack = MagicMock()
    on_member_joined(
        bot_user_id="B",
        joined_user_id="B",
        inviter_id="U-inviter",
        team="T",
        channel="C",
        agents=["a", "b"],
        single_agent_auto_bind=True,
        welcome_template="hi {agent_mentions}",
        slack=slack,
        store=store,
    )
    store.set_channel_binding.assert_not_called()


def test_event_for_other_user_skipped():
    store = MagicMock()
    slack = MagicMock()
    on_member_joined(
        bot_user_id="B",
        joined_user_id="U-other",
        inviter_id="U-inviter",
        team="T",
        channel="C",
        agents=["a"],
        single_agent_auto_bind=True,
        welcome_template="hi {agent_mentions}",
        slack=slack,
        store=store,
    )
    store.record_inviter.assert_not_called()
    slack.chat_postMessage.assert_not_called()
