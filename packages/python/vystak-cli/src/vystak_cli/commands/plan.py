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

    if getattr(defs, "vault", None) is None:
        _emit_default_path_plan(defs)
    else:
        _emit_vault_plan(defs)
    _print_workspace_section(defs.agents)


def _print_workspace_section(agents) -> None:
    """Emit a ``Workspaces:`` section for every agent that declares one.

    One line per workspace-bearing agent names the image (or Dockerfile)
    and persistence mode; optional follow-on indented lines surface the
    provision-step count and whether human SSH is enabled. Offline —
    does not contact any provider.
    """
    ws_agents = [a for a in agents if a.workspace is not None]
    if not ws_agents:
        return

    click.echo("Workspaces:")
    for a in ws_agents:
        ws = a.workspace
        img = (
            f"from Dockerfile {ws.dockerfile}"
            if ws.dockerfile
            else ws.image or "<no image>"
        )
        click.echo(
            f"  {a.name}-workspace  image={img}  persistence={ws.persistence}"
        )
        if ws.provision:
            click.echo(f"    provision steps: {len(ws.provision)}")
        if ws.ssh:
            click.echo(
                f"    human SSH enabled (authorized_keys: "
                f"{len(ws.ssh_authorized_keys)})"
            )
    click.echo()


def _emit_default_path_plan(defs) -> None:
    """Emit default-path plan output — EnvFiles section + orphan detection.

    When no Vault is declared, secrets are materialized into per-principal
    env files at apply time (``.vystak/env/<principal>.env``). This helper
    previews what each principal will receive + surfaces any leftover
    Vault resources from a prior vault-backed deploy that need explicit
    cleanup.
    """
    from vystak.secrets.env_loader import load_env_file

    env_values = load_env_file(Path(".env"), optional=True)

    # --- EnvFiles section. Only principals the provider actually materializes
    # on the default path: agent + workspace. Channels are not currently wired
    # for per-channel env-file generation (follow-up); advertising rows for
    # them here would misrepresent what `vystak apply` will produce.
    principals: list[tuple[str, list[str]]] = []
    for agent in defs.agents:
        if agent.secrets:
            principals.append(
                (f"{agent.name}-agent", [s.name for s in agent.secrets])
            )
        if agent.workspace is not None and agent.workspace.secrets:
            principals.append(
                (f"{agent.name}-workspace", [s.name for s in agent.workspace.secrets])
            )

    if principals:
        click.echo("EnvFiles:")
        for p_name, secret_names in principals:
            resolved = sum(1 for n in secret_names if n in env_values)
            missing = [n for n in secret_names if n not in env_values]
            status = f"{resolved}/{len(secret_names)} resolved from .env"
            if missing:
                status += f", missing: {', '.join(missing)}"
            click.echo(f"  {p_name}  {status}")
        click.echo()

    # --- Orphan detection: leftover Vault resources from a prior deploy.
    # Scoped to the current config's agents so unrelated worktrees /
    # parallel deploys on the same Docker host don't show up here and
    # tempt the user to run `destroy --delete-vault` on someone else's
    # Vault.
    agent_names = [a.name for a in defs.agents]
    orphans = _detect_orphan_vault_resources(agent_names)
    if orphans:
        click.echo("Orphan resources detected:")
        for o in orphans:
            click.echo(f"  {o}")
        click.echo()
        click.echo("These are from a previous Vault-backed deploy. To clean up:")
        click.echo("  vystak destroy --delete-vault")
        click.echo("  vystak apply")
        click.echo()
        click.echo("To keep them during migration, proceed with 'vystak apply'.")
        click.echo()


def _detect_orphan_vault_resources(agent_names: list[str] | None = None) -> list[str]:
    """Best-effort detection of leftover Vault resources on the default path.

    Scoping rules:
    - ``.vystak/vault/init.json`` is cwd-relative so it unambiguously
      belongs to this project; always flagged when present.
    - Per-agent Vault Agent sidecars and per-principal volumes are
      filtered to names containing an ``agent_names`` entry. Without this
      filter the global Docker daemon query would show resources from
      unrelated worktrees or parallel deploys on the same host, and the
      remediation (`vystak destroy --delete-vault`) would destroy their
      Vault state.
    - The shared ``vystak-vault`` server and its ``vystak-vault-data``
      volume are intentionally NOT flagged here — they may be actively
      used by another worktree's config. They are cleaned up explicitly
      via ``vystak destroy --delete-vault`` when the user opts in.

    Returns a list of human-readable resource descriptions. Swallows
    docker-daemon errors (returns empty for the docker branch) because
    plan is supposed to be offline-safe.
    """
    agent_names = list(agent_names or [])
    orphans: list[str] = []
    init_path = Path(".vystak") / "vault" / "init.json"
    if init_path.exists():
        orphans.append(f"{init_path} (Hashi Vault unseal keys + root token)")

    if not agent_names:
        return orphans

    # Enumerate the exact resource names the provider builds for this
    # config's agents. Matching on the exact string avoids prefix-collision
    # footguns where agent 'api' would otherwise match 'api-gateway'.
    expected_containers: set[str] = set()
    expected_volumes: set[str] = set()
    for a in agent_names:
        for principal_suffix in ("-agent", "-workspace"):
            principal = f"vystak-{a}{principal_suffix}"
            expected_containers.add(f"{principal}-vault-agent")
            expected_volumes.add(f"{principal}-approle")
            expected_volumes.add(f"{principal}-secrets")

    try:
        import docker as _docker

        dc = _docker.from_env()
        for container in dc.containers.list(all=True):
            if container.name in expected_containers:
                orphans.append(f"container: {container.name}")
        for volume in dc.volumes.list():
            if volume.name in expected_volumes:
                orphans.append(f"volume: {volume.name}")
    except Exception:
        # Docker unreachable — skip. Plan should remain offline-safe.
        pass

    return orphans


