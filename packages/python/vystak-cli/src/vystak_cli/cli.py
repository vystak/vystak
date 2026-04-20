"""Vystak CLI entry point."""

import click

# Trigger auto-registration of bundled channel plugins.
# Side-effecting imports are the intended mechanism here; keep them at top level
# so ruff's SIM/I rules don't re-order or flag them.
import vystak_channel_chat  # noqa: F401 — registers ChannelType.CHAT plugin
import vystak_channel_slack  # noqa: F401 — registers ChannelType.SLACK plugin

from vystak_cli import __version__
from vystak_cli.commands import apply, destroy, init, logs, plan, status


@click.group()
@click.version_option(version=__version__)
def cli():
    """Vystak — declarative AI agent orchestration."""


cli.add_command(init)
cli.add_command(plan)
cli.add_command(apply)
cli.add_command(destroy)
cli.add_command(status)
cli.add_command(logs)


if __name__ == "__main__":
    cli()
