"""Vystak Discord channel plugin — auto-registers on import."""

from vystak.channels import register_plugin

from vystak_channel_discord.plugin import DiscordChannelConfig, DiscordChannelPlugin

__version__ = "0.1.0"

_plugin = DiscordChannelPlugin()
register_plugin(_plugin)


__all__ = ["DiscordChannelConfig", "DiscordChannelPlugin"]
