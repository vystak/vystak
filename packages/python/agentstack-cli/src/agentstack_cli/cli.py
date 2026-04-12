"""AgentStack CLI entry point."""

import click

from agentstack_cli import __version__
from agentstack_cli.commands import apply, destroy, init, plan, status


@click.group()
@click.version_option(version=__version__)
def cli():
    """AgentStack — declarative AI agent orchestration."""


cli.add_command(init)
cli.add_command(plan)
cli.add_command(apply)
cli.add_command(destroy)
cli.add_command(status)
