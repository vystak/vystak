"""agentstack status — show agent status."""

from pathlib import Path

import click

from agentstack_cli.loader import find_agent_file, load_agents
from agentstack_cli.provider_factory import get_provider


@click.command()
@click.argument("files", nargs=-1, type=click.Path(exists=True))
@click.option("--file", "file_path", default=None, help="Path to agent definition file (legacy)")
@click.option("--name", "agent_name", default=None, help="Show status for a specific agent")
def status(files, file_path, agent_name):
    """Show the status of deployed agents."""
    if agent_name and not files and not file_path:
        from agentstack_provider_docker import DockerProvider
        provider = DockerProvider()
        _show_status(provider, agent_name)
        return

    if files:
        paths = [Path(f) for f in files]
    elif file_path:
        paths = [Path(file_path)]
    else:
        paths = [find_agent_file()]

    base_dir = paths[0].parent if paths[0].is_file() else paths[0].parent
    agents = load_agents(paths, base_dir=base_dir)

    if agent_name:
        agents = [a for a in agents if a.name == agent_name]

    for agent in agents:
        provider = get_provider(agent)
        provider.set_agent(agent)
        _show_status(provider, agent.name)


def _show_status(provider, agent_name: str):
    agent_status = provider.status(agent_name)
    click.echo(f"Agent: {agent_name}")
    if agent_status.running:
        click.echo("  Status: running")
        if agent_status.hash:
            click.echo(f"  Hash: {agent_status.hash[:16]}...")
        info = agent_status.info
        if "url" in info and info["url"]:
            click.echo(f"  URL: {info['url']}")
        elif "ports" in info and "8000/tcp" in info["ports"] and info["ports"]["8000/tcp"]:
            host_port = info["ports"]["8000/tcp"][0].get("HostPort", "?")
            click.echo(f"  URL: http://localhost:{host_port}")
    else:
        click.echo("  Status: not deployed")
