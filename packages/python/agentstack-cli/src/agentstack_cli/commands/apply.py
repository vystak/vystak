"""agentstack apply — deploy or update an agent."""

import click

from agentstack.hash import hash_agent
from agentstack_adapter_langchain import LangChainAdapter
from agentstack_cli.loader import find_agent_file, load_agent_from_file
from agentstack_provider_docker import DockerProvider


@click.command()
@click.option("--file", "file_path", default=None, help="Path to agent definition file")
def apply(file_path):
    """Deploy or update an agent."""
    path = find_agent_file(file=file_path)
    agent = load_agent_from_file(path)

    click.echo(f"Agent: {agent.name}")

    click.echo("Validating... ", nl=False)
    adapter = LangChainAdapter()
    errors = adapter.validate(agent)
    if errors:
        click.echo("FAILED")
        for err in errors:
            click.echo(f"  {err.field}: {err.message}", err=True)
        raise SystemExit(1)
    click.echo("OK")

    click.echo("Generating code... ", nl=False)
    code = adapter.generate(agent, base_dir=path.parent)
    click.echo("OK")

    provider = DockerProvider()
    current_hash = provider.get_hash(agent.name)
    deploy_plan = provider.plan(agent, current_hash)

    if not deploy_plan.actions:
        click.echo("No changes. Already up to date.")
        return

    click.echo("Building Docker image... ", nl=False)
    provider.set_generated_code(code)
    provider.set_agent(agent)
    result = provider.apply(deploy_plan)

    if result.success:
        click.echo("OK")
        click.echo()
        click.echo(f"Deployed: {agent.name}")
        click.echo(f"  {result.message}")
    else:
        click.echo("FAILED")
        click.echo(f"  Error: {result.message}", err=True)
        raise SystemExit(1)
