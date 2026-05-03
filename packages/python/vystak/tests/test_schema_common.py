from vystak.schema.common import ChannelType


def test_channel_type_includes_discord():
    assert ChannelType.DISCORD == "discord"
    assert ChannelType("discord") is ChannelType.DISCORD
