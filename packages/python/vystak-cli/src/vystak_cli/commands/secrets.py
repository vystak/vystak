"""vystak secrets — list/push/set/diff subcommands.

All subcommands operate on secrets declared in ``vystak.yaml`` and materialize
through the declared ``Vault`` backend. Two backends are supported:

- ``type=key-vault`` (``VaultType.KEY_VAULT``) — Azure Key Vault, used by the
  AzureProvider. Secret values live on ``https://<vault>.vault.azure.net/``.
- ``type=vault`` (``VaultType.VAULT``) — HashiCorp Vault running as a Docker
  container (``vystak-vault``), used by the DockerProvider. Values live in
  KV v2 under ``secret/data/<name>``.

The CLI picks the backend by inspecting ``vault.type`` on the loaded config.

SECURITY CONTRACT: these commands print secret **names** and presence/diff
**categories** only. Actual secret values MUST NEVER appear in output at any
verbosity level.
"""

from pathlib import Path

import click
import yaml
from vystak.schema.multi_loader import load_multi_yaml
from vystak.schema.vault import Vault
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


def _collect_declared_secrets(config_path: Path) -> tuple[list[str], Vault | None]:
    """Return (declared secret names, Vault | None) for the given config.

    Declared names = union of agent.secrets, agent.workspace.secrets,
    channel.secrets. Order-preserving de-dupe. The second element is the
    :class:`Vault` object itself (or ``None``) so callers can dispatch on
    ``vault.type`` to pick the right backend.
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

    return unique, vault


def _vault_display_name(vault: Vault) -> str:
    """Resolve the identifier used in output / Azure KV URL."""
    cfg_name = vault.config.get("vault_name") if vault.config else None
    return cfg_name or vault.name


# --- Azure Key Vault backend -------------------------------------------


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


# --- HashiCorp Vault backend -------------------------------------------


def _make_vault_client(vault: Vault):
    """Build a :class:`VaultClient` for the declared Vault resource.

    In ``deploy`` mode the root token lives in
    ``.vystak/vault/init.json`` (written by ``HashiVaultInitNode`` during
    ``vystak apply``). In ``external`` mode the caller provides a URL and
    an environment variable name holding the token (``config.token_env``).
    """
    import json
    import os

    from vystak_provider_docker.vault_client import VaultClient

    cfg = vault.config or {}
    port = cfg.get("port", 8200)

    if vault.mode.value == "external":
        url = cfg.get("url")
        if not url:
            raise click.ClickException(
                "external-mode Vault requires config.url (e.g. http://host:8200)."
            )
        token_env = cfg.get("token_env")
        token = os.environ.get(token_env) if token_env else None
    else:
        url = f"http://localhost:{cfg.get('host_port', port)}"
        init_path = Path(".vystak/vault/init.json")
        if not init_path.exists():
            raise click.ClickException(
                "Vault not initialized yet (.vystak/vault/init.json missing). "
                "Run 'vystak apply' first."
            )
        token = json.loads(init_path.read_text()).get("root_token")

    return VaultClient(url, token=token)


def _vault_list_names(vault: Vault) -> list[str]:
    """Fetch secret NAMES from HashiCorp Vault KV v2. Never returns values."""
    client = _make_vault_client(vault)
    return client.kv_list()


# --- subcommands ----------------------------------------------------------


@secrets.command("list")
@click.option("--file", default="vystak.yaml", help="Path to vystak.yaml")
def list_cmd(file: str):
    """List declared secrets and whether each is present in the vault."""
    from vystak.schema.common import VaultType

    declared, vault = _collect_declared_secrets(Path(file))

    if vault is None:
        click.echo("Declared secrets (no vault, env-passthrough):")
        for name in declared:
            click.echo(f"  {name}  [env-only]")
        return

    if vault.type is VaultType.VAULT:
        existing = set(_vault_list_names(vault))
    else:
        existing = set(_kv_list_names(_vault_display_name(vault)))

    click.echo(
        f"Declared secrets (vault: {vault.name}, type: {vault.type.value}):"
    )
    for name in declared:
        status = "present in vault" if name in existing else "absent in vault"
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
    from vystak.schema.common import VaultType

    declared, vault = _collect_declared_secrets(Path(file))
    if vault is None:
        raise click.ClickException("No vault declared in config; push has nothing to do.")

    env_values = load_env_file(Path(env_file), optional=True)
    target = list(names) if names else declared

    if vault.type is VaultType.VAULT:
        client = _make_vault_client(vault)
        for name in target:
            existing = client.kv_get(name)
            if existing is not None and not force:
                click.echo(f"  skip    {name}")
                continue
            if name in env_values:
                client.kv_put(name, env_values[name])
                click.echo(f"  pushed  {name}")
            elif allow_missing:
                click.echo(f"  missing {name}")
            else:
                raise click.ClickException(
                    f"Secret '{name}' missing from .env and vault. "
                    f"Set in .env, run 'vystak secrets set {name}=...', "
                    f"or pass --allow-missing."
                )
        return

    # Azure Key Vault path (v1 behavior)
    import contextlib

    from azure.core.exceptions import ResourceNotFoundError

    client = _make_kv_secret_client(_vault_display_name(vault))

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
    written to the declared vault directly and never echoed back.
    """
    from vystak.schema.common import VaultType

    if "=" not in assignment:
        raise click.ClickException("Use NAME=VALUE syntax.")
    name, value = assignment.split("=", 1)
    _, vault = _collect_declared_secrets(Path(file))
    if vault is None:
        raise click.ClickException("No vault declared.")

    if vault.type is VaultType.VAULT:
        client = _make_vault_client(vault)
        client.kv_put(name, value)
    else:
        client = _make_kv_secret_client(_vault_display_name(vault))
        client.set_secret(name, value)
    click.echo(f"  set     {name}")


@secrets.command("diff")
@click.option("--file", default="vystak.yaml")
@click.option("--env-file", default=".env")
def diff_cmd(file: str, env_file: str):
    """Compare .env values vs vault values for declared secrets.

    Prints only names and categories — NEVER the actual values.
    Categories:
        same           — env and vault values match
        differs        — env and vault both present, values don't match
        env-only       — only in .env
        vault-only     — only in vault
        missing        — absent from both
    """
    from vystak.schema.common import VaultType

    declared, vault = _collect_declared_secrets(Path(file))
    env_values = load_env_file(Path(env_file), optional=True)

    if vault is None:
        for name in declared:
            in_env = name in env_values
            click.echo(
                f"  {name}  {'env-only (vault missing)' if in_env else 'missing (absent in env and vault)'}"
            )
        return

    if vault.type is VaultType.VAULT:
        vc = _make_vault_client(vault)

        def _lookup(n: str) -> str | None:
            return vc.kv_get(n)

    else:
        import contextlib

        from azure.core.exceptions import ResourceNotFoundError

        kv_client = _make_kv_secret_client(_vault_display_name(vault))

        def _lookup(n: str) -> str | None:
            with contextlib.suppress(ResourceNotFoundError):
                return kv_client.get_secret(n).value
            return None

    for name in declared:
        in_env = name in env_values
        stored = _lookup(name)

        if in_env and stored is not None:
            match = env_values[name] == stored
            click.echo(f"  {name}  {'same' if match else 'differs'}")
        elif in_env and stored is None:
            click.echo(f"  {name}  env-only (vault missing)")
        elif not in_env and stored is not None:
            click.echo(f"  {name}  vault-only (env missing)")
        else:
            click.echo(f"  {name}  missing (absent in env and vault)")
