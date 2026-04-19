import pytest
from pydantic import BaseModel
from vystak.channels import ChannelPluginRegistry
from vystak.providers.base import ChannelPlugin, GeneratedCode
from vystak.schema.common import AgentProtocol, ChannelType, RuntimeMode


class _NoopConfig(BaseModel):
    pass


class _FakePlugin(ChannelPlugin):
    type = ChannelType.API
    default_runtime_mode = RuntimeMode.SHARED
    agent_protocol = AgentProtocol.A2A_TURN
    config_schema = _NoopConfig

    def generate_code(self, channel, resolved_routes):
        return GeneratedCode(files={}, entrypoint="main.py")

    def provision_nodes(self, channel, platform):
        return []

    def thread_name(self, event):
        return "thread:api:default:1"

    def health_check(self, deployment):
        return "ok"


class _FakeChatPlugin(_FakePlugin):
    type = ChannelType.CHAT


class TestChannelPluginRegistry:
    def test_register_and_get(self):
        registry = ChannelPluginRegistry()
        plugin = _FakePlugin()
        registry.register(plugin)
        assert registry.get(ChannelType.API) is plugin

    def test_missing_plugin_raises(self):
        registry = ChannelPluginRegistry()
        with pytest.raises(KeyError, match="No plugin registered"):
            registry.get(ChannelType.SLACK)

    def test_list_plugins(self):
        registry = ChannelPluginRegistry()
        p1 = _FakePlugin()
        p2 = _FakeChatPlugin()
        registry.register(p1)
        registry.register(p2)
        plugins = registry.list()
        assert len(plugins) == 2

    def test_register_replaces(self):
        registry = ChannelPluginRegistry()
        p1 = _FakePlugin()
        p2 = _FakePlugin()
        registry.register(p1)
        registry.register(p2)
        assert registry.get(ChannelType.API) is p2
