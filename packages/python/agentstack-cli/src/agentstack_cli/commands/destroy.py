"""agentstack destroy — stop and remove agents."""

from pathlib import Path

import click

from agentstack_cli.loader import find_agent_file, load_agents
from agentstack_cli.provider_factory import get_provider


@click.command()
@click.argument("files", nargs=-1, type=click.Path(exists=True))
@click.option("--file", "file_path", default=None, help="Path to agent definition file (legacy)")
@click.option("--name", "agent_name", default=None, help="Destroy a specific agent by name")
@click.option("--include-resources", is_flag=True, default=False,
              help="Also remove backing infrastructure")
def destroy(files, file_path, agent_name, include_resources):
    """Stop and remove deployed agents."""
    if agent_name and not files and not file_path:
        from agentstack_provider_docker import DockerProvider
        provider = DockerProvider()
        click.echo(f"Destroying: {agent_name}")
        provider.destroy(agent_name, include_resources=include_resources)
        click.echo(f"Destroyed: {agent_name}")
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
        if not agents:
            click.echo(f"Agent '{agent_name}' not found in definition.", err=True)
            raise SystemExit(1)

    for agent in agents:
        click.echo(f"Destroying: {agent.name}")
        provider = get_provider(agent)
        provider.set_agent(agent)

        if include_resources and hasattr(provider, "list_resources"):
            resources = provider.list_resources(agent.name)
            if resources:
                click.echo("  Resources to delete:")
                for r in resources:
                    click.echo(f"    - {r['type']}: {r['name']}")

        try:
            provider.destroy(agent.name, include_resources=include_resources)
            click.echo("  OK")
        except Exception as e:
            click.echo(f"  FAILED: {e}", err=True)

    click.echo(f"Destroyed {len(agents)} agent(s)")
