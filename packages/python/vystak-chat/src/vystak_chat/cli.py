"""Vystak chat CLI entry point."""

import click

from vystak_chat import __version__
from vystak_chat.chat import run_oneshot, run_repl


@click.command()
@click.version_option(version=__version__)
@click.option("--url", default=None, help="Connect to agent or chat channel URL")
@click.option("--gateway", default=None, help="Connect to a gateway to discover agents")
@click.option(
    "--model",
    default=None,
    help="Model to use on a chat channel (e.g. vystak/weather-agent)",
)
@click.option("-p", "--prompt", default=None, help="Send a single message and exit")
def cli(url, gateway, model, prompt):
    """Vystak Chat — interactive REPL for talking to deployed agents."""
    if prompt:
        run_oneshot(url=url, message=prompt, model_override=model)
    else:
        run_repl(auto_connect_url=url, auto_gateway_url=gateway)
