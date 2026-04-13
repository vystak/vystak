"""agentstack logs — tail agent container logs."""

import click

from agentstack_cli.loader import find_agent_file, load_agent_from_file
from agentstack_cli.provider_factory import get_provider


@click.command()
@click.option("--file", "file_path", default=None, help="Path to agent definition file")
@click.option("--name", "agent_name", default=None, help="Agent name (alternative to --file)")
@click.option("--follow", "-f", is_flag=True, default=False, help="Follow log output")
@click.option("--tail", "-n", "tail_lines", default=50, help="Number of lines to show")
def logs(file_path, agent_name, follow, tail_lines):
    """Tail agent container logs."""
    agent = None
    if agent_name is None:
        path = find_agent_file(file=file_path)
        agent = load_agent_from_file(path)
        agent_name = agent.name

    # Determine provider type — logs currently only supported for Docker
    if agent:
        provider = get_provider(agent)
    else:
        from agentstack_provider_docker import DockerProvider
        provider = DockerProvider()

    from agentstack_provider_docker import DockerProvider as _DockerType
    if not isinstance(provider, _DockerType):
        click.echo(f"Logs are not yet supported for {agent.platform.provider.type} provider.", err=True)
        raise SystemExit(1)

    container = provider._get_container(agent_name)

    if container is None:
        click.echo(f"Agent '{agent_name}' is not deployed.", err=True)
        raise SystemExit(1)

    if follow:
        click.echo(f"Following logs for {agent_name} (Ctrl+C to stop)...")
        try:
            for line in container.logs(stream=True, follow=True, tail=tail_lines):
                click.echo(line.decode("utf-8", errors="replace"), nl=False)
        except KeyboardInterrupt:
            pass
    else:
        output = container.logs(tail=tail_lines).decode("utf-8", errors="replace")
        click.echo(output, nl=False)
