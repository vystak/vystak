"""vystak destroy — stop and remove agents and channels."""

from pathlib import Path

import click

from vystak_cli.loader import find_agent_file, load_definitions
from vystak_cli.provider_factory import get_provider


@click.command()
@click.argument("files", nargs=-1, type=click.Path(exists=True))
@click.option("--file", "file_path", default=None, help="Path to agent definition file (legacy)")
@click.option("--name", "agent_name", default=None, help="Destroy a specific agent by name")
@click.option(
    "--include-resources", is_flag=True, default=False, help="Also remove backing infrastructure"
)
@click.option(
    "--no-wait",
    is_flag=True,
    default=False,
    help="Don't wait for Azure resource deletion to complete",
)
@click.option(
    "--delete-vault",
    is_flag=True,
    default=False,
    help=(
        "Also delete the HashiCorp Vault container, volume, and "
        ".vystak/vault/init.json host file. Unrecoverable — loses every "
        "secret value stored in the vault."
    ),
)
@click.option(
    "--keep-sidecars",
    is_flag=True,
    default=False,
    help=(
        "Leave Vault Agent sidecar containers and their per-principal "
        "secrets/approle volumes in place. Useful during iteration."
    ),
)
@click.option(
    "--delete-workspace-data",
    is_flag=True,
    default=False,
    help=(
        "Also remove the vystak-<agent>-workspace-data volume, wiping "
        "every file the workspace has written. Unrecoverable."
    ),
)
@click.option(
    "--keep-workspace",
    is_flag=True,
    default=False,
    help=(
        "Leave the vystak-<agent>-workspace container running. Useful "
        "during iteration when only the agent container needs recycling."
    ),
)
def destroy(
    files,
    file_path,
    agent_name,
    include_resources,
    no_wait,
    delete_vault,
    keep_sidecars,
    delete_workspace_data,
    keep_workspace,
):
    """Stop and remove deployed agents and channels."""
    if agent_name and not files and not file_path:
        from vystak_provider_docker import DockerProvider

        provider = DockerProvider()
        click.echo(f"Destroying: {agent_name}")
        provider.destroy(
            agent_name,
            include_resources=include_resources,
            no_wait=no_wait,
            delete_vault=delete_vault,
            keep_sidecars=keep_sidecars,
            delete_workspace_data=delete_workspace_data,
            keep_workspace=keep_workspace,
        )
        click.echo(f"Destroyed: {agent_name}")
        return

    if files:
        paths = [Path(f) for f in files]
    elif file_path:
        paths = [Path(file_path)]
    else:
        paths = [find_agent_file()]

    base_dir = paths[0].parent if paths[0].is_file() else paths[0].parent
    defs = load_definitions(paths, base_dir=base_dir)

    agents = defs.agents
    channels = defs.channels

    if agent_name:
        agents = [a for a in agents if a.name == agent_name]
        channels = [c for c in channels if c.name == agent_name]
        if not agents and not channels:
            click.echo(f"'{agent_name}' not found in definition.", err=True)
            raise SystemExit(1)

    for channel in channels:
        click.echo(f"Destroying channel: {channel.name}")
        provider = get_provider(channel)
        try:
            provider.destroy_channel(channel)
            click.echo("  OK")
        except NotImplementedError as e:
            click.echo(f"  Skipped: {e}")
        except Exception as e:
            click.echo(f"  FAILED: {e}", err=True)

    vault = getattr(defs, "vault", None)
    for agent in agents:
        click.echo(f"Destroying agent: {agent.name}")
        provider = get_provider(agent)
        provider.set_agent(agent)
        # Thread vault declaration so the provider knows to tear down
        # Vault-specific resources (sidecars, approle volumes, secret
        # volumes) via its _destroy_vault_resources branch.
        if hasattr(provider, "set_vault") and vault:
            provider.set_vault(vault)
        # Channels are needed so _destroy_vault_resources enumerates
        # channel principals when cleaning up per-principal sidecars +
        # volumes. Channels on this config were co-deployed with the
        # agent via the same _add_vault_nodes pass.
        if hasattr(provider, "set_channels"):
            provider.set_channels(channels)

        if include_resources and hasattr(provider, "list_resources"):
            resources = provider.list_resources(agent.name)
            if resources:
                click.echo("  Resources to delete:")
                for r in resources:
                    click.echo(f"    - {r['type']}: {r['name']}")

        try:
            provider.destroy(
                agent.name,
                include_resources=include_resources,
                no_wait=no_wait,
                delete_vault=delete_vault,
                keep_sidecars=keep_sidecars,
                delete_workspace_data=delete_workspace_data,
                keep_workspace=keep_workspace,
            )
            click.echo("  OK" if not no_wait else "  OK (delete in progress)")
        except Exception as e:
            click.echo(f"  FAILED: {e}", err=True)

    # Default path: clean up per-principal env files + SSH key directories
    # that were materialized at apply time. Vault-path state (init.json,
    # approle volumes) is handled by provider.destroy under --delete-vault.
    if vault is None:
        _cleanup_default_path_state(agents)

    click.echo(f"Destroyed {len(agents)} agent(s), {len(channels)} channel(s)")


def _cleanup_default_path_state(agents) -> None:
    """Remove .vystak/env/*.env and .vystak/ssh/<agent>/ for destroyed agents."""
    import shutil

    env_dir = Path(".vystak") / "env"
    ssh_root = Path(".vystak") / "ssh"

    for agent in agents:
        for suffix in ("-agent.env", "-workspace.env"):
            p = env_dir / f"{agent.name}{suffix}"
            if p.exists():
                p.unlink()
        d = ssh_root / agent.name
        if d.exists():
            shutil.rmtree(d)
