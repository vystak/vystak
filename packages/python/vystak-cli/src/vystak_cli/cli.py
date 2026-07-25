"""Vystak CLI entry point."""

import click

# Trigger auto-registration of bundled channel plugins.
# Side-effecting imports are the intended mechanism here; keep them at top level
# so ruff's SIM/I rules don't re-order or flag them.
import vystak_channel_chat  # noqa: F401 — registers ChannelType.CHAT plugin
import vystak_channel_discord  # noqa: F401 — registers ChannelType.DISCORD plugin
import vystak_channel_panel  # noqa: F401 — registers ChannelType.PANEL plugin
import vystak_channel_slack  # noqa: F401 — registers ChannelType.SLACK plugin

from vystak_cli import __version__
from vystak_cli.commands import (
    apply_cmd,
    destroy_cmd,
    init_cmd,
    logs_cmd,
    plan_cmd,
    secrets_cmd,
    status_cmd,
    update_cmd,
)


@click.group()
@click.version_option(version=__version__)
def cli():
    """Vystak — declarative AI agent orchestration."""


cli.add_command(init_cmd)
cli.add_command(plan_cmd)
cli.add_command(apply_cmd)
cli.add_command(destroy_cmd)
cli.add_command(status_cmd)
cli.add_command(logs_cmd)
cli.add_command(secrets_cmd)
cli.add_command(update_cmd)


if __name__ == "__main__":
    cli()
