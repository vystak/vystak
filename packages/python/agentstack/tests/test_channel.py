import pytest
from pydantic import ValidationError

from agentstack.schema.channel import Channel
from agentstack.schema.common import ChannelType


class TestChannel:
    def test_api(self):
        ch = Channel(name="rest", type=ChannelType.API)
        assert ch.type == ChannelType.API
        assert ch.config == {}

    def test_slack_with_config(self):
        ch = Channel(name="support-slack", type=ChannelType.SLACK, config={"channel": "#support", "bot_token_secret": "SLACK_TOKEN"})
        assert ch.type == ChannelType.SLACK
        assert ch.config["channel"] == "#support"

    def test_type_required(self):
        with pytest.raises(ValidationError):
            Channel(name="test")

    def test_serialization_roundtrip(self):
        ch = Channel(name="api", type=ChannelType.API, config={"cors": True})
        data = ch.model_dump()
        restored = Channel.model_validate(data)
        assert restored == ch
