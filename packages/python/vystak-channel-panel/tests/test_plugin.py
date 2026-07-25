"""Tests for the PanelChannelPlugin — unit-level, no Docker required."""

import json

from vystak.schema.channel import Channel
from vystak.schema.common import AgentProtocol, ChannelType, RuntimeMode
from vystak.schema.platform import Platform
from vystak.schema.provider import Provider
from vystak_channel_panel import PanelChannelPlugin


def _platform():
    docker = Provider(name="docker", type="docker")
    return Platform(name="local", type="docker", provider=docker)


def _channel(**overrides):
    base = {
        "name": "panel",
        "type": ChannelType.PANEL,
        "platform": _platform(),
    }
    base.update(overrides)
    return Channel(**base)


class TestPanelChannelPlugin:
    def test_plugin_metadata(self):
        plugin = PanelChannelPlugin()
        assert plugin.type == ChannelType.PANEL
        assert plugin.default_runtime_mode == RuntimeMode.SHARED
        assert plugin.agent_protocol == AgentProtocol.A2A_TURN

    def test_build_bundle_emits_expected_files(self):
        code = PanelChannelPlugin().build_bundle(_channel(), {})
        assert code.entrypoint == "python -m vystak_channel_panel"
        assert set(code.files.keys()) == {
            "Dockerfile",
            "requirements.txt",
            "channel_config.json",
            "routes.json",
        }

    def test_routes_baked_into_routes_json(self):
        resolved = {
            "weather-agent": {
                "canonical": "weather-agent.agents.default",
                "address": "http://vystak-weather-agent:8000/a2a",
            },
        }
        code = PanelChannelPlugin().build_bundle(_channel(), resolved)
        assert json.loads(code.files["routes.json"]) == resolved

    def test_channel_config_shape(self):
        code = PanelChannelPlugin().build_bundle(_channel(), {})
        cfg = json.loads(code.files["channel_config.json"])
        assert cfg["channel_type"] == "panel"
        assert cfg["agent_protocol"] == "a2a-turn"
        assert cfg["port"] == 8080
        assert cfg["db_path"] == "/data/panel.db"
        assert cfg["canonical_name"] == "panel.channels.default"
        assert "channel_package_version" in cfg
        assert "channel_runtime_version" in cfg

    def test_db_path_override(self):
        ch = _channel(config={"db_path": "/tmp/x.db"})
        cfg = json.loads(
            PanelChannelPlugin().build_bundle(ch, {}).files["channel_config.json"]
        )
        assert cfg["db_path"] == "/tmp/x.db"

    def test_plugin_emits_no_python_source(self):
        code = PanelChannelPlugin().build_bundle(_channel(), {})
        for path in code.files:
            assert not path.endswith(".py"), f"unexpected python source: {path}"

    def test_dockerfile_uses_python_311(self):
        code = PanelChannelPlugin().build_bundle(_channel(), {})
        assert "FROM python:3.11-slim" in code.files["Dockerfile"]

    def test_thread_name_format(self):
        name = PanelChannelPlugin().thread_name({"conversation_id": "abc"})
        assert name == "thread:panel:abc"


class TestAutoRegistration:
    def test_plugin_registered_on_import(self):
        from vystak.channels import get_plugin

        plugin = get_plugin(ChannelType.PANEL)
        assert isinstance(plugin, PanelChannelPlugin)


class TestCliRegistration:
    def test_cli_import_registers_panel_plugin(self):
        """Importing the CLI must register the panel plugin. Runs in a fresh
        interpreter: in-process, this test module's own top-level import of
        vystak_channel_panel would have already registered it, hiding a
        missing side-effect import in cli.py."""
        import subprocess
        import sys

        code = (
            "import vystak_cli.cli;"
            "from vystak.channels import get_plugin;"
            "from vystak.schema.common import ChannelType;"
            "print(type(get_plugin(ChannelType.PANEL)).__name__)"
        )
        out = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            check=False,
        )
        # check=False + explicit assert: CalledProcessError renders only the
        # exit code, hiding the registry KeyError that explains the failure.
        assert out.returncode == 0, out.stderr
        assert out.stdout.strip() == "PanelChannelPlugin"
