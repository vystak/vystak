"""AgentStack chat CLI entry point."""

import click

from agentstack_chat import __version__
from agentstack_chat.chat import run_repl


@click.command()
@click.version_option(version=__version__)
@click.option("--url", default=None, help="Connect to agent URL immediately on start")
def cli(url):
    """AgentStack Chat — interactive REPL for talking to deployed agents."""
    run_repl(auto_connect_url=url)
