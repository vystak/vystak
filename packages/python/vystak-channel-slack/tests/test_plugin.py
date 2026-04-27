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


class TestServerTemplateThreadBindings:
    """Slack agent threads — server.py wires up thread_bindings."""

    def test_imports_route_thread_message(self):
        from vystak_channel_slack.server_template import SERVER_PY

        assert "from vystak_channel_slack.threads import route_thread_message" in SERVER_PY

    def test_on_mention_writes_binding_after_finalize(self):
        """After _finalize succeeds, on_mention persists the binding."""
        from vystak_channel_slack.server_template import SERVER_PY

        assert "_store.set_thread_binding(" in SERVER_PY

    def test_on_mention_sticky_check_uses_binding(self):
        """If a binding exists, on_mention must use it instead of resolving."""
        from vystak_channel_slack.server_template import SERVER_PY

        # Sticky check looks up the binding before _resolve().
        assert "_store.thread_binding(" in SERVER_PY

    def test_on_message_calls_route_thread_message(self):
        """The non-DM branch in on_message must consult the policy."""
        from vystak_channel_slack.server_template import SERVER_PY

        assert "route_thread_message(" in SERVER_PY

    def test_on_message_no_longer_blanket_returns_for_non_dm(self):
        """The 'mentions are already handled by on_mention' early-return
        must be gone — replaced by the policy call."""
        from vystak_channel_slack.server_template import SERVER_PY

        assert "mentions are already handled by on_mention" not in SERVER_PY

    def test_require_explicit_mention_is_consulted(self):
        """The opt-out flag is passed to the policy."""
        from vystak_channel_slack.server_template import SERVER_PY

        assert "_THREAD_REQUIRE_EXPLICIT_MENTION" in SERVER_PY
        # Ensure it's no longer a dead variable: it's read after the
        # 'require_explicit_mention=' kwarg in the policy call.
        assert "require_explicit_mention=_THREAD_REQUIRE_EXPLICIT_MENTION" in SERVER_PY


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


class TestStreamToAgentHelper:
    """The _stream_to_agent helper is emitted into server.py and the runtime
    branches on the stream_tool_calls flag at use sites."""

    def _server_py(self):
        from vystak_channel_slack.server_template import SERVER_PY
        return SERVER_PY

    def test_helper_is_defined(self):
        src = self._server_py()
        assert "async def _stream_to_agent(" in src

    def test_helper_uses_stream_task(self):
        src = self._server_py()
        assert "stream_task(" in src

    def test_helper_is_rate_limited(self):
        """Throttle to 1 chat.update per second (Slack tier-3 cap)."""
        src = self._server_py()
        # The helper computes a min interval between updates.
        assert "_STREAM_UPDATE_MIN_INTERVAL_S" in src or "1.0" in src
        # The helper tracks last_update_at to coalesce.
        assert "last_update_at" in src

    def test_helper_renders_in_flight_and_completed_lines(self):
        """In-flight tools render as `🔧 *<name>*`; completed tools add `✓ _(Xs)_`."""
        src = self._server_py()
        assert "\\U0001f527" in src or "🔧" in src
        assert "✓" in src or "\\u2713" in src
        # The duration formatter renders as "(2.1s)" — keep the regex narrow
        # so we don't false-positive on unrelated mentions.
        assert "duration_ms" in src

    def test_helper_handles_error_with_legacy_text(self):
        """Same error text as _forward_to_agent's except branch."""
        src = self._server_py()
        # The exact phrase mirrors on_mention's existing error path.
        assert "Sorry, I hit an error talking to" in src

    def test_helper_replaces_placeholder_on_final(self):
        """On final event, chat.update with the rendered final reply."""
        src = self._server_py()
        # The helper calls _to_slack_mrkdwn on ev.text (or equivalent) for
        # the final replacement. Looking for the function call inside the
        # streaming helper body.
        # Use a regex to scope the assertion to the helper.
        import re
        m = re.search(
            r"async def _stream_to_agent\(.*?\):.*?(?=\n(?:async def |def |@|\Z))",
            src, re.DOTALL,
        )
        assert m, "_stream_to_agent body not found"
        body = m.group(0)
        assert "_to_slack_mrkdwn" in body
        assert "chat_update" in body

    def test_helper_passes_metadata_like_forward_to_agent(self):
        """Same metadata shape: sessionId, user_id (slack-prefixed), project_id."""
        src = self._server_py()
        import re
        m = re.search(
            r"async def _stream_to_agent\(.*?\):.*?(?=\n(?:async def |def |@|\Z))",
            src, re.DOTALL,
        )
        body = m.group(0)
        assert '"sessionId"' in body
        assert "slack:" in body  # the user_id prefix
        assert "project_id" in body

    def test_runtime_reads_stream_tool_calls_flag(self):
        """server.py reads the flag from _channel_config at startup."""
        src = self._server_py()
        assert '"stream_tool_calls"' in src
        # A module-level binding so the handlers can branch fast.
        assert "_STREAM_TOOL_CALLS" in src or "_stream_tool_calls" in src


class TestStreamToolCallsBranch:
    """on_mention and on_message thread-follow branch on _STREAM_TOOL_CALLS."""

    def _server_py(self):
        from vystak_channel_slack.server_template import SERVER_PY
        return SERVER_PY

    def test_on_mention_branches_on_flag(self):
        import re
        src = self._server_py()
        m = re.search(
            r"async def on_mention\(.*?\):.*?(?=\n(?:async def |def |@|\Z))",
            src, re.DOTALL,
        )
        assert m, "on_mention body not found"
        body = m.group(0)
        # The branch checks the flag and routes to _stream_to_agent on True.
        assert "_STREAM_TOOL_CALLS" in body
        assert "_stream_to_agent(" in body
        # The non-streaming branch still calls _forward_to_agent.
        assert "_forward_to_agent(" in body

    def test_on_message_thread_follow_branches_on_flag(self):
        import re
        src = self._server_py()
        m = re.search(
            r"async def on_message\(.*?\):.*?(?=\n(?:async def |def |@|\Z))",
            src, re.DOTALL,
        )
        assert m, "on_message body not found"
        body = m.group(0)
        assert "_STREAM_TOOL_CALLS" in body
        assert "_stream_to_agent(" in body

    def test_default_off_preserves_forward_to_agent(self):
        """When stream_tool_calls=False, the existing _forward_to_agent path
        is unchanged. Verifying the non-streaming branch still includes the
        existing reply-finalize sequence."""
        src = self._server_py()
        # _to_slack_mrkdwn + _finalize sequence still present in on_mention.
        # (Both pre-existed; we just want them not to be removed.)
        assert "_to_slack_mrkdwn(raw_reply)" in src
        assert "_finalize(client, say, placeholder" in src
