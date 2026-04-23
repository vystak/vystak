"""vystak apply — deploy or update agents and channels."""

from pathlib import Path

import click
from vystak.secrets.env_loader import load_env_file
from vystak_adapter_langchain import LangChainAdapter
from vystak_provider_docker.transport_wiring import (
    build_routes_json,
    get_transport_plugin,
)

from vystak_cli.loader import find_agent_file, load_definitions
from vystak_cli.provider_factory import get_provider


@click.command()
@click.argument("files", nargs=-1, type=click.Path(exists=True))
@click.option("--file", "file_path", default=None, help="Path to agent definition file (legacy)")
@click.option(
    "--force", is_flag=True, default=False, help="Force redeploy even if no changes detected"
)
@click.option(
    "--env",
    "-e",
    default=None,
    envvar="VYSTAK_ENV",
    help="Environment name. Applies vystak.<env>.py overlay if present.",
)
@click.option(
    "--env-file",
    "env_file",
    default=".env",
    show_default=True,
    type=click.Path(),
    help="Path to the .env file used to bootstrap vault secrets at apply time.",
)
@click.option(
    "--allow-missing",
    is_flag=True,
    default=False,
    help=(
        "Allow declared vault secrets to be absent both locally (in .env) and in "
        "the vault at apply time. Without this flag, a missing secret aborts apply."
    ),
)
def apply(files, file_path, force, env, env_file, allow_missing):
    """Deploy or update agents and channels."""
    if files:
        paths = [Path(f) for f in files]
    elif file_path:
        paths = [Path(file_path)]
    else:
        paths = [find_agent_file()]

    base_dir = (
        paths[0].parent
        if paths[0].is_file()
        else paths[0].parent
        if paths[0].is_dir()
        else Path.cwd()
    )
    defs = load_definitions(paths, base_dir=base_dir)
    click.echo(f"Loaded {len(defs.agents)} agent(s), {len(defs.channels)} channel(s)")

    if env:
        from vystak_cli.loader import load_environment_override

        base_path = paths[0]
        override = load_environment_override(base_path, env)
        defs.agents = override.apply(defs.agents)
        click.echo(f"Environment: {env}")
    else:
        click.echo("Environment: (base)")

    # Load bootstrap env values from `.env` (or --env-file). Values are only
    # used during apply to push missing secrets into the vault; they are never
    # persisted by vystak. When the file is absent we silently continue — the
    # user may have pre-populated the vault by other means.
    env_path = Path(env_file)
    env_values = load_env_file(env_path, optional=True)
    if env_values:
        click.echo(f"Env file: {env_path}  ({len(env_values)} value(s))")
    else:
        click.echo(f"Env file: {env_path}  (not present or empty)")

    _run_provider_apply(
        agents=defs.agents,
        channels=defs.channels,
        vault=defs.vault,
        env_values=env_values,
        force=force,
        allow_missing=allow_missing,
        paths=paths,
    )


