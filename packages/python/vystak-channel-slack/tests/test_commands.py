import pytest
from unittest.mock import MagicMock
from vystak_channel_slack.commands import handle_command, NotAuthorized, Result


@pytest.fixture
def store():
    s = MagicMock()
    s.inviter.return_value = "U-inviter"
    return s


def test_route_sets_binding_when_authorized(store):
    res = handle_command(
        cmd="/vystak", args="route weather-agent",
        team="T", channel="C", user="U-inviter",
        agents=["weather-agent", "support-agent"],
        route_authority="inviter",
        store=store,
    )
    assert isinstance(res, Result)
    assert "weather-agent" in res.message
    store.set_channel_binding.assert_called_once_with(
        "T", "C", "weather-agent", "U-inviter"
    )


def test_route_rejects_unknown_agent(store):
    res = handle_command(
        cmd="/vystak", args="route ghost-agent",
        team="T", channel="C", user="U-inviter",
        agents=["weather-agent"], route_authority="inviter", store=store,
    )
    assert "Unknown agent" in res.message
    store.set_channel_binding.assert_not_called()


def test_route_unauthorized_rejected(store):
    with pytest.raises(NotAuthorized):
        handle_command(
            cmd="/vystak", args="route weather-agent",
            team="T", channel="C", user="U-other",
            agents=["weather-agent"],
            route_authority="inviter", store=store,
        )


def test_status_shows_current_binding(store):
    store.channel_binding.return_value = "weather-agent"
    res = handle_command(
        cmd="/vystak", args="status",
        team="T", channel="C", user="U-any",
        agents=["weather-agent"],
        route_authority="inviter", store=store,
    )
    assert "weather-agent" in res.message


def test_unroute_removes_binding(store):
    res = handle_command(
        cmd="/vystak", args="unroute",
        team="T", channel="C", user="U-inviter",
        agents=["weather-agent"],
        route_authority="inviter", store=store,
    )
    store.unbind_channel.assert_called_once_with("T", "C")


def test_prefer_sets_user_pref(store):
    res = handle_command(
        cmd="/vystak", args="prefer weather-agent",
        team="T", channel="C", user="U-anyone",
        agents=["weather-agent"],
        route_authority="inviter", store=store,
    )
    store.set_user_pref.assert_called_once_with(
        "T", "U-anyone", "weather-agent"
    )


def test_authority_anyone_lets_any_user_route(store):
    res = handle_command(
        cmd="/vystak", args="route weather-agent",
        team="T", channel="C", user="U-other",
        agents=["weather-agent"],
        route_authority="anyone", store=store,
    )
    assert isinstance(res, Result)
    store.set_channel_binding.assert_called_once()
