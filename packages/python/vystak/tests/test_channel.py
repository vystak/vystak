import pytest
from pydantic import ValidationError
from vystak.schema.channel import Channel, RouteRule
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
        assert ch.routes == []
        assert ch.runtime_mode is None

    def test_with_config(self, platform):
        ch = Channel(
            name="support-slack",
            type=ChannelType.SLACK,
            platform=platform,
            config={"bot_token_secret": "SLACK_TOKEN"},
        )
        assert ch.config["bot_token_secret"] == "SLACK_TOKEN"

    def test_with_routes(self, platform):
        ch = Channel(
            name="slack",
            type=ChannelType.SLACK,
            platform=platform,
            routes=[
                RouteRule(match={"slack_channel": "C0123"}, agent="weather-agent"),
                RouteRule(match={"slack_channel": "C0456"}, agent="time-agent"),
            ],
        )
        assert len(ch.routes) == 2
        assert ch.routes[0].agent == "weather-agent"

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
            routes=[RouteRule(match={}, agent="bot")],
        )
        data = ch.model_dump()
        restored = Channel.model_validate(data)
        assert restored == ch


class TestRouteRule:
    def test_minimal(self):
        rule = RouteRule(agent="bot")
        assert rule.agent == "bot"
        assert rule.match == {}

    def test_with_match(self):
        rule = RouteRule(match={"slack_channel": "C0123"}, agent="weather-agent")
        assert rule.match["slack_channel"] == "C0123"

    def test_agent_required(self):
        with pytest.raises(ValidationError):
            RouteRule(match={"x": "y"})