def _run_provider_apply(
    *,
    agents,
    channels,
    vault,
    env_values: dict[str, str],
    force: bool,
    allow_missing: bool,
    paths: list[Path],
) -> None:
    """Execute the agents- and channels- provisioning loop.

    Extracted from the click command so tests can patch this single symbol
    (`vystak_cli.commands.apply._run_provider_apply`) to assert the vault,
    env_values, and flags are threaded through correctly without having to
    stub out Azure / Docker clients.
    """
    adapter = LangChainAdapter()
    deployed_agents: list[dict] = []

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

        # Thread vault + env_values + flags into the provider *before* plan/
        # apply. AzureProvider uses these to build the KV/UAMI/Grant/SecretSync
        # subgraph (v1 secret-manager). DockerProvider uses them to build the
        # HashiCorp Vault subgraph (Server/Init/Unseal/AppRole/Sidecar) and
        # rejects Vault(type='key-vault') at plan time.
        if hasattr(provider, "set_vault"):
            provider.set_vault(vault)
        # Pass channels so the Vault subgraph enumerates channel principals
        # alongside agent + workspace. Without this, a vault-declared
        # deploy pushes channel secrets to KV but creates no per-channel
        # AppRole or sidecar, and the channel silently falls back to env
        # passthrough — defeating the Vault guarantee.
        if hasattr(provider, "set_channels"):
            provider.set_channels(channels)
        if hasattr(provider, "set_env_values"):
            provider.set_env_values(env_values)
        if hasattr(provider, "set_force_sync"):
            provider.set_force_sync(force)
        if hasattr(provider, "set_allow_missing"):
            provider.set_allow_missing(allow_missing)

        current_hash = provider.get_hash(agent.name)
        deploy_plan = provider.plan(agent, current_hash)

        if not deploy_plan.actions and not force:
            click.echo("  No changes. Already up to date.")
            # Still fetch the live URL so downstream channel route-resolution
            # has this agent on the map. Without this, rebuilt channels lose
            # routes for agents that didn't change this apply.
            resolved_url = "(unchanged)"
            try:
                live_status = provider.status(agent.name)
                info = getattr(live_status, "info", {}) or {}
                if info.get("url"):
                    resolved_url = info["url"]
            except Exception:
                pass
            deployed_agents.append({"name": agent.name, "url": resolved_url, "agent": agent})
            continue

        if not deploy_plan.actions and force:
            click.echo("  No changes detected, forcing redeploy.")
            deploy_plan.actions.append("Force redeploy")

        click.echo("  Deploying:")
        provider.set_generated_code(code)
        provider.set_agent(agent)

        if hasattr(provider, "set_listener"):
            from vystak.provisioning import PrintListener

            provider.set_listener(PrintListener(indent="    "))

        # v1: peer-route wiring is only implemented for Docker; Azure agents
        # use the manual env-var export workaround until ACA defaultDomain
        # lookup is added. AgentClient needs the {short: canonical} map to
        # resolve short names in ask_agent() calls; build it for every
        # Docker transport (HTTP carries real URLs, NATS subjects — the
        # address field is transport-specific but the mapping itself is
        # transport-agnostic).
        peer_routes: str | None = None
        if (
            agent.platform is not None
            and agent.platform.provider.type == "docker"
            and agent.platform.transport is not None
        ):
            try:
                plugin = get_transport_plugin(agent.platform.transport.type)
                peer_routes = build_routes_json(list(agents), plugin, agent.platform)
            except (KeyError, Exception):
                pass

        result = provider.apply(deploy_plan, peer_routes=peer_routes)

        if result.success:
            click.echo("  OK")
            url = (
                result.info.get("url", result.message)
                if hasattr(result, "info")
                else result.message
            )
            deployed_agents.append(
                {"name": agent.name, "url": url, "agent": agent, "result": result}
            )
        else:
            click.echo("FAILED")
            click.echo(f"  Error: {result.message}", err=True)
            raise SystemExit(1)

    deployed_channels: list[dict] = []

    for channel in channels:
        click.echo(f"\nChannel: {channel.name}")

        provider = get_provider(channel)
        # Thread vault into the channel provider too — apply_channel uses
        # it to wire the channel container to its pre-provisioned Vault
        # Agent sidecar volume (created during the agent's apply()).
        if hasattr(provider, "set_vault"):
            provider.set_vault(vault)
        try:
            current_hash = provider.get_channel_hash(channel)
            deploy_plan = provider.plan_channel(channel, current_hash)
        except NotImplementedError as e:
            click.echo(f"  Skipped: {e}")
            continue

        if not deploy_plan.actions and not force:
            click.echo("  No changes. Already up to date.")
            deployed_channels.append({"name": channel.name, "channel": channel})
            continue

        if not deploy_plan.actions and force:
            click.echo("  No changes detected, forcing redeploy.")
            deploy_plan.actions.append("Force redeploy")

        agents_by_name = {a["name"]: a["agent"] for a in deployed_agents}

        resolved_routes: dict[str, dict[str, str]] = {}
        for rule in channel.routes:
            if rule.agent in agents_by_name:
                peer_agent = agents_by_name[rule.agent]
                if peer_agent.platform is None:
                    continue
                try:
                    plugin = get_transport_plugin(peer_agent.platform.transport.type)
                    resolved_routes[rule.agent] = {
                        "canonical": peer_agent.canonical_name,
                        "address": plugin.resolve_address_for(peer_agent, peer_agent.platform),
                    }
                except (KeyError, Exception):
                    pass

        missing = [rule.agent for rule in channel.routes if rule.agent not in resolved_routes]
        if missing:
            click.echo(
                f"  Warning: route targets not deployed: {', '.join(missing)}",
                err=True,
            )

        click.echo("  Deploying:")
        if hasattr(provider, "set_listener"):
            from vystak.provisioning import PrintListener

            provider.set_listener(PrintListener(indent="    "))

        try:
            result = provider.apply_channel(deploy_plan, channel, resolved_routes)
        except NotImplementedError as e:
            click.echo(f"  Skipped: {e}")
            continue

        if result.success:
            click.echo("  OK")
            deployed_channels.append({"name": channel.name, "channel": channel, "result": result})
        else:
            click.echo("FAILED")
            click.echo(f"  Error: {result.message}", err=True)
            raise SystemExit(1)

    if deployed_agents or deployed_channels:
        _print_summary(deployed_agents, deployed_channels)


