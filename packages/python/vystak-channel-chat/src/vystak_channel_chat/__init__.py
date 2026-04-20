"""Vystak chat channel plugin — auto-registers on import."""

from vystak.channels import register_plugin

from vystak_channel_chat.plugin import ChatChannelConfig, ChatChannelPlugin

__version__ = "0.1.0"

_plugin = ChatChannelPlugin()
register_plugin(_plugin)


__all__ = ["ChatChannelConfig", "ChatChannelPlugin"]
