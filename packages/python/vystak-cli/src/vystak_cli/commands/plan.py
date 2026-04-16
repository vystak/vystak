"""vystak plan — show what would change."""

from pathlib import Path

import click

from vystak.hash import hash_agent
from vystak_adapter_langchain import LangChainAdapter
from vystak_cli.loader import find_agent_file, load_agents
from vystak_cli.provider_factory import get_provider


@click.command()
@click.argument("files", nargs=-1, type=click.Path(exists=True))
@click.option("--file", "file_path", default=None, help="Path to agent definition file (legacy)")
def plan(files, file_path):
    """Show what would change if you applied."""
    if files:
        paths = [Path(f) for f in files]
    elif file_path:
        paths = [Path(file_path)]
    else:
        paths = [find_agent_file()]

    base_dir = paths[0].parent if paths[0].is_file() else paths[0].parent
    agents = load_agents(paths, base_dir=base_dir)

    adapter = LangChainAdapter()

    for agent in agents:
        click.echo(f"Agent: {agent.name}")
        click.echo(f"  Provider: {agent.model.provider.type} ({agent.model.model_name})")
        if agent.platform:
            click.echo(f"  Platform: {agent.platform.type} ({agent.platform.provider.type})")

        errors = adapter.validate(agent)
        if errors:
            for err in errors:
                click.echo(f"  Validation error: {err.field} — {err.message}", err=True)
            continue

        try:
            provider = get_provider(agent)
            provider.set_agent(agent)
            current_hash = provider.get_hash(agent.name)
            deploy_plan = provider.plan(agent, current_hash)

            if not deploy_plan.actions:
                click.echo("  No changes. Already up to date.")
            else:
                click.echo("  Changes:")
                for action in deploy_plan.actions:
                    click.echo(f"    + {action}")
        except Exception as e:
            tree = hash_agent(agent)
            click.echo(f"  Could not connect to provider: {e}", err=True)
            click.echo(f"  Target hash: {tree.root[:16]}...")

        click.echo()
