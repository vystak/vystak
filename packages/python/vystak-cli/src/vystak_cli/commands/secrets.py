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
from vystak.secrets.env_loader import load_env_file


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


def _make_kv_secret_client(vault_name: str):
    """Construct an Azure Key Vault SecretClient.

    Azure deps are lazy-imported — they're only needed when a vault is
    declared, so users without the Azure plugin installed can still use
    env-passthrough flows.
    """
    from azure.identity import DefaultAzureCredential
    from azure.keyvault.secrets import SecretClient

    return SecretClient(
        vault_url=f"https://{vault_name}.vault.azure.net/",
        credential=DefaultAzureCredential(),
    )


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


@secrets.command("push")
@click.option("--file", default="vystak.yaml")
@click.option("--env-file", default=".env")
@click.option("--force", is_flag=True, help="Overwrite existing KV values")
@click.option("--allow-missing", is_flag=True, help="Skip secrets not in .env or vault")
@click.argument("names", nargs=-1)
def push_cmd(file: str, env_file: str, force: bool, allow_missing: bool, names):
    """Push secrets from .env into the vault.

    Default behaviour is push-if-missing: only pushes when KV has no value.
    ``--force`` overwrites whatever is in KV. ``--allow-missing`` allows
    declared secrets to be silently skipped when absent from both .env
    and KV (otherwise this is a hard error).

    Never prints secret VALUES — only names and status markers.
    """
    import contextlib

    from azure.core.exceptions import ResourceNotFoundError

    declared, vault_name = _collect_declared_secrets(Path(file))
    if not vault_name:
        raise click.ClickException("No vault declared in config; push has nothing to do.")

    target = list(names) if names else declared
    env_values = load_env_file(Path(env_file), optional=True)
    client = _make_kv_secret_client(vault_name)

    for name in target:
        existing = None
        with contextlib.suppress(ResourceNotFoundError):
            existing = client.get_secret(name).value

        if existing is not None and not force:
            click.echo(f"  skip    {name}")
            continue

        if name in env_values:
            client.set_secret(name, env_values[name])
            click.echo(f"  pushed  {name}")
        elif allow_missing:
            click.echo(f"  missing {name}")
        else:
            raise click.ClickException(
                f"Secret '{name}' missing from .env and vault. "
                f"Set in .env, run 'vystak secrets set {name}=...', or pass --allow-missing."
            )


@secrets.command("set")
@click.argument("assignment", required=True)
@click.option("--file", default="vystak.yaml")
def set_cmd(assignment: str, file: str):
    """Push a single secret directly: ``vystak secrets set NAME=VALUE``.

    Intended for one-off bootstrap — does NOT read .env. The value is
    written to KV directly and never echoed back.
    """
    if "=" not in assignment:
        raise click.ClickException("Use NAME=VALUE syntax.")
    name, value = assignment.split("=", 1)
    _, vault_name = _collect_declared_secrets(Path(file))
    if not vault_name:
        raise click.ClickException("No vault declared.")
    client = _make_kv_secret_client(vault_name)
    client.set_secret(name, value)
    click.echo(f"  set     {name}")


@secrets.command("diff")
@click.option("--file", default="vystak.yaml")
@click.option("--env-file", default=".env")
def diff_cmd(file: str, env_file: str):
    """Compare .env values vs KV values for declared secrets.

    Prints only names and categories — NEVER the actual values.
    Categories:
        same           — env and vault values match
        differs        — env and vault both present, values don't match
        env-only       — only in .env
        vault-only     — only in vault
        missing        — absent from both
    """
    import contextlib

    from azure.core.exceptions import ResourceNotFoundError

    declared, vault_name = _collect_declared_secrets(Path(file))
    env_values = load_env_file(Path(env_file), optional=True)
    client = _make_kv_secret_client(vault_name) if vault_name else None

    for name in declared:
        in_env = name in env_values
        kv_value = None
        if client is not None:
            with contextlib.suppress(ResourceNotFoundError):
                kv_value = client.get_secret(name).value

        if in_env and kv_value is not None:
            match = env_values[name] == kv_value
            click.echo(f"  {name}  {'same' if match else 'differs'}")
        elif in_env and kv_value is None:
            click.echo(f"  {name}  env-only (vault missing)")
        elif not in_env and kv_value is not None:
            click.echo(f"  {name}  vault-only (env missing)")
        else:
            click.echo(f"  {name}  missing (absent in env and vault)")