def _emit_vault_plan(defs) -> None:
    """Emit Vault-related plan sections when a vault is declared.

    Dispatches by ``vault.type`` — Azure Key Vault (v1) emits Identities /
    Grants, while HashiCorp Vault emits AppRoles / Policies. The shared
    Vault header + Secrets name-list sit in each helper so callers don't
    need to know the branch structure.

    Kept offline: the real push/skip decision happens at `apply` time inside
    the relevant SecretSync node — plan only surfaces *what will be
    attempted*. No secret VALUES are ever printed here at any verbosity.
    """
    vault = getattr(defs, "vault", None)
    if vault is None:
        return

    from vystak.schema.common import VaultType

    if vault.type is VaultType.VAULT:
        _print_vault_sections_hashi(vault, defs.agents, defs.channels)
    else:  # KEY_VAULT
        _print_vault_sections_kv(vault, defs.agents, defs.channels)


def _print_vault_sections_kv(vault, agents, channels) -> None:
    """v1 Azure Key Vault output: Vault / Identities / Secrets / Grants."""
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
    for agent in agents:
        if agent.secrets:
            click.echo(f"  {agent.name}-agent      will create (UAMI, lifecycle: None)")
        if agent.workspace is not None and agent.workspace.secrets:
            click.echo(f"  {agent.name}-workspace  will create (UAMI, lifecycle: None)")
    click.echo()

    # --- Secrets — declared-name list only, status deferred to apply time
    click.echo("Secrets:")
    seen: set[str] = set()
    for agent in agents:
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
    for channel in channels:
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
    for agent in agents:
        for s in agent.secrets:
            click.echo(f"  {agent.name}-agent      \u2192 {s.name}  will assign")
        if agent.workspace is not None:
            for s in agent.workspace.secrets:
                click.echo(
                    f"  {agent.name}-workspace  \u2192 {s.name}  will assign"
                )
    click.echo()


def _print_vault_sections_hashi(vault, agents, channels) -> None:
    """HashiCorp Vault output: Vault / AppRoles / Secrets / Policies.

    - AppRoles stand in for KV's UAMI identities (one per principal that
      needs to read secrets).
    - Policies stand in for KV's Grants (each principal's AppRole is
      bound to an HCL policy granting read on its secret paths).
    """
    start_or_link = "start" if vault.mode.value == "deploy" else "link"
    click.echo("Vault:")
    click.echo(
        f"  {vault.name} "
        f"({vault.type.value}, {vault.mode.value}, {vault.provider.name})"
        f"  will {start_or_link}"
    )
    click.echo()

    # --- AppRoles (one per principal that needs secrets)
    click.echo("AppRoles:")
    for a in agents:
        if a.secrets:
            count = len(a.secrets)
            plural = "s" if count != 1 else ""
            click.echo(
                f"  {a.name}-agent      will create (policy: {count} secret{plural})"
            )
        if a.workspace is not None and a.workspace.secrets:
            count = len(a.workspace.secrets)
            plural = "s" if count != 1 else ""
            click.echo(
                f"  {a.name}-workspace  will create (policy: {count} secret{plural})"
            )
    click.echo()

    # --- Secrets — declared-name list only, values never printed
    click.echo("Secrets:")
    seen: set[str] = set()
    for a in agents:
        for s in a.secrets:
            if s.name in seen:
                continue
            seen.add(s.name)
            click.echo(
                f"  {s.name}    will push  "
                f"(presence depends on .env and vault state)"
            )
        if a.workspace is not None:
            for s in a.workspace.secrets:
                if s.name in seen:
                    continue
                seen.add(s.name)
                click.echo(
                    f"  {s.name}    will push  "
                    f"(presence depends on .env and vault state)"
                )
    for channel in channels:
        for s in channel.secrets:
            if s.name in seen:
                continue
            seen.add(s.name)
            click.echo(
                f"  {s.name}    will push  "
                f"(presence depends on .env and vault state)"
            )
    click.echo()

    # --- Policies — AppRole-per-principal gets read on each declared path
    click.echo("Policies:")
    for a in agents:
        for s in a.secrets:
            click.echo(f"  {a.name}-agent      \u2192 {s.name}  (read)")
        if a.workspace is not None:
            for s in a.workspace.secrets:
                click.echo(f"  {a.name}-workspace  \u2192 {s.name}  (read)")
    click.echo()
