"""Tests for the SlackChannelPlugin — unit-level, no Slack or Docker required."""

import json

from vystak.schema.agent import Agent
from vystak.schema.channel import Channel, SlackChannelOverride
from vystak.schema.common import AgentProtocol, ChannelType, RuntimeMode
from vystak.schema.model import Model
from vystak.schema.platform import Platform
from vystak.schema.provider import Provider
from vystak.schema.secret import Secret
from vystak_channel_slack import SlackChannelPlugin


def _model():
    return Model(
        name="claude",
        model_name="claude-sonnet-4-20250514",
        provider=Provider(name="anthropic", type="anthropic"),
    )


def _agent(name: str) -> Agent:
    return Agent(name=name, model=_model(), provider=Provider(name="docker", type="docker"))


def _platform():
    docker = Provider(name="docker", type="docker")
    return Platform(name="local", type="docker", provider=docker)


def _channel(**overrides):
    base = {
        "name": "slack-main",
        "type": ChannelType.SLACK,
        "platform": _platform(),
        "agents": [_agent("weather-agent"), _agent("support-agent")],
        "default_agent": _agent("weather-agent"),
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
        resolved = {
            "weather-agent": {
                "canonical": "weather-agent.agents.default",
                "address": "http://vystak-weather-agent:8000",
            },
        }
        code = plugin.generate_code(_channel(), resolved)

        assert code.entrypoint == "server.py"
        assert set(code.files.keys()) == {
            "server.py",
            "Dockerfile",
            "requirements.txt",
            "routes.json",
            "channel_config.json",
        }

    def test_routes_baked(self):
        plugin = SlackChannelPlugin()
        resolved = {
            "weather-agent": {
                "canonical": "weather-agent.agents.default",
                "address": "http://vystak-weather-agent:8000",
            },
        }
        code = plugin.generate_code(_channel(), resolved)
        routes = json.loads(code.files["routes.json"])
        assert routes == resolved

    def test_channel_config_agents(self):
        plugin = SlackChannelPlugin()
        code = plugin.generate_code(_channel(), {})
        cfg = json.loads(code.files["channel_config.json"])
        assert cfg["agents"] == ["weather-agent", "support-agent"]

    def test_channel_config_default_agent(self):
        plugin = SlackChannelPlugin()
        code = plugin.generate_code(_channel(), {})
        cfg = json.loads(code.files["channel_config.json"])
        assert cfg["default_agent"] == "weather-agent"

    def test_channel_config_state_sqlite(self):
        plugin = SlackChannelPlugin()
        code = plugin.generate_code(_channel(), {})
        cfg = json.loads(code.files["channel_config.json"])
        assert cfg["state"] is not None
        assert cfg["state"]["type"] == "sqlite"

    def test_channel_config_channel_overrides(self):
        plugin = SlackChannelPlugin()
        ov = SlackChannelOverride(name="ov1", agent=_agent("support-agent"), system_prompt="Help!")
        ch = _channel(channel_overrides={"C12345678": ov})
        code = plugin.generate_code(ch, {})
        cfg = json.loads(code.files["channel_config.json"])
        assert "C12345678" in cfg["channel_overrides"]
        assert cfg["channel_overrides"]["C12345678"]["agent"] == "support-agent"
        assert cfg["channel_overrides"]["C12345678"]["system_prompt"] == "Help!"

    def test_channel_config_no_rules_json(self):
        """rules.json must be absent — replaced by channel_config.json."""
        plugin = SlackChannelPlugin()
        code = plugin.generate_code(_channel(), {})
        assert "rules.json" not in code.files

    def test_requirements_include_slack_bolt(self):
        plugin = SlackChannelPlugin()
        code = plugin.generate_code(_channel(), {})
        assert "slack-bolt" in code.files["requirements.txt"]

    def test_requirements_include_psycopg(self):
        plugin = SlackChannelPlugin()
        code = plugin.generate_code(_channel(), {})
        assert "psycopg" in code.files["requirements.txt"]

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

    def test_channel_config_loaded(self):
        """server.py must load channel_config.json at startup."""
        from vystak_channel_slack.server_template import SERVER_PY

        assert "channel_config.json" in SERVER_PY
        assert "channel_config" in SERVER_PY

    def test_resolver_used_in_server(self):
        """server.py must use the resolver module."""
        from vystak_channel_slack.server_template import SERVER_PY

        assert "vystak_channel_slack.resolver" in SERVER_PY or "_resolve" in SERVER_PY

    def test_slash_command_handler_present(self):
        """server.py must register a /vystak slash command handler."""
        from vystak_channel_slack.server_template import SERVER_PY

        assert "/vystak" in SERVER_PY
        assert "handle_command" in SERVER_PY

    def test_member_joined_handler_present(self):
        """server.py must handle member_joined_channel events."""
        from vystak_channel_slack.server_template import SERVER_PY

        assert "member_joined_channel" in SERVER_PY
        assert "on_member_joined" in SERVER_PY

    def test_vystak_packages_not_in_requirements(self):
        """vystak + vystak_transport_http are bundled as source by
        DockerChannelNode; they must NOT appear in requirements.txt."""
        from vystak_channel_slack.server_template import REQUIREMENTS

        assert "vystak>=" not in REQUIREMENTS
        assert "vystak-transport-http" not in REQUIREMENTS

    def test_dockerfile_creates_data_dir(self):
        """Dockerfile must create /data for SQLite to write."""
        from vystak_channel_slack.server_template import DOCKERFILE

        assert "mkdir -p /data" in DOCKERFILE
