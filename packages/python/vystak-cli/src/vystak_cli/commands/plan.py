"""vystak plan — show what would change."""

from pathlib import Path

import click
from vystak.hash import hash_agent, hash_channel
from vystak_adapter_langchain import LangChainAdapter

from vystak_cli.loader import find_agent_file, load_definitions
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
    defs = load_definitions(paths, base_dir=base_dir)

    adapter = LangChainAdapter()

    for agent in defs.agents:
        click.echo(f"Agent: {agent.name}  ({agent.canonical_name})")
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

    for channel in defs.channels:
        click.echo(f"Channel: {channel.name}  ({channel.canonical_name})")
        click.echo(f"  Type: {channel.type.value}")
        if channel.platform:
            click.echo(f"  Platform: {channel.platform.type} ({channel.platform.provider.type})")
        if channel.routes:
            click.echo(f"  Routes: {len(channel.routes)}")
            for rule in channel.routes:
                click.echo(f"    → {rule.agent}  match={rule.match}")

        try:
            provider = get_provider(channel)
            current_hash = provider.get_channel_hash(channel)
            deploy_plan = provider.plan_channel(channel, current_hash)

            if not deploy_plan.actions:
                click.echo("  No changes. Already up to date.")
            else:
                click.echo("  Changes:")
                for action in deploy_plan.actions:
                    click.echo(f"    + {action}")
        except NotImplementedError as e:
            tree = hash_channel(channel)
            click.echo(f"  Provisioning not yet supported: {e}", err=True)
            click.echo(f"  Target hash: {tree.root[:16]}...")
        except Exception as e:
            tree = hash_channel(channel)
            click.echo(f"  Could not connect to provider: {e}", err=True)
            click.echo(f"  Target hash: {tree.root[:16]}...")

        click.echo()

    _emit_vault_plan(defs)


def _emit_vault_plan(defs) -> None:
    """Emit Vault / Identities / Secrets / Grants sections when a vault is
    declared in the loaded config.

    Kept offline: the real push/skip decision happens at `apply` time inside
    ``SecretSyncNode`` — plan only surfaces *what will be attempted*. No secret
    VALUES are ever printed here at any verbosity.
    """
    vault = getattr(defs, "vault", None)
    if vault is None:
        return

    # --- Vault
    create_or_link = "create" if vault.mode.value == "deploy" else "link"
    click.echo("Vault:")
    click.echo(
        f"  {vault.name} "
        f"({vault.type.value}, {vault.mode.value}, {vault.provider.name})"
        f"  will {create_or_link}"
    )
    click.echo()

    # --- Identities (one UAMI per agent-side and workspace-side secret set)
    click.echo("Identities:")
    for agent in defs.agents:
        if agent.secrets:
            click.echo(f"  {agent.name}-agent      will create (UAMI, lifecycle: None)")
        if agent.workspace is not None and agent.workspace.secrets:
            click.echo(f"  {agent.name}-workspace  will create (UAMI, lifecycle: None)")
    click.echo()

    # --- Secrets — declared-name list only, status deferred to apply time
    click.echo("Secrets:")
    seen: set[str] = set()
    for agent in defs.agents:
        for s in agent.secrets:
            if s.name in seen:
                continue
            seen.add(s.name)
            click.echo(
                f"  {s.name}  will push  "
                f"(presence depends on .env and vault state)"
            )
        if agent.workspace is not None:
            for s in agent.workspace.secrets:
                if s.name in seen:
                    continue
                seen.add(s.name)
                click.echo(
                    f"  {s.name}  will push  "
                    f"(presence depends on .env and vault state)"
                )
    for channel in defs.channels:
        for s in channel.secrets:
            if s.name in seen:
                continue
            seen.add(s.name)
            click.echo(
                f"  {s.name}  will push  "
                f"(presence depends on .env and vault state)"
            )
    click.echo()

    # --- Grants — agent UAMI / workspace UAMI gets read on each declared secret
    click.echo("Grants:")
    for agent in defs.agents:
        for s in agent.secrets:
            click.echo(f"  {agent.name}-agent      \u2192 {s.name}  will assign")
        if agent.workspace is not None:
            for s in agent.workspace.secrets:
                click.echo(
                    f"  {agent.name}-workspace  \u2192 {s.name}  will assign"
                )
    click.echo()
