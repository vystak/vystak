"""vystak logs — tail agent container logs."""

import click

from vystak_cli.loader import find_agent_file, load_agents


@click.command()
@click.option("--file", "file_path", default=None, help="Path to agent definition file")
@click.option("--name", "agent_name", default=None, help="Agent name")
@click.option("--follow", "-f", is_flag=True, default=False, help="Follow log output")
@click.option("--tail", "-n", "tail_lines", default=50, help="Number of lines to show")
def logs(file_path, agent_name, follow, tail_lines):
    """Tail agent container logs."""
    if agent_name is None:
        path = find_agent_file(file=file_path)
        agents = load_agents([path])
        if len(agents) == 1:
            agent_name = agents[0].name
        else:
            click.echo("Multiple agents found. Use --name to specify which one.", err=True)
            for a in agents:
                click.echo(f"  {a.name}")
            raise SystemExit(1)

    # Logs is Docker-specific for now
    from vystak_provider_docker import DockerProvider

    provider = DockerProvider()
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
