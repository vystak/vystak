"""Tests for the ChatChannelPlugin — unit-level, no Docker required."""

import json

from vystak.schema.channel import Channel
from vystak.schema.common import AgentProtocol, ChannelType, RuntimeMode
from vystak.schema.platform import Platform
from vystak.schema.provider import Provider
from vystak_channel_chat import ChatChannelPlugin


def _platform():
    docker = Provider(name="docker", type="docker")
    return Platform(name="local", type="docker", provider=docker)


def _channel(**overrides):
    base = {
        "name": "chat",
        "type": ChannelType.CHAT,
        "platform": _platform(),
    }
    base.update(overrides)
    return Channel(**base)


class TestChatChannelPlugin:
    def test_plugin_metadata(self):
        plugin = ChatChannelPlugin()
        assert plugin.type == ChannelType.CHAT
        assert plugin.default_runtime_mode == RuntimeMode.SHARED
        assert plugin.agent_protocol == AgentProtocol.A2A_TURN

    def test_generate_code_emits_expected_files(self):
        plugin = ChatChannelPlugin()
        resolved = {
            "weather-agent": {
                "canonical": "weather-agent.agents.default",
                "address": "http://vystak-weather-agent:8000",
            },
            "time-agent": {
                "canonical": "time-agent.agents.default",
                "address": "http://vystak-time-agent:8000",
            },
        }
        code = plugin.generate_code(_channel(), resolved)

        assert code.entrypoint == "python -m vystak_channel_chat"
        assert set(code.files.keys()) == {
            "Dockerfile",
            "requirements.txt",
            "channel_config.json",
            "routes.json",
        }

    def test_routes_baked_into_routes_json(self):
        plugin = ChatChannelPlugin()
        resolved = {
            "weather-agent": {
                "canonical": "weather-agent.agents.default",
                "address": "http://vystak-weather-agent:8000",
            },
        }
        code = plugin.generate_code(_channel(), resolved)
        routes = json.loads(code.files["routes.json"])
        assert routes == resolved

    def test_no_resolved_routes_still_valid(self):
        plugin = ChatChannelPlugin()
        code = plugin.generate_code(_channel(), {})
        assert json.loads(code.files["routes.json"]) == {}

    def test_dockerfile_uses_python_311(self):
        plugin = ChatChannelPlugin()
        code = plugin.generate_code(_channel(), {})
        assert "FROM python:3.11-slim" in code.files["Dockerfile"]

    def test_requirements_lists_third_party_deps(self):
        """Channel package source is bundled by DockerChannelNode; the
        emitted requirements.txt only carries third-party deps."""
        plugin = ChatChannelPlugin()
        code = plugin.generate_code(_channel(), {})
        assert "fastapi" in code.files["requirements.txt"]
        assert "vystak-channel-chat" not in code.files["requirements.txt"]

    def test_thread_name_format(self):
        plugin = ChatChannelPlugin()
        name = plugin.thread_name({"channel": "web", "session_id": "abc123"})
        assert name == "thread:chat:web:abc123"

    def test_thread_name_default_channel(self):
        plugin = ChatChannelPlugin()
        name = plugin.thread_name({"id": "xyz"})
        assert name == "thread:chat:default:xyz"


class TestNoCodegenShape:
    """Task 3.2: plugin must emit configs + Dockerfile only (no Python source)."""

    def test_plugin_emits_no_python_source(self):
        out = ChatChannelPlugin().generate_code(_channel(), resolved_routes={})
        for path in out.files:
            assert not path.endswith(".py"), f"unexpected python source: {path}"
        assert "Dockerfile" in out.files
        assert "channel_config.json" in out.files

    def test_entrypoint_is_module_form(self):
        out = ChatChannelPlugin().generate_code(_channel(), resolved_routes={})
        assert out.entrypoint == "python -m vystak_channel_chat"

    def test_channel_config_includes_channel_type_and_protocol(self):
        out = ChatChannelPlugin().generate_code(_channel(), resolved_routes={})
        cfg = json.loads(out.files["channel_config.json"])
        assert cfg["channel_type"] == "chat"
        assert cfg["agent_protocol"] == "a2a-turn"


class TestDeliveryFields:
    """channel_config.json includes delivery_port + transport_type (heartbeat v2)."""

    def test_channel_config_includes_delivery_port_and_transport_type(self):
        out = ChatChannelPlugin().generate_code(_channel(), resolved_routes={})
        cfg = json.loads(out.files["channel_config.json"])
        assert cfg["delivery_port"] == 9999
        assert cfg["transport_type"] == "http"

    def test_delivery_port_from_channel_config(self):
        ch = _channel(config={"delivery_port": 10001})
        out = ChatChannelPlugin().generate_code(ch, resolved_routes={})
        cfg = json.loads(out.files["channel_config.json"])
        assert cfg["delivery_port"] == 10001

    def test_transport_type_defaults_to_http_when_no_transport(self):
        """Platform has no transport declared → transport_type is 'http'."""
        ch = _channel()
        out = ChatChannelPlugin().generate_code(ch, resolved_routes={})
        cfg = json.loads(out.files["channel_config.json"])
        assert cfg["transport_type"] == "http"


class TestAutoRegistration:
    def test_plugin_registered_on_import(self):
        from vystak.channels import get_plugin

        plugin = get_plugin(ChannelType.CHAT)
        assert isinstance(plugin, ChatChannelPlugin)

    def test_plugin_writes_version_fields(self):
        import json

        out = ChatChannelPlugin().generate_code(_channel(), resolved_routes={})
        cfg = json.loads(out.files["channel_config.json"])
        assert "channel_package_version" in cfg
        assert "channel_runtime_version" in cfg

    def test_plugin_injects_canonical_name(self):
        import json

        ch = _channel()
        out = ChatChannelPlugin().generate_code(ch, resolved_routes={})
        cfg = json.loads(out.files["channel_config.json"])
        assert cfg["canonical_name"] == ch.canonical_name
        # canonical_name is "<channel-name>.channels.<platform-namespace>"
        assert cfg["canonical_name"] == "chat.channels.default"
