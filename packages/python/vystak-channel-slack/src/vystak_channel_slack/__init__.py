"""Vystak Slack channel plugin — auto-registers on import."""

from vystak.channels import register_plugin

from vystak_channel_slack.plugin import SlackChannelConfig, SlackChannelPlugin

__version__ = "0.1.0"

_plugin = SlackChannelPlugin()
register_plugin(_plugin)


__all__ = ["SlackChannelConfig", "SlackChannelPlugin"]
