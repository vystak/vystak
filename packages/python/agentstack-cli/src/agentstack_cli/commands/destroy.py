"""agentstack destroy — stop and remove an agent."""

import click

from agentstack_cli.loader import find_agent_file, load_agent_from_file
from agentstack_cli.provider_factory import get_provider


@click.command()
@click.option("--file", "file_path", default=None, help="Path to agent definition file")
@click.option("--name", "agent_name", default=None, help="Agent name (alternative to --file)")
@click.option(
    "--include-resources",
    is_flag=True,
    default=False,
    help="Also remove backing resources (Postgres, ACR, etc.)",
)
def destroy(file_path, agent_name, include_resources):
    """Stop and remove a deployed agent."""
    agent = None
    if agent_name is None:
        path = find_agent_file(file=file_path)
        agent = load_agent_from_file(path)
        agent_name = agent.name

    click.echo(f"Destroying: {agent_name}")
    if agent:
        provider = get_provider(agent)
    else:
        from agentstack_provider_docker import DockerProvider
        provider = DockerProvider()

    if agent:
        provider.set_agent(agent)

    # List resources that will be affected
    if include_resources and hasattr(provider, "list_resources"):
        resources = provider.list_resources(agent_name)
        if resources:
            click.echo("Resources to delete:")
            for r in resources:
                click.echo(f"  - {r['type']}: {r['name']}")
        else:
            click.echo("No tagged resources found.")
    else:
        click.echo(f"  Container: agentstack-{agent_name}")

    try:
        provider.destroy(agent_name, include_resources=include_resources)
        click.echo("OK")
        if include_resources:
            click.echo("All tagged resources removed.")
        click.echo(f"Destroyed: {agent_name}")
    except Exception as e:
        click.echo("FAILED")
        click.echo(f"  Error: {e}", err=True)
        raise SystemExit(1)
