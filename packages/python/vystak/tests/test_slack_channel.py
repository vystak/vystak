import pytest
from pydantic import ValidationError
from vystak.schema.channel import SlackChannel
from vystak.schema.gateway import ChannelProvider, Gateway
from vystak.schema.provider import Provider


@pytest.fixture()
def slack_provider():
    docker = Provider(name="docker", type="docker")
    gw = Gateway(name="main", provider=docker)
    return ChannelProvider(
        name="internal-slack",
        type="slack",
        gateway=gw,
        config={"bot_token": "xoxb-test", "app_token": "xapp-test"},
    )


class TestSlackChannel:
    def test_create_minimal(self, slack_provider):
        ch = SlackChannel(name="support", provider=slack_provider)
        assert ch.channels == []
        assert ch.listen == "mentions"
        assert ch.threads is True
        assert ch.dm is True

    def test_create_full(self, slack_provider):
        ch = SlackChannel(
            name="support",
            provider=slack_provider,
            channels=["#support", "#help"],
            listen="messages",
            threads=False,
            dm=False,
        )
        assert ch.channels == ["#support", "#help"]
        assert ch.listen == "messages"
        assert ch.threads is False
        assert ch.dm is False

    def test_provider_required(self):
        with pytest.raises(ValidationError):
            SlackChannel(name="support")

    def test_serialization_roundtrip(self, slack_provider):
        ch = SlackChannel(
            name="support", provider=slack_provider, channels=["#support"], listen="mentions"
        )
        data = ch.model_dump()
        restored = SlackChannel.model_validate(data)
        assert restored == ch
