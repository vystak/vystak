"""Tests for the Vault-aware section of ``vystak plan`` output."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner
from vystak_cli.commands.plan import plan as plan_cmd

VAULT_YAML = """\
providers:
  azure: {type: azure, config: {location: eastus2}}
  anthropic: {type: anthropic}
platforms:
  aca: {type: container-apps, provider: azure}
vault:
  name: myvault
  provider: azure
  mode: deploy
  config: {vault_name: myvault}
models:
  sonnet: {provider: anthropic, model_name: claude-sonnet-4-20250514}
agents:
  - name: assistant
    model: sonnet
    platform: aca
    secrets:
      - {name: ANTHROPIC_API_KEY}
"""


NO_VAULT_YAML = """\
providers:
  azure: {type: azure, config: {location: eastus2}}
  anthropic: {type: anthropic}
platforms:
  aca: {type: container-apps, provider: azure}
models:
  sonnet: {provider: anthropic, model_name: claude-sonnet-4-20250514}
agents:
  - name: assistant
    model: sonnet
    platform: aca
"""


def _stub_provider_for_plan():
    """Return a stub the plan command will use instead of connecting to a
    real backend. The hash and deploy_plan returned are irrelevant to the
    vault sections — we just need get_provider() to succeed."""
    prov = MagicMock()
    prov.get_hash.return_value = None
    prov.plan.return_value = MagicMock(actions=["Create new deployment"])
    prov.get_channel_hash.return_value = None
    prov.plan_channel.return_value = MagicMock(actions=[])
    return prov


def test_plan_output_includes_vault_identities_secrets_grants(tmp_path):
    config = tmp_path / "vystak.yaml"
    config.write_text(VAULT_YAML)

    runner = CliRunner()
    with patch(
        "vystak_cli.commands.plan.get_provider",
        return_value=_stub_provider_for_plan(),
    ):
        result = runner.invoke(plan_cmd, ["--file", str(config)])

    assert result.exit_code == 0, result.output
    # Four new section headers
    assert "Vault:" in result.output
    assert "Identities:" in result.output
    assert "Secrets:" in result.output
    assert "Grants:" in result.output

    # Vault row names the declared vault
    assert "myvault" in result.output
    assert "will create" in result.output  # mode=deploy

    # Identity row uses {agent}-agent naming (workspace not declared here,
    # so we only assert the agent-side row).
    assert "assistant-agent" in result.output
    assert "UAMI" in result.output
    assert "lifecycle: None" in result.output

    # Secrets section lists the declared secret name
    assert "ANTHROPIC_API_KEY" in result.output
    assert "will push" in result.output

    # Grants section binds agent UAMI to secret
    assert "assistant-agent" in result.output
    assert "ANTHROPIC_API_KEY" in result.output
    assert "will assign" in result.output


def test_plan_output_omits_vault_sections_when_no_vault(tmp_path):
    config = tmp_path / "vystak.yaml"
    config.write_text(NO_VAULT_YAML)

    runner = CliRunner()
    with patch(
        "vystak_cli.commands.plan.get_provider",
        return_value=_stub_provider_for_plan(),
    ):
        result = runner.invoke(plan_cmd, ["--file", str(config)])

    assert result.exit_code == 0, result.output
    assert "Vault:" not in result.output
    assert "Identities:" not in result.output
    # "Secrets:" and "Grants:" also must be absent
    assert "Secrets:" not in result.output
    assert "Grants:" not in result.output


def test_plan_vault_output_never_leaks_secret_values(tmp_path):
    """Task 22 explicitly forbids secret values appearing in plan output."""
    config = tmp_path / "vystak.yaml"
    config.write_text(VAULT_YAML)

    runner = CliRunner()
    with patch(
        "vystak_cli.commands.plan.get_provider",
        return_value=_stub_provider_for_plan(),
    ):
        # Even if a caller had a .env with a matching value in cwd, we must
        # never look it up nor print it. (Plan is offline by design here.)
        result = runner.invoke(plan_cmd, ["--file", str(config)])

    out = result.output
    # We never emit anything that looks like a value here — plan is name-only.
    # Spot-check: the declaration's secret name is present but any "value"-ish
    # string is not.
    assert "ANTHROPIC_API_KEY" in out
    assert "sk-ant" not in out
    assert "fake-value" not in out


HASHI_VAULT_YAML = """\
providers:
  docker: {type: docker}
  anthropic: {type: anthropic}
platforms:
  local: {type: docker, provider: docker}
vault:
  name: vystak-vault
  provider: docker
  type: vault
  mode: deploy
  config: {}
models:
  sonnet: {provider: anthropic, model_name: claude-sonnet-4-20250514}
agents:
  - name: assistant
    model: sonnet
    platform: local
    secrets:
      - {name: ANTHROPIC_API_KEY}
    workspace:
      name: tools
      type: persistent
      secrets:
        - {name: STRIPE_API_KEY}
