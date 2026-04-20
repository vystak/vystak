"""In-process registry mapping ChannelType to ChannelPlugin implementations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from vystak.schema.common import ChannelType

if TYPE_CHECKING:
    from vystak.providers.base import ChannelPlugin


class ChannelPluginRegistry:
    """Maps ChannelType → ChannelPlugin instance.

    Plugins register themselves at import time. Platform providers look up the
    plugin by channel type when provisioning.
    """

    def __init__(self) -> None:
        self._plugins: dict[ChannelType, ChannelPlugin] = {}

    def register(self, plugin: ChannelPlugin) -> None:
        self._plugins[plugin.type] = plugin

    def get(self, channel_type: ChannelType) -> ChannelPlugin:
        if channel_type not in self._plugins:
            raise KeyError(
                f"No plugin registered for channel type '{channel_type.value}'. "
                f"Registered: {[t.value for t in self._plugins]}"
            )
        return self._plugins[channel_type]

    def list(self) -> list[ChannelPlugin]:
        return list(self._plugins.values())


_registry = ChannelPluginRegistry()


def register_plugin(plugin: ChannelPlugin) -> None:
    _registry.register(plugin)


def get_plugin(channel_type: ChannelType) -> ChannelPlugin:
    return _registry.get(channel_type)


def list_plugins() -> list[ChannelPlugin]:
    return _registry.list()
