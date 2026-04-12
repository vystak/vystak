"""AgentStack chat CLI entry point."""

import click

from agentstack_chat import __version__
from agentstack_chat.chat import run_repl, run_oneshot


@click.command()
@click.version_option(version=__version__)
@click.option("--url", default=None, help="Connect to agent URL immediately on start")
@click.option("-p", "--prompt", default=None, help="Send a single message and exit")
def cli(url, prompt):
    """AgentStack Chat — interactive REPL for talking to deployed agents."""
    if prompt:
        run_oneshot(url=url, message=prompt)
    else:
        run_repl(auto_connect_url=url)