"""


def test_plan_hashi_vault_sections(tmp_path):
    """Hashi Vault configs emit AppRoles + Policies (not Identities + Grants)."""
    config = tmp_path / "vystak.yaml"
    config.write_text(HASHI_VAULT_YAML)

    runner = CliRunner()
    with patch(
        "vystak_cli.commands.plan.get_provider",
        return_value=_stub_provider_for_plan(),
    ):
        result = runner.invoke(plan_cmd, ["--file", str(config)])

    assert result.exit_code == 0, result.output
    # Hashi-specific section headers
    assert "Vault:" in result.output
    assert "AppRoles:" in result.output
    assert "Policies:" in result.output
    # KV-specific headers must NOT appear
    assert "Identities:" not in result.output
    assert "Grants:" not in result.output

    # Vault row shows type=vault, mode=deploy, provider=docker
    assert "vystak-vault" in result.output
    assert "vault, deploy, docker" in result.output
    assert "will start" in result.output  # hashi mode=deploy uses "start"

    # Both principals appear
    assert "assistant-agent" in result.output
    assert "assistant-workspace" in result.output

    # Policy rows mention the scoped secrets
    assert "ANTHROPIC_API_KEY" in result.output
    assert "STRIPE_API_KEY" in result.output
    assert "(read)" in result.output  # policy capability

    # Values never printed
    assert "sk-" not in result.output
    assert "fake-value" not in result.output


WORKSPACE_YAML = """\
providers: {docker: {type: docker}, anthropic: {type: anthropic}}
platforms: {local: {type: docker, provider: docker}}
vault: {name: v, provider: docker, type: vault, mode: deploy, config: {}}
models: {sonnet: {provider: anthropic, model_name: claude-sonnet-4-20250514}}
agents:
  - name: coder
    model: sonnet
    platform: local
    workspace:
      name: dev
      image: python:3.12-slim
      provision: ["pip install ruff"]
      persistence: volume
