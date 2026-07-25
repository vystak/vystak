"""Vystak panel channel plugin — auto-registers on import."""

from vystak.channels import register_plugin

from vystak_channel_panel.plugin import PanelChannelConfig, PanelChannelPlugin

__version__ = "0.1.0"

_plugin = PanelChannelPlugin()
register_plugin(_plugin)


__all__ = ["PanelChannelConfig", "PanelChannelPlugin"]
