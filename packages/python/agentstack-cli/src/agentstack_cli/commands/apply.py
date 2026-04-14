"""agentstack apply — deploy or update agents."""

from pathlib import Path

import click

from agentstack.hash import hash_agent
from agentstack_adapter_langchain import LangChainAdapter
from agentstack_cli.loader import find_agent_file, load_agents
from agentstack_cli.provider_factory import get_provider


@click.command()
@click.argument("files", nargs=-1, type=click.Path(exists=True))
@click.option("--file", "file_path", default=None, help="Path to agent definition file (legacy)")
def apply(files, file_path):
    """Deploy or update agents."""
    if files:
        paths = [Path(f) for f in files]
    elif file_path:
        paths = [Path(file_path)]
    else:
        paths = [find_agent_file()]

    base_dir = paths[0].parent if paths[0].is_file() else paths[0].parent if paths[0].is_dir() else Path.cwd()
    agents = load_agents(paths, base_dir=base_dir)
    click.echo(f"Loaded {len(agents)} agent(s)")

    adapter = LangChainAdapter()
    deployed: list[dict] = []

    for agent in agents:
        click.echo(f"\nAgent: {agent.name}")

        click.echo("  Validating... ", nl=False)
        errors = adapter.validate(agent)
        if errors:
            click.echo("FAILED")
            for err in errors:
                click.echo(f"    {err.field}: {err.message}", err=True)
            raise SystemExit(1)
        click.echo("OK")

        click.echo("  Generating code... ", nl=False)
        agent_base = _find_agent_base_dir(agent.name, paths)
        code = adapter.generate(agent, base_dir=agent_base)
        click.echo("OK")

        provider = get_provider(agent)
        current_hash = provider.get_hash(agent.name)
        deploy_plan = provider.plan(agent, current_hash)

        if not deploy_plan.actions:
            click.echo("  No changes. Already up to date.")
            deployed.append({"name": agent.name, "url": "(unchanged)", "agent": agent})
            continue

        click.echo("  Deploying... ", nl=False)
        provider.set_generated_code(code)
        provider.set_agent(agent)
        result = provider.apply(deploy_plan)

        if result.success:
            click.echo("OK")
            url = result.info.get("url", result.message) if hasattr(result, "info") else result.message
            deployed.append({"name": agent.name, "url": url, "agent": agent, "result": result})
        else:
            click.echo("FAILED")
            click.echo(f"  Error: {result.message}", err=True)
            raise SystemExit(1)

    # Deployment summary
    if deployed:
        _print_summary(deployed)


def _print_summary(deployed: list[dict]) -> None:
    """Print deployment summary with infrastructure and agent details."""
    click.echo("\n" + "=" * 60)
    click.echo(f"Deployment complete — {len(deployed)} agent(s) deployed")
    click.echo("=" * 60)

    # Shared infrastructure details (from first agent with a platform)
    first_agent = next((d["agent"] for d in deployed if d["agent"].platform), None)
    if first_agent and first_agent.platform:
        provider_type = first_agent.platform.provider.type
        config = first_agent.platform.provider.config

        click.echo("\nShared Infrastructure:")

        if provider_type == "azure":
            click.echo(f"  Provider:     Azure ({config.get('location', 'unknown')})")
            if config.get("resource_group"):
                click.echo(f"  Resource Group: {config['resource_group']}")
        elif provider_type == "docker":
            click.echo(f"  Provider:     Docker (local)")
            click.echo(f"  Network:      agentstack-net")

    # Agent URLs
    click.echo("\nAgents:")
    max_name = max(len(d["name"]) for d in deployed)
    for d in deployed:
        result = d.get("result")
        if result and hasattr(result, "message"):
            # Extract URL from message like "Deployed X at https://..."
            msg = result.message
            if " at " in msg:
                url = msg.split(" at ", 1)[1]
            else:
                url = msg
        else:
            url = d.get("url", "")
        click.echo(f"  {d['name']:<{max_name}}  {url}")

    # Connect command
    click.echo("\nConnect:")
    for d in deployed:
        result = d.get("result")
        if result and hasattr(result, "message") and " at " in result.message:
            url = result.message.split(" at ", 1)[1]
            click.echo(f"  agentstack-chat --url {url}")
            break  # Show connect for first agent only


def _find_agent_base_dir(agent_name: str, paths: list[Path]) -> Path:
    """Find the base directory for an agent's tools."""
    for p in paths:
        if p.is_dir() and p.name == agent_name:
            return p
        if p.is_dir():
            subdir = p / agent_name
            if subdir.exists():
                return subdir
    first = paths[0] if paths else Path.cwd()
    return first if first.is_dir() else first.parent
