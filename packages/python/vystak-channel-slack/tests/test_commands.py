import pytest
from vystak_channel_runtime.store import MemoryChannelStore
from vystak_channel_slack.commands import NotAuthorized, Result, handle_command
from vystak_channel_slack.inviters import InviterStore


@pytest.fixture
def store():
    return MemoryChannelStore()


@pytest.fixture
def inviters(tmp_path):
    return InviterStore(str(tmp_path / "inviters.db"))


async def _cmd(store, inviters, args, user="U-inviter", agents=None, authority="inviter"):
    if agents is None:
        agents = ["weather-agent", "support-agent"]
    return await handle_command(
        cmd="/vystak",
        args=args,
        team="T",
        channel="C",
        user=user,
        agents=agents,
        route_authority=authority,
        store=store,
        inviters=inviters,
    )


async def test_route_sets_binding_when_authorized(store, inviters):
    await inviters.record_inviter("T", "C", "U-inviter")
    res = await _cmd(store, inviters, "route weather-agent")
    assert isinstance(res, Result)
    assert "weather-agent" in res.message
    assert await store.get_thread_binding("slack", "T", "C:") == "weather-agent"


async def test_route_rejects_unknown_agent(store, inviters):
    await inviters.record_inviter("T", "C", "U-inviter")
    res = await _cmd(store, inviters, "route ghost-agent", agents=["weather-agent"])
    assert "Unknown agent" in res.message
    assert await store.get_thread_binding("slack", "T", "C:") is None


async def test_route_unauthorized_rejected(store, inviters):
    await inviters.record_inviter("T", "C", "U-inviter")
    with pytest.raises(NotAuthorized):
        await _cmd(store, inviters, "route weather-agent", user="U-other", agents=["weather-agent"])


async def test_status_shows_current_binding(store, inviters):
    await store.set_thread_binding("slack", "T", "C:", "weather-agent")
    res = await _cmd(store, inviters, "status", user="U-any")
    assert "weather-agent" in res.message


async def test_unroute_removes_binding(store, inviters):
    await store.set_thread_binding("slack", "T", "C:", "weather-agent")
    await inviters.record_inviter("T", "C", "U-inviter")
    await _cmd(store, inviters, "unroute", agents=["weather-agent"])
    assert await store.get_thread_binding("slack", "T", "C:") is None


async def test_prefer_sets_user_pref(store, inviters):
    res = await _cmd(
        store, inviters, "prefer weather-agent",
        user="U-anyone", authority="anyone", agents=["weather-agent"],
    )
    assert "weather-agent" in res.message
    assert await store.get_route_pref("slack", "T:U-anyone") == "weather-agent"


async def test_authority_anyone_lets_any_user_route(store, inviters):
    res = await _cmd(
        store, inviters, "route weather-agent",
        user="U-other", authority="anyone", agents=["weather-agent"],
    )
    assert isinstance(res, Result)
    assert await store.get_thread_binding("slack", "T", "C:") == "weather-agent"
