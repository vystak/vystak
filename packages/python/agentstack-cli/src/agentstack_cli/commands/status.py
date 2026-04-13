"""agentstack status — show agent status."""

import click

from agentstack_cli.loader import find_agent_file, load_agent_from_file
from agentstack_cli.provider_factory import get_provider


@click.command()
@click.option("--file", "file_path", default=None, help="Path to agent definition file")
@click.option("--name", "agent_name", default=None, help="Agent name (alternative to --file)")
def status(file_path, agent_name):
    """Show the status of a deployed agent."""
    agent = None
    if agent_name is None:
        path = find_agent_file(file=file_path)
        agent = load_agent_from_file(path)
        agent_name = agent.name

    if agent:
        provider = get_provider(agent)
    else:
        from agentstack_provider_docker import DockerProvider
        provider = DockerProvider()
    agent_status = provider.status(agent_name)

    click.echo(f"Agent: {agent_name}")
    if agent_status.running:
        click.echo(f"Status: running")
        click.echo(f"Container: agentstack-{agent_name}")
        if agent_status.hash:
            click.echo(f"Hash: {agent_status.hash[:16]}...")
        ports = agent_status.info.get("ports", {})
        if ports and "8000/tcp" in ports and ports["8000/tcp"]:
            host_port = ports["8000/tcp"][0].get("HostPort", "?")
            click.echo(f"URL: http://localhost:{host_port}")
    else:
        click.echo(f"Status: not deployed")
