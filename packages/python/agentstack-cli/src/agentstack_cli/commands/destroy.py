"""agentstack destroy — stop and remove an agent."""

import click

from agentstack_cli.loader import find_agent_file, load_agent_from_file
from agentstack_provider_docker import DockerProvider


@click.command()
@click.option("--file", "file_path", default=None, help="Path to agent definition file")
@click.option("--name", "agent_name", default=None, help="Agent name (alternative to --file)")
def destroy(file_path, agent_name):
    """Stop and remove a deployed agent."""
    if agent_name is None:
        path = find_agent_file(file=file_path)
        agent = load_agent_from_file(path)
        agent_name = agent.name

    click.echo(f"Destroying: {agent_name}")
    provider = DockerProvider()

    click.echo(f"Stopping container agentstack-{agent_name}... ", nl=False)
    try:
        provider.destroy(agent_name)
        click.echo("OK")
        click.echo(f"Destroyed: {agent_name}")
    except Exception as e:
        click.echo("FAILED")
        click.echo(f"  Error: {e}", err=True)
        raise SystemExit(1)
