import pytest
from pydantic import ValidationError
from vystak.schema.agent import Agent
from vystak.schema.channel import (
    Channel,
    ChannelType,
    Policy,
    SlackChannelOverride,
)
from vystak.schema.model import Model
from vystak.schema.platform import Platform
from vystak.schema.provider import Provider
from vystak.schema.secret import Secret


def _make_agent(name: str) -> Agent:
    return Agent(
        name=name,
        model=Model(
            name="m",
            provider=Provider(name="anthropic", type="anthropic"),
            model_name="claude-sonnet-4-20250514",
        ),
        platform=Platform(
            name="local",
            type="docker",
            provider=Provider(name="docker", type="docker"),
        ),
    )


def test_minimal_slack_channel_loads():
    weather = _make_agent("weather-agent")
    ch = Channel(
        name="slack-main",
        type=ChannelType.SLACK,
        platform=weather.platform,
        secrets=[
            Secret(name="SLACK_BOT_TOKEN"),
            Secret(name="SLACK_APP_TOKEN"),
        ],
        agents=[weather],
    )
    # Defaults
    assert ch.group_policy is Policy.OPEN
    assert ch.dm_policy is Policy.OPEN
    assert ch.reply_to_mode == "first"
    assert ch.welcome_on_invite is True
    assert ch.state is not None
    assert ch.state.type == "sqlite"
    assert ch.state.path == "/data/channel-state.db"


def test_channel_overrides_with_agent_pin():
    weather = _make_agent("weather-agent")
    support = _make_agent("support-agent")
    ch = Channel(
        name="slack-main",
        type=ChannelType.SLACK,
        platform=weather.platform,
        secrets=[
            Secret(name="SLACK_BOT_TOKEN"),
            Secret(name="SLACK_APP_TOKEN"),
        ],
        agents=[weather, support],
        channel_overrides={
            "C12345678": SlackChannelOverride(
                agent=support,
                system_prompt="Triage first.",
                tools=["create_ticket"],
            ),
        },
        default_agent=weather,
    )
    assert ch.channel_overrides["C12345678"].agent is support


def test_routes_field_rejected_with_migration_error():
    weather = _make_agent("weather-agent")
    with pytest.raises(ValidationError, match="routes.*deprecated"):
        Channel(
            name="slack-main",
            type=ChannelType.SLACK,
            platform=weather.platform,
            secrets=[Secret(name="SLACK_BOT_TOKEN"),
                     Secret(name="SLACK_APP_TOKEN")],
            agents=[weather],
            routes=[{"match": {"dm": True}, "agent": "weather-agent"}],
        )


def test_policy_enum_values():
    assert Policy.OPEN.value == "open"
    assert Policy.ALLOWLIST.value == "allowlist"
    assert Policy.DISABLED.value == "disabled"


def test_default_agent_must_be_in_agents_list():
    weather = _make_agent("weather-agent")
    other = _make_agent("other-agent")
    with pytest.raises(ValidationError, match="default_agent.*must be in agents"):
        Channel(
            name="slack-main",
            type=ChannelType.SLACK,
            platform=weather.platform,
            secrets=[Secret(name="SLACK_BOT_TOKEN"),
                     Secret(name="SLACK_APP_TOKEN")],
            agents=[weather],
            default_agent=other,
        )
