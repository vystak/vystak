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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
