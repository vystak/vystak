from unittest.mock import AsyncMock

from vystak_channel_runtime.store import MemoryChannelStore
from vystak_channel_slack.inviters import InviterStore
from vystak_channel_slack.welcome import on_member_joined, render_welcome


def test_render_welcome_substitutes_agent_mentions():
    out = render_welcome(
        template="Routes: {agent_mentions}",
        agents=["weather-agent", "support-agent"],
    )
    assert "weather-agent" in out and "support-agent" in out


async def test_on_member_joined_records_inviter_and_posts_welcome(tmp_path):
    store = MemoryChannelStore()
    inviters = InviterStore(str(tmp_path / "inviters.db"))
    slack = AsyncMock()
    await on_member_joined(
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
        inviters=inviters,
    )
    assert await inviters.get_inviter("T", "C") == "U-inviter"
    assert await store.get_thread_binding("slack", "T", "C:") == "weather-agent"
    slack.chat_postMessage.assert_called()


async def test_no_auto_bind_when_multiple_agents(tmp_path):
    store = MemoryChannelStore()
    inviters = InviterStore(str(tmp_path / "inviters.db"))
    slack = AsyncMock()
    await on_member_joined(
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
        inviters=inviters,
    )
    assert await store.get_thread_binding("slack", "T", "C:") is None


async def test_event_for_other_user_skipped(tmp_path):
    store = MemoryChannelStore()
    inviters = InviterStore(str(tmp_path / "inviters.db"))
    slack = AsyncMock()
    await on_member_joined(
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
        inviters=inviters,
    )
    assert await inviters.get_inviter("T", "C") is None
    slack.chat_postMessage.assert_not_called()
