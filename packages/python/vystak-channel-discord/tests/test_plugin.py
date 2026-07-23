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
    out = DiscordChannelPlugin().build_bundle(_channel(), resolved_routes={})
    for path in out.files:
        assert not path.endswith(".py"), f"unexpected python source: {path}"
    assert "Dockerfile" in out.files
    assert "channel_config.json" in out.files
    assert "routes.json" in out.files


def test_entrypoint_is_module_form():
    out = DiscordChannelPlugin().build_bundle(_channel(), resolved_routes={})
    assert out.entrypoint == "python -m vystak_channel_discord"


def test_channel_config_includes_channel_type_and_protocol():
    out = DiscordChannelPlugin().build_bundle(_channel(), resolved_routes={})
    cfg = json.loads(out.files["channel_config.json"])
    assert cfg["channel_type"] == "discord"
    # Discord defaults to streaming so the typing indicator covers the turn.
    assert cfg["agent_protocol"] == "a2a-stream"


def test_plugin_writes_version_fields():
    out = DiscordChannelPlugin().build_bundle(_channel(), resolved_routes={})
    cfg = json.loads(out.files["channel_config.json"])
    assert "channel_package_version" in cfg
    assert "channel_runtime_version" in cfg


def test_plugin_injects_canonical_name():
    ch = _channel()
    out = DiscordChannelPlugin().build_bundle(ch, resolved_routes={})
    cfg = json.loads(out.files["channel_config.json"])
    assert cfg["canonical_name"] == ch.canonical_name
    # canonical_name is "<channel-name>.channels.<platform-namespace>"
    assert cfg["canonical_name"] == "discord-prod.channels.default"


def test_channel_config_includes_delivery_port_and_transport_type():
    """channel_config.json includes delivery_port + transport_type (heartbeat v2)."""
    out = DiscordChannelPlugin().build_bundle(_channel(), resolved_routes={})
    cfg = json.loads(out.files["channel_config.json"])
    assert cfg["delivery_port"] == 9999
    assert cfg["transport_type"] == "http"


def test_transport_type_defaults_to_http_when_no_transport():
    """Platform has no transport declared → transport_type is 'http'."""
    ch = _channel()
    out = DiscordChannelPlugin().build_bundle(ch, resolved_routes={})
    cfg = json.loads(out.files["channel_config.json"])
    assert cfg["transport_type"] == "http"