def _resolve_agent_urls(deployed_agents: list[dict]) -> dict[str, str]:
    """Map agent name → URL reachable from channel containers on vystak-net.

    For Docker, agents are addressable by their container name on the shared
    network: `http://vystak-<agent>:8000`. For Azure etc., the external URL
    from the deploy result is used.
    """
    urls: dict[str, str] = {}
    for d in deployed_agents:
        agent = d["agent"]
        provider_type = "docker"
        if agent.platform and agent.platform.provider:
            provider_type = agent.platform.provider.type

        if provider_type == "docker":
            urls[agent.name] = f"http://vystak-{agent.name}:8000"
            continue

        result = d.get("result")
        if result and hasattr(result, "message") and " at " in result.message:
            urls[agent.name] = result.message.split(" at ", 1)[1]
            continue

        url = d.get("url")
        if url and url != "(unchanged)":
            urls[agent.name] = url

    return urls


def _print_summary(deployed_agents: list[dict], deployed_channels: list[dict]) -> None:
    click.echo("\n" + "=" * 60)
    click.echo(
        f"Deployment complete — {len(deployed_agents)} agent(s), "
        f"{len(deployed_channels)} channel(s)"
    )
    click.echo("=" * 60)

    first_platform = None
    for d in deployed_agents:
        if d["agent"].platform:
            first_platform = d["agent"].platform
            break
    if first_platform is None:
        for d in deployed_channels:
            if d["channel"].platform:
                first_platform = d["channel"].platform
                break

    if first_platform:
        provider_type = first_platform.provider.type
        config = first_platform.provider.config

        click.echo("\nShared Infrastructure:")

        if provider_type == "azure":
            click.echo(f"  Provider:     Azure ({config.get('location', 'unknown')})")
            if config.get("resource_group"):
                click.echo(f"  Resource Group: {config['resource_group']}")
        elif provider_type == "docker":
            click.echo("  Provider:     Docker (local)")
            click.echo("  Network:      vystak-net")

    if deployed_agents:
        click.echo("\nAgents:")
        max_name = max(len(d["name"]) for d in deployed_agents)
        for d in deployed_agents:
            result = d.get("result")
            if result and hasattr(result, "message"):
                msg = result.message
                url = msg.split(" at ", 1)[1] if " at " in msg else msg
            else:
                url = d.get("url", "")
            click.echo(f"  {d['name']:<{max_name}}  {url}")

    if deployed_channels:
        click.echo("\nChannels:")
        max_name = max(len(d["name"]) for d in deployed_channels)
        for d in deployed_channels:
            result = d.get("result")
            msg = result.message if result and hasattr(result, "message") else ""
            click.echo(f"  {d['name']:<{max_name}}  {msg}")


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
