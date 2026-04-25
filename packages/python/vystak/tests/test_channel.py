import pytest
from pydantic import ValidationError
from vystak.schema.channel import Channel, Policy, SlackChannelOverride
from vystak.schema.common import ChannelType, RuntimeMode
from vystak.schema.platform import Platform
from vystak.schema.provider import Provider


@pytest.fixture()
def platform():
    docker = Provider(name="docker", type="docker")
    return Platform(name="local", type="docker", provider=docker, namespace="prod")


class TestChannel:
    def test_minimal(self, platform):
        ch = Channel(name="rest", type=ChannelType.API, platform=platform)
        assert ch.type == ChannelType.API
        assert ch.config == {}
        assert ch.runtime_mode is None

    def test_with_config(self, platform):
        ch = Channel(
            name="support-slack",
            type=ChannelType.SLACK,
            platform=platform,
            config={"bot_token_secret": "SLACK_TOKEN"},
        )
        assert ch.config["bot_token_secret"] == "SLACK_TOKEN"

    def test_routes_rejected(self, platform):
        with pytest.raises(ValidationError, match="routes.*deprecated"):
            Channel(
                name="slack",
                type=ChannelType.SLACK,
                platform=platform,
                routes=[{"match": {"slack_channel": "C0123"}, "agent": "weather-agent"}],
            )

    def test_canonical_name(self, platform):
        ch = Channel(name="slack", type=ChannelType.SLACK, platform=platform)
        assert ch.canonical_name == "slack.channels.prod"

    def test_runtime_mode(self, platform):
        ch = Channel(
            name="voice",
            type=ChannelType.VOICE,
            platform=platform,
            runtime_mode=RuntimeMode.PER_SESSION,
        )
        assert ch.runtime_mode == RuntimeMode.PER_SESSION

    def test_type_required(self, platform):
        with pytest.raises(ValidationError):
            Channel(name="test", platform=platform)

    def test_platform_required(self):
        with pytest.raises(ValidationError):
            Channel(name="test", type=ChannelType.API)

    def test_serialization_roundtrip(self, platform):
        ch = Channel(
            name="api",
            type=ChannelType.API,
            platform=platform,
            config={"cors": True},
        )
        data = ch.model_dump()
        restored = Channel.model_validate(data)
        assert restored == ch

    def test_group_policy_default(self, platform):
        ch = Channel(name="slack", type=ChannelType.SLACK, platform=platform)
        assert ch.group_policy is Policy.OPEN

    def test_dm_policy_default(self, platform):
        ch = Channel(name="slack", type=ChannelType.SLACK, platform=platform)
        assert ch.dm_policy is Policy.OPEN

    def test_slack_state_auto_set(self, platform):
        ch = Channel(name="slack", type=ChannelType.SLACK, platform=platform)
        assert ch.state is not None
        assert ch.state.type == "sqlite"

    def test_non_slack_state_not_set(self, platform):
        ch = Channel(name="api", type=ChannelType.API, platform=platform)
        assert ch.state is None


class TestSlackChannelOverride:
    def test_minimal(self):
        override = SlackChannelOverride()
        assert override.name == ""
        assert override.agent is None
        assert override.require_mention is False

    def test_with_system_prompt(self):
        override = SlackChannelOverride(system_prompt="Be concise.")
        assert override.system_prompt == "Be concise."
