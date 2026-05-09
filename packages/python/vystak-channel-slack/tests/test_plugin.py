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
    return Agent(
        name=name,
        framework="langchain-python",
        model=_model(),
        provider=Provider(name="docker", type="docker"),
    )


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

        assert code.entrypoint == "python -m vystak_channel_slack"
        assert set(code.files.keys()) == {
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

    def test_requirements_lists_third_party_deps(self):
        """Channel package source is bundled by DockerChannelNode; the
        emitted requirements.txt only carries third-party deps."""
        plugin = SlackChannelPlugin()
        code = plugin.generate_code(_channel(), {})
        assert "slack-bolt" in code.files["requirements.txt"]
        assert "vystak-channel-slack" not in code.files["requirements.txt"]

    def test_thread_name_in_channel(self):
        plugin = SlackChannelPlugin()
        name = plugin.thread_name({"channel": "C0123", "thread_ts": "1705.111", "ts": "1705.222"})
        assert name == "thread:slack:C0123:1705.111"

    def test_thread_name_dm(self):
        plugin = SlackChannelPlugin()
        name = plugin.thread_name({"ts": "1705.555"})
        assert name == "thread:slack:dm:1705.555"


class TestNoCodegenShape:
    """Task 2.8: plugin must emit configs + Dockerfile only (no Python source)."""

    def test_plugin_emits_no_python_source(self):
        plugin = SlackChannelPlugin()
        out = plugin.generate_code(_channel(), resolved_routes={})
        for path in out.files:
            assert not path.endswith(".py"), f"unexpected python source emitted: {path}"
        assert "Dockerfile" in out.files
        assert "channel_config.json" in out.files
        assert "routes.json" in out.files
        assert "requirements.txt" in out.files

    def test_plugin_entrypoint_is_module_form(self):
        plugin = SlackChannelPlugin()
        out = plugin.generate_code(_channel(), resolved_routes={})
        assert out.entrypoint == "python -m vystak_channel_slack"

    def test_dockerfile_uses_bundled_source(self):
        """Dockerfile bundles source via COPY . . and runs `python -m`,
        not `pip install vystak-channel-slack==X.Y.Z` from PyPI."""
        plugin = SlackChannelPlugin()
        out = plugin.generate_code(_channel(), resolved_routes={})
        df = out.files["Dockerfile"]
        assert "COPY . ." in df
        assert "python" in df and "vystak_channel_slack" in df
        assert "vystak-channel-slack==" not in df

    def test_channel_config_includes_channel_type_and_protocol(self):
        plugin = SlackChannelPlugin()
        out = plugin.generate_code(_channel(), resolved_routes={})
        cfg = json.loads(out.files["channel_config.json"])
        assert cfg["channel_type"] == "slack"
        # Slack defaults to streaming so tool-call statuses surface in-thread.
        assert cfg["agent_protocol"] == "a2a-stream"


class TestAutoRegistration:
    def test_plugin_registered_on_import(self):
        from vystak.channels import get_plugin

        plugin = get_plugin(ChannelType.SLACK)
        assert isinstance(plugin, SlackChannelPlugin)

    def test_plugin_writes_version_fields(self):
        out = SlackChannelPlugin().generate_code(_channel(), resolved_routes={})
        cfg = json.loads(out.files["channel_config.json"])
        assert "channel_package_version" in cfg
        assert "channel_runtime_version" in cfg

    def test_plugin_injects_canonical_name(self):
        ch = _channel()
        out = SlackChannelPlugin().generate_code(ch, resolved_routes={})
        cfg = json.loads(out.files["channel_config.json"])
        assert cfg["canonical_name"] == ch.canonical_name
        # canonical_name is "<channel-name>.channels.<platform-namespace>"
        assert cfg["canonical_name"] == "slack-main.channels.default"


class TestSlackChannelStreamToolCalls:
    """The stream_tool_calls flag round-trips from Channel.config to channel_config.json."""

    def test_default_value_false(self):
        plugin = SlackChannelPlugin()
        code = plugin.generate_code(_channel(), {})
        cfg = json.loads(code.files["channel_config.json"])
        assert cfg.get("stream_tool_calls") is False

    def test_true_when_set_in_channel_config(self):
        plugin = SlackChannelPlugin()
        ch = _channel(config={"stream_tool_calls": True})
        code = plugin.generate_code(ch, {})
        cfg = json.loads(code.files["channel_config.json"])
        assert cfg["stream_tool_calls"] is True

    def test_slack_channel_config_pydantic_field(self):
        """The pydantic SlackChannelConfig schema documents the field."""
        from vystak_channel_slack import SlackChannelConfig

        cfg = SlackChannelConfig(stream_tool_calls=True)
        assert cfg.stream_tool_calls is True
        # Default still False.
        assert SlackChannelConfig().stream_tool_calls is False
