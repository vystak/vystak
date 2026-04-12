"""CLI entry point."""

import click

from agentstack_cli import __version__
from agentstack_cli.commands.init import init


@click.group()
@click.version_option(__version__, prog_name="agentstack")
def cli() -> None:
    """AgentStack CLI — manage and deploy AI agents."""


cli.add_command(init)


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
