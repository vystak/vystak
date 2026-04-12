"""agentstack plan — show what would change."""

import click

from agentstack.hash import hash_agent
from agentstack_adapter_langchain import LangChainAdapter
from agentstack_cli.loader import find_agent_file, load_agent_from_file
from agentstack_provider_docker import DockerProvider


@click.command()
@click.option("--file", "file_path", default=None, help="Path to agent definition file")
def plan(file_path):
    """Show what would change if you applied."""
    path = find_agent_file(file=file_path)
    agent = load_agent_from_file(path)

    adapter = LangChainAdapter()
    errors = adapter.validate(agent)
    if errors:
        for err in errors:
            click.echo(f"Validation error: {err.field} — {err.message}", err=True)
        raise SystemExit(1)

    tree = hash_agent(agent)

    click.echo(f"Agent: {agent.name}")
    click.echo(f"Provider: {agent.model.provider.type} ({agent.model.model_name})")
    click.echo(f"Framework: langchain")
    click.echo()

    try:
        provider = DockerProvider()
        current_hash = provider.get_hash(agent.name)
        deploy_plan = provider.plan(agent, current_hash)

        if not deploy_plan.actions:
            click.echo("No changes. Already up to date.")
        else:
            click.echo("Changes:")
            for action in deploy_plan.actions:
                click.echo(f"  + {action}")
            click.echo()
            click.echo("Run 'agentstack apply' to deploy.")
    except Exception as e:
        click.echo(f"Could not connect to Docker: {e}", err=True)
        click.echo(f"Target hash: {tree.root[:16]}...")
