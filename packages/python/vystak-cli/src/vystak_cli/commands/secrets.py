"""vystak secrets — list/push/set/diff subcommands.

All subcommands operate on secrets declared in ``vystak.yaml`` and materialize
through the declared ``Vault`` backend (Azure Key Vault in v1).

SECURITY CONTRACT: these commands print secret **names** and presence/diff
**categories** only. Actual secret values MUST NEVER appear in output at any
verbosity level.
"""

from pathlib import Path

import click
import yaml
from vystak.schema.multi_loader import load_multi_yaml


@click.group()
def secrets():
    """Manage secrets declared by agents, workspaces, channels."""


# --- internal helpers -----------------------------------------------------


def _load_config(config_path: Path) -> tuple[list, list, object]:
    """Return (agents, channels, vault) from a vystak.yaml file."""
    with open(config_path) as f:
        data = yaml.safe_load(f)
    return load_multi_yaml(data)


def _collect_declared_secrets(config_path: Path) -> tuple[list[str], str | None]:
    """Return (declared secret names, vault identifier) for the given config.

    Declared names = union of agent.secrets, agent.workspace.secrets,
    channel.secrets. Order-preserving de-dupe. Vault identifier is the
    ``config["vault_name"]`` if set, else the Vault's logical name. Returns
    ``(names, None)`` when the config declares no vault.
    """
    agents, channels, vault = _load_config(config_path)
    names: list[str] = []
    for agent in agents:
        names.extend(s.name for s in agent.secrets)
        if agent.workspace is not None:
            names.extend(s.name for s in agent.workspace.secrets)
    for ch in channels:
        names.extend(s.name for s in ch.secrets)

    seen: set[str] = set()
    unique: list[str] = []
    for n in names:
        if n not in seen:
            seen.add(n)
            unique.append(n)

    vault_name: str | None = None
    if vault is not None:
        vault_name = vault.config.get("vault_name") if vault.config else None
        if not vault_name:
            vault_name = vault.name
    return unique, vault_name


def _kv_list_names(vault_name: str) -> list[str]:
    """Fetch secret NAMES from Key Vault. Never returns values."""
    from azure.identity import DefaultAzureCredential
    from azure.keyvault.secrets import SecretClient

    client = SecretClient(
        vault_url=f"https://{vault_name}.vault.azure.net/",
        credential=DefaultAzureCredential(),
    )
    return [p.name for p in client.list_properties_of_secrets()]


# --- subcommands ----------------------------------------------------------


@secrets.command("list")
@click.option("--file", default="vystak.yaml", help="Path to vystak.yaml")
def list_cmd(file: str):
    """List declared secrets and whether each is present in the vault."""
    declared, vault_name = _collect_declared_secrets(Path(file))

    if vault_name:
        kv_names = set(_kv_list_names(vault_name))
        click.echo(f"Declared secrets (vault: {vault_name}):")
    else:
        kv_names = set()
        click.echo("Declared secrets (no vault, env-passthrough):")

    for name in declared:
        if vault_name:
            status = "present in vault" if name in kv_names else "absent in vault"
        else:
            status = "env-passthrough"
        click.echo(f"  {name}  [{status}]")
