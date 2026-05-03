"""Tests for the Discord channel plugin."""

import json

from vystak.schema.channel import Channel
from vystak.schema.common import ChannelType
from vystak.schema.platform import Platform
from vystak.schema.provider import Provider
from vystak_channel_discord.plugin import DiscordChannelPlugin


def _platform():
    docker = Provider(name="docker", type="docker")
    return Platform(name="local", type="docker", provider=docker)


def _channel():
    return Channel(name="discord-prod", type=ChannelType.DISCORD, platform=_platform(), agents=[])


def test_plugin_emits_no_python_source():
    out = DiscordChannelPlugin().generate_code(_channel(), resolved_routes={})
    for path in out.files:
        assert not path.endswith(".py"), f"unexpected python source: {path}"
    assert "Dockerfile" in out.files
    assert "channel_config.json" in out.files
    assert "routes.json" in out.files


def test_entrypoint_is_module_form():
    out = DiscordChannelPlugin().generate_code(_channel(), resolved_routes={})
    assert out.entrypoint == "python -m vystak_channel_discord"


def test_channel_config_includes_channel_type_and_protocol():
    out = DiscordChannelPlugin().generate_code(_channel(), resolved_routes={})
    cfg = json.loads(out.files["channel_config.json"])
    assert cfg["channel_type"] == "discord"
    assert cfg["agent_protocol"] == "a2a-turn"
