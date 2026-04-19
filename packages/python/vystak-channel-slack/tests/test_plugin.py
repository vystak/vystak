"""Tests for the SlackChannelPlugin — unit-level, no Slack or Docker required."""

import json

from vystak.schema.channel import Channel, RouteRule
from vystak.schema.common import AgentProtocol, ChannelType, RuntimeMode
from vystak.schema.platform import Platform
from vystak.schema.provider import Provider
from vystak.schema.secret import Secret
from vystak_channel_slack import SlackChannelPlugin


def _platform():
    docker = Provider(name="docker", type="docker")
    return Platform(name="local", type="docker", provider=docker)


def _channel(**overrides):
    base = {
        "name": "slack-main",
        "type": ChannelType.SLACK,
        "platform": _platform(),
        "routes": [
            RouteRule(match={"slack_channel": "C0123"}, agent="weather-agent"),
            RouteRule(match={"dm": True}, agent="dm-agent"),
        ],
        "secrets": [
            Secret(name="SLACK_BOT_TOKEN"),
            Secret(name="SLACK_APP_TOKEN"),
        ],
    }
    base.update(overrides)
    return Channel(**base)


class TestSlackChannelPlugin:
    def test_plugin_metadata(self):
        plugin = SlackChannelPlugin()
        assert plugin.type == ChannelType.SLACK
        assert plugin.default_runtime_mode == RuntimeMode.SHARED
        assert plugin.agent_protocol == AgentProtocol.A2A_TURN

    def test_generate_code_emits_expected_files(self):
        plugin = SlackChannelPlugin()
        resolved = {"weather-agent": "http://vystak-weather-agent:8000"}
        code = plugin.generate_code(_channel(), resolved)

        assert code.entrypoint == "server.py"
        assert set(code.files.keys()) == {
            "server.py",
            "Dockerfile",
            "requirements.txt",
            "routes.json",
            "rules.json",
        }

    def test_routes_baked(self):
        plugin = SlackChannelPlugin()
        resolved = {"weather-agent": "http://vystak-weather-agent:8000"}
        code = plugin.generate_code(_channel(), resolved)
        routes = json.loads(code.files["routes.json"])
        assert routes == resolved

    def test_rules_preserve_match_shape(self):
        plugin = SlackChannelPlugin()
        code = plugin.generate_code(_channel(), {})
        rules = json.loads(code.files["rules.json"])
        assert len(rules) == 2
        assert rules[0]["match"] == {"slack_channel": "C0123"}
        assert rules[0]["agent"] == "weather-agent"
        assert rules[1]["match"] == {"dm": True}
        assert rules[1]["agent"] == "dm-agent"

    def test_requirements_include_slack_bolt(self):
        plugin = SlackChannelPlugin()
        code = plugin.generate_code(_channel(), {})
        assert "slack-bolt" in code.files["requirements.txt"]

    def test_thread_name_in_channel(self):
        plugin = SlackChannelPlugin()
        name = plugin.thread_name({"channel": "C0123", "thread_ts": "1705.111", "ts": "1705.222"})
        assert name == "thread:slack:C0123:1705.111"

    def test_thread_name_dm(self):
        plugin = SlackChannelPlugin()
        name = plugin.thread_name({"ts": "1705.555"})
        assert name == "thread:slack:dm:1705.555"


class TestAutoRegistration:
    def test_plugin_registered_on_import(self):
        from vystak.channels import get_plugin

        plugin = get_plugin(ChannelType.SLACK)
        assert isinstance(plugin, SlackChannelPlugin)


class TestServerTemplateTransportBootstrap:
    """Task 16: the Slack channel server must bootstrap an AgentClient from env."""

    def test_reads_vystak_routes_json_env(self):
        from vystak_channel_slack.server_template import SERVER_PY

        assert "VYSTAK_ROUTES_JSON" in SERVER_PY

    def test_has_build_transport_helper(self):
        from vystak_channel_slack.server_template import SERVER_PY

        assert "_build_transport_from_env" in SERVER_PY

    def test_installs_agent_client_as_default(self):
        from vystak_channel_slack.server_template import SERVER_PY

        assert "AgentClient" in SERVER_PY
        # The process-level default client must be installed so _default_client()
        # returns something from the event handlers.
        assert "_DEFAULT_CLIENT" in SERVER_PY

    def test_uses_http_transport_plugin(self):
        from vystak_channel_slack.server_template import SERVER_PY

        assert "HttpTransport" in SERVER_PY
        assert "vystak_transport_http" in SERVER_PY

    def test_dispatch_goes_through_agent_client(self):
        """A2A dispatch is via AgentClient.send_task(), not raw httpx POST to /a2a."""
        from vystak_channel_slack.server_template import SERVER_PY

        assert ".send_task(" in SERVER_PY
        # The old raw /a2a httpx posting must be gone.
        assert '/a2a"' not in SERVER_PY
        assert "'tasks/send'" not in SERVER_PY

    def test_fallback_to_routes_json(self):
        """While providers are still on the old route-shape, the server must
        tolerate a legacy routes.json and convert it to the new shape.
        """
        from vystak_channel_slack.server_template import SERVER_PY

        assert "routes.json" in SERVER_PY
        # Single-line migration-state warning log.
        assert "routes.json fallback" in SERVER_PY

    def test_requirements_include_vystak_transport(self):
        from vystak_channel_slack.server_template import REQUIREMENTS

        assert "vystak" in REQUIREMENTS
        assert "vystak-transport-http" in REQUIREMENTS
