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


def _collect_principals_from_config(config_path: Path) -> dict[str, list[str]]:
    """Return ``{principal_name → [secret_name, ...]}`` for the config.

    Principals are one per (agent, side) with ``-agent`` / ``-workspace``
    suffix. Used by ``rotate-approle`` to know which AppRole names and
    which volumes to write credentials into.
    """
    agents, _channels, _vault = _load_config(config_path)
    result: dict[str, list[str]] = {}
    for a in agents:
        if a.secrets:
            result[f"{a.name}-agent"] = [s.name for s in a.secrets]
        if a.workspace is not None and a.workspace.secrets:
            result[f"{a.name}-workspace"] = [s.name for s in a.workspace.secrets]
    return result


def _write_approle_volume(principal_name: str, role_id: str, secret_id: str) -> None:
    """Overwrite the role_id + secret_id files in the principal's approle volume.

    Mirrors ``AppRoleCredentialsNode`` — uses a throwaway alpine container
    because Docker named volumes have no host path we can write to
    directly.
    """
    import shlex

    import docker as _docker

    dc = _docker.from_env()
    volume_name = f"vystak-{principal_name}-approle"
    script = (
        f"printf %s {shlex.quote(role_id)} > /target/role_id && "
        f"chmod 400 /target/role_id && "
        f"printf %s {shlex.quote(secret_id)} > /target/secret_id && "
        f"chmod 400 /target/secret_id"
    )
    dc.containers.run(
        image="alpine:3.19",
        command=["sh", "-c", script],
        volumes={volume_name: {"bind": "/target", "mode": "rw"}},
        remove=True,
    )


def _restart_sidecar(principal_name: str) -> None:
    """Restart the Vault Agent sidecar so it picks up the rotated creds."""
    import docker as _docker

    dc = _docker.from_env()
    name = f"vystak-{principal_name}-vault-agent"
    try:
        c = dc.containers.get(name)
        c.restart()
    except Exception:
        pass


def _get_docker_client():
    """Return a docker-py client. Isolated as a seam so
    ``rotate-ssh`` tests can patch it without touching a real daemon."""
    import docker as _docker

    return _docker.from_env()


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
    env_values = load_env_file(Path(env_file), optional=True)
    target = list(names) if names else declared

    if vault is None:
        # Default path: secrets are materialized into per-principal env
        # files at `vystak apply` time. There's no out-of-band push to do;
        # surface the resolution status as a preview.
        click.echo(
            "Default path (no vault): env-file generation happens at "
            "'vystak apply'. Previewing resolution from .env:"
        )
        for name in target:
            if name in env_values:
                click.echo(f"  ready   {name}")
            elif allow_missing:
                click.echo(f"  missing {name}")
            else:
                click.echo(f"  MISSING {name}  (absent from .env)")
        return

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
        raise click.ClickException(
            "Default path (no vault): 'secrets set' is not supported. "
            "Edit .env directly (e.g. `echo "
            f"'{name}=<value>' >> .env`), then run 'vystak apply' to "
            "materialize."
        )

    if vault.type is VaultType.VAULT:
        client = _make_vault_client(vault)
        client.kv_put(name, value)
    else:
        client = _make_kv_secret_client(_vault_display_name(vault))
        client.set_secret(name, value)
    click.echo(f"  set     {name}")


