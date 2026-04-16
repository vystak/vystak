"""vystak apply — deploy or update agents."""

from pathlib import Path

import click

from vystak.hash import hash_agent
from vystak_adapter_langchain import LangChainAdapter
from vystak_cli.loader import find_agent_file, load_agents
from vystak_cli.provider_factory import get_provider


@click.command()
@click.argument("files", nargs=-1, type=click.Path(exists=True))
@click.option("--file", "file_path", default=None, help="Path to agent definition file (legacy)")
@click.option("--force", is_flag=True, default=False, help="Force redeploy even if no changes detected")
def apply(files, file_path, force):
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
        provider.set_agent(agent)
        current_hash = provider.get_hash(agent.name)
        deploy_plan = provider.plan(agent, current_hash)

        if not deploy_plan.actions and not force:
            click.echo("  No changes. Already up to date.")
            deployed.append({"name": agent.name, "url": "(unchanged)", "agent": agent})
            continue

        if not deploy_plan.actions and force:
            click.echo("  No changes detected, forcing redeploy.")
            deploy_plan.actions.append("Force redeploy")

        click.echo("  Deploying:")
        provider.set_generated_code(code)
        provider.set_agent(agent)

        # Attach progress listener if provider supports it
        if hasattr(provider, "set_listener"):
            from vystak.provisioning import PrintListener
            provider.set_listener(PrintListener(indent="    "))

        result = provider.apply(deploy_plan)

        if result.success:
            click.echo("  OK")
            url = result.info.get("url", result.message) if hasattr(result, "info") else result.message
            deployed.append({"name": agent.name, "url": url, "agent": agent, "result": result})
        else:
            click.echo("FAILED")
            click.echo(f"  Error: {result.message}", err=True)
            raise SystemExit(1)

    # Deploy gateway and register agents if multiple agents
    gateway_url = None
    if len(deployed) > 1:
        click.echo("\nGateway:")
        click.echo("  Deploying... ", nl=False)
        from vystak_cli.gateway import deploy_gateway, register_agents, inject_gateway_env
        gateway_url = deploy_gateway(deployed)
        if gateway_url:
            click.echo("OK")
            click.echo(f"  {gateway_url}")
            click.echo("  Registering agents...")
            register_agents(gateway_url, deployed)
            click.echo("  Injecting gateway URL into agents...")
            inject_gateway_env(gateway_url, deployed)
        else:
            click.echo("skipped")

    # Deployment summary
    if deployed:
        _print_summary(deployed, gateway_url=gateway_url)


def _print_summary(deployed: list[dict], gateway_url: str | None = None) -> None:
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
            click.echo(f"  Network:      vystak-net")

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

    # Gateway
    if gateway_url:
        click.echo(f"\nGateway:")
        click.echo(f"  {gateway_url}")
        click.echo(f"  Agents:  {gateway_url}/agents")
        click.echo(f"  Health:  {gateway_url}/health")

    # Connect command
    click.echo("\nConnect:")
    if gateway_url:
        click.echo(f"  vystak-chat --gateway {gateway_url}")
    else:
        for d in deployed:
            result = d.get("result")
            if result and hasattr(result, "message") and " at " in result.message:
                url = result.message.split(" at ", 1)[1]
                click.echo(f"  vystak-chat --url {url}")
                break


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