"""


def test_plan_workspace_section_shown_when_declared(tmp_path):
    config = tmp_path / "vystak.yaml"
    config.write_text(WORKSPACE_YAML)

    runner = CliRunner()
    with patch(
        "vystak_cli.commands.plan.get_provider",
        return_value=_stub_provider_for_plan(),
    ):
        result = runner.invoke(plan_cmd, ["--file", str(config)])

    assert result.exit_code == 0, result.output
    # Workspace section header appears
    assert "Workspaces:" in result.output
    # Image and persistence surfaced
    assert "python:3.12-slim" in result.output
    assert "persistence" in result.output.lower()
    # Provision step count is shown
    assert "provision steps: 1" in result.output


# ---------------------------------------------------------------------------
# default path (no vault)
# ---------------------------------------------------------------------------


def test_plan_default_path_emits_env_files_section(tmp_path, monkeypatch):
    """When no Vault is declared, plan shows per-principal env-file status."""
    from click.testing import CliRunner
    from vystak_cli.commands.plan import plan as plan_cmd

    (tmp_path / "vystak.yaml").write_text(
        "providers:\n"
        "  docker: {type: docker}\n"
        "  anthropic: {type: anthropic}\n"
        "platforms:\n"
        "  docker: {provider: docker, type: docker}\n"
        "models:\n"
        "  sonnet: {provider: anthropic, model_name: claude-sonnet-4-20250514}\n"
        "agents:\n"
        "  - name: assistant\n"
        "    model: sonnet\n"
        "    platform: docker\n"
        "    secrets: [{name: ANTHROPIC_API_KEY}]\n"
        "    workspace:\n"
        "      name: ws\n"
        "      image: python:3.12-slim\n"
        "      secrets: [{name: STRIPE_API_KEY}]\n"
    )
    (tmp_path / ".env").write_text(
        "ANTHROPIC_API_KEY=a\nSTRIPE_API_KEY=b\n"
    )
    monkeypatch.chdir(tmp_path)

    runner = CliRunner()
    result = runner.invoke(plan_cmd)
    assert "EnvFiles:" in result.output
    assert "assistant-agent" in result.output
    assert "assistant-workspace" in result.output
    assert "1/1 resolved" in result.output
    assert "Vault:" not in result.output
    assert "Identities:" not in result.output


def test_plan_default_path_flags_missing_env_values(tmp_path, monkeypatch):
    from click.testing import CliRunner
    from vystak_cli.commands.plan import plan as plan_cmd

    (tmp_path / "vystak.yaml").write_text(
        "providers:\n"
        "  docker: {type: docker}\n"
        "  anthropic: {type: anthropic}\n"
        "platforms:\n"
        "  docker: {provider: docker, type: docker}\n"
        "models:\n"
        "  sonnet: {provider: anthropic, model_name: claude-sonnet-4-20250514}\n"
        "agents:\n"
        "  - name: assistant\n"
        "    model: sonnet\n"
        "    platform: docker\n"
        "    secrets: [{name: PRESENT}, {name: ABSENT}]\n"
    )
    (tmp_path / ".env").write_text("PRESENT=x\n")
    monkeypatch.chdir(tmp_path)

    runner = CliRunner()
    result = runner.invoke(plan_cmd)
    assert "EnvFiles:" in result.output
    assert "1/2 resolved" in result.output
    assert "missing: ABSENT" in result.output


def test_plan_detects_orphan_init_json(tmp_path, monkeypatch):
    """When Vault init.json is on disk but config has no vault block,
    the plan warns about orphan resources and prints the cleanup command."""
    from click.testing import CliRunner
    from vystak_cli.commands.plan import plan as plan_cmd

    (tmp_path / "vystak.yaml").write_text(
        "providers:\n"
        "  docker: {type: docker}\n"
        "  anthropic: {type: anthropic}\n"
        "platforms:\n"
        "  docker: {provider: docker, type: docker}\n"
        "models:\n"
        "  sonnet: {provider: anthropic, model_name: claude-sonnet-4-20250514}\n"
        "agents:\n"
        "  - name: assistant\n"
        "    model: sonnet\n"
        "    platform: docker\n"
        "    secrets: [{name: K}]\n"
    )
    (tmp_path / ".env").write_text("K=x\n")
    (tmp_path / ".vystak" / "vault").mkdir(parents=True)
    (tmp_path / ".vystak" / "vault" / "init.json").write_text("{}")
    monkeypatch.chdir(tmp_path)

    runner = CliRunner()
    result = runner.invoke(plan_cmd)
    assert "Orphan resources detected" in result.output
    assert "init.json" in result.output
    assert "destroy --delete-vault" in result.output


def test_plan_orphan_detection_scoped_to_current_agents(monkeypatch):
    """_detect_orphan_vault_resources filters docker-ls to names that
    include an agent declared in THIS config. Unrelated vystak-vault*
    containers from other worktrees must NOT be flagged."""
    from unittest.mock import MagicMock

    from vystak_cli.commands.plan import _detect_orphan_vault_resources

    fake_dc = MagicMock()
    this_sidecar = MagicMock()
    this_sidecar.name = "vystak-assistant-agent-vault-agent"
    other_sidecar = MagicMock()
    other_sidecar.name = "vystak-otheragent-agent-vault-agent"
    fake_dc.containers.list.return_value = [this_sidecar, other_sidecar]

    this_volume = MagicMock()
    this_volume.name = "vystak-assistant-agent-secrets"
    other_volume = MagicMock()
    other_volume.name = "vystak-otheragent-agent-secrets"
    shared = MagicMock()
    shared.name = "vystak-vault-data"  # shared across worktrees; must NOT flag
    fake_dc.volumes.list.return_value = [this_volume, other_volume, shared]

    import docker as _docker

    monkeypatch.setattr(_docker, "from_env", lambda: fake_dc)

    orphans = _detect_orphan_vault_resources(agent_names=["assistant"])
    joined = "\n".join(orphans)
    assert "vystak-assistant-agent-vault-agent" in joined
    assert "vystak-assistant-agent-secrets" in joined
    # The other worktree's resources and the shared vault-data volume
    # must NOT be flagged — otherwise the remediation 'destroy
    # --delete-vault' would destroy someone else's Vault state.
    assert "otheragent" not in joined, (
        f"orphan detection leaked across worktrees: {joined}"
    )
    assert "vystak-vault-data" not in joined, (
        "shared vystak-vault-data volume flagged as orphan — another "
        "worktree may depend on it"
    )


def test_plan_env_files_omits_channel_rows(tmp_path, monkeypatch):
    """plan's EnvFiles section must not list channel principals — the
    provider's default-path graph doesn't emit per-channel env-file
    nodes, so advertising them would misrepresent what apply will do."""
    from click.testing import CliRunner
    from vystak_cli.commands.plan import plan as plan_cmd

    (tmp_path / "vystak.yaml").write_text(
        "providers:\n"
        "  docker: {type: docker}\n"
        "  anthropic: {type: anthropic}\n"
        "platforms:\n"
        "  docker: {provider: docker, type: docker}\n"
        "models:\n"
        "  sonnet: {provider: anthropic, model_name: claude-sonnet-4-20250514}\n"
        "agents:\n"
        "  - name: assistant\n"
        "    model: sonnet\n"
        "    platform: docker\n"
        "    secrets: [{name: ANTHROPIC_API_KEY}]\n"
        "channels:\n"
        "  - name: slack\n"
        "    type: slack\n"
        "    platform: docker\n"
        "    secrets: [{name: SLACK_BOT_TOKEN}]\n"
    )
    (tmp_path / ".env").write_text("ANTHROPIC_API_KEY=x\nSLACK_BOT_TOKEN=y\n")
    monkeypatch.chdir(tmp_path)

    runner = CliRunner()
    result = runner.invoke(plan_cmd)
    assert "EnvFiles:" in result.output
    assert "assistant-agent" in result.output
    assert "slack-channel" not in result.output, (
        "EnvFiles section advertised a channel row the provider does not "
        "materialize: " + result.output
    )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
