"""Vystak CLI entry point."""

import click

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