@secrets.command("rotate-approle")
@click.argument("principal", required=False)
@click.option(
    "--rotate-role-id",
    is_flag=True,
    help="Also rotate role_id (default: only secret_id).",
)
@click.option("--all", "rotate_all", is_flag=True, help="Rotate every principal.")
@click.option("--file", default="vystak.yaml")
def rotate_approle_cmd(principal, rotate_role_id, rotate_all, file):
    """Rotate AppRole credentials for a principal (Hashi-only).

    Generates a fresh ``secret_id`` (and optionally ``role_id``), writes
    them into the principal's AppRole volume, then restarts the Vault
    Agent sidecar so it authenticates with the new creds on the next
    template render cycle.
    """
    from vystak.schema.common import VaultType

    _declared, vault = _collect_declared_secrets(Path(file))
    if vault is None or vault.type is not VaultType.VAULT:
        raise click.ClickException(
            "rotate-approle is not applicable — only HashiCorp Vault "
            "deployments (Vault(type='vault')) have AppRoles to rotate."
        )

    principals = _collect_principals_from_config(Path(file))

    targets: list[str] = []
    if rotate_all:
        targets = list(principals.keys())
    elif principal:
        if principal not in principals:
            raise click.ClickException(
                f"Unknown principal '{principal}'. "
                f"Known: {', '.join(principals.keys()) or '(none)'}"
            )
        targets = [principal]
    else:
        raise click.ClickException("Specify a principal name or --all.")

    client = _make_vault_client(vault)
    for name in targets:
        role_id, secret_id = client.upsert_approle(
            role_name=name,
            policies=[f"{name}-policy"],
            token_ttl="1h",
            token_max_ttl="24h",
        )
        _write_approle_volume(name, role_id, secret_id)
        _restart_sidecar(name)
        click.echo(f"  rotated  {name}")


@secrets.command("rotate-ssh")
@click.argument("agent_name", required=True)
@click.option("--file", default="vystak.yaml")
def rotate_ssh_cmd(agent_name: str, file: str):
    """Regenerate the SSH keypairs for a workspace-backed agent.

    Deletes the four ``_vystak/workspace-ssh/<agent>/*`` entries from
    Vault, then runs ``WorkspaceSshKeygenNode.provision`` which generates
    fresh ed25519 keypairs inside a throwaway alpine container and
    pushes them back into Vault. Agent and workspace containers are left
    running — the next apply will pick up the new keys.

    Never prints key material.
    """
    agents, _channels, vault = _load_config(Path(file))
    matching = [a for a in agents if a.name == agent_name]
    if not matching:
        raise click.ClickException(
            f"Agent '{agent_name}' not found. Known: "
            f"{', '.join(a.name for a in agents) or '(none)'}"
        )
    agent = matching[0]
    if agent.workspace is None:
        raise click.ClickException(
            f"Agent '{agent_name}' has no workspace; nothing to rotate."
        )

    docker_client = _get_docker_client()

    from vystak_provider_docker.nodes.workspace_ssh_keygen import (
        WorkspaceSshKeygenNode,
    )

    if vault is None:
        # Default path: invalidate .vystak/ssh/<agent>/ so the node
        # regenerates into host files on the next provision() call.
        import shutil

        host_dir = Path(".vystak") / "ssh" / agent_name
        if host_dir.exists():
            shutil.rmtree(host_dir)

        node = WorkspaceSshKeygenNode(
            vault_client=None,
            docker_client=docker_client,
            agent_name=agent_name,
        )
        node.provision(context={})
        click.echo(f"  rotated  {agent_name}  (host path, no vault)")
        return

    # Vault path: invalidate the four KV entries, regenerate + push.
    vault_client = _make_vault_client(vault)
    import contextlib

    for key in ("client-key", "host-key", "client-key-pub", "host-key-pub"):
        with contextlib.suppress(Exception):
            vault_client.kv_delete(
                f"_vystak/workspace-ssh/{agent_name}/{key}"
            )

    node = WorkspaceSshKeygenNode(
        vault_client=vault_client,
        docker_client=docker_client,
        agent_name=agent_name,
    )
    node.provision(context={})

    click.echo(f"  rotated  {agent_name}")


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
        # Default path: compare declared ∩ .env ∩ .vystak/env/*.env.
        # Never reference "vault" in status strings — there is none.
        materialized: set[str] = set()
        env_file_dir = Path(".vystak") / "env"
        if env_file_dir.exists():
            for f in env_file_dir.glob("*.env"):
                for line in f.read_text().splitlines():
                    if "=" in line and not line.lstrip().startswith("#"):
                        materialized.add(line.split("=", 1)[0].strip())
        for name in declared:
            in_env = name in env_values
            in_materialized = name in materialized
            if in_env and in_materialized:
                status = "ready (in .env and .vystak/env)"
            elif in_env and not in_materialized:
                status = "pending (in .env, not yet applied)"
            elif not in_env and in_materialized:
                status = "stale (in .vystak/env but absent from .env)"
            else:
                status = "missing (absent from both .env and .vystak/env)"
            click.echo(f"  {name}  {status}")
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
