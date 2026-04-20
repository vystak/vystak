"""Tests for the ``vystak secrets`` CLI subcommand group."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from azure.core.exceptions import ResourceNotFoundError
from click.testing import CliRunner
from vystak_cli.commands.secrets import secrets

FIXTURE_YAML = """\
providers:
  azure: {type: azure, config: {location: eastus2}}
  anthropic: {type: anthropic}
platforms:
  aca: {type: container-apps, provider: azure}
vault:
  name: v
  provider: azure
  mode: deploy
  config: {vault_name: v}
models:
  sonnet: {provider: anthropic, model_name: claude-sonnet-4-20250514}
agents:
  - name: assistant
    model: sonnet
    secrets: [{name: ANTHROPIC_API_KEY}]
    platform: aca
"""


def _write_fixture_yaml(tmp_path: Path) -> Path:
    p = tmp_path / "vystak.yaml"
    p.write_text(FIXTURE_YAML)
    return p


def _write_fixture_yaml_with_two(tmp_path: Path, names: list[str]) -> Path:
    secret_block = "\n".join(f"      - {{name: {n}}}" for n in names)
    body = (
        "providers:\n"
        "  azure: {type: azure, config: {location: eastus2}}\n"
        "  anthropic: {type: anthropic}\n"
        "platforms:\n"
        "  aca: {type: container-apps, provider: azure}\n"
        "vault:\n"
        "  name: v\n"
        "  provider: azure\n"
        "  mode: deploy\n"
        "  config: {vault_name: v}\n"
        "models:\n"
        "  sonnet: {provider: anthropic, model_name: claude-sonnet-4-20250514}\n"
        "agents:\n"
        "  - name: assistant\n"
        "    model: sonnet\n"
        "    platform: aca\n"
        "    secrets:\n"
        f"{secret_block}\n"
    )
    p = tmp_path / "vystak.yaml"
    p.write_text(body)
    return p


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


def test_secrets_list_shows_declared(tmp_path):
    config = _write_fixture_yaml(tmp_path)
    runner = CliRunner()
    with patch("vystak_cli.commands.secrets._kv_list_names", return_value=[]):
        result = runner.invoke(secrets, ["list", "--file", str(config)])
    assert result.exit_code == 0, result.output
    assert "ANTHROPIC_API_KEY" in result.output
    assert "absent in vault" in result.output


def test_secrets_list_marks_present_when_kv_has_name(tmp_path):
    config = _write_fixture_yaml(tmp_path)
    runner = CliRunner()
    with patch(
        "vystak_cli.commands.secrets._kv_list_names",
        return_value=["ANTHROPIC_API_KEY"],
    ):
        result = runner.invoke(secrets, ["list", "--file", str(config)])
    assert result.exit_code == 0, result.output
    assert "ANTHROPIC_API_KEY" in result.output
    assert "present in vault" in result.output


def test_secrets_list_never_prints_values(tmp_path):
    """The list subcommand only surfaces names. No envvar lookup — safe by
    construction — but assert defensively anyway."""
    config = _write_fixture_yaml(tmp_path)
    runner = CliRunner()
    with patch(
        "vystak_cli.commands.secrets._kv_list_names",
        return_value=["ANTHROPIC_API_KEY"],
    ):
        result = runner.invoke(secrets, ["list", "--file", str(config)])
    assert result.exit_code == 0
    # A value-looking string should not appear:
    assert "sk-" not in result.output
    assert "fake-value" not in result.output


# ---------------------------------------------------------------------------
# push
# ---------------------------------------------------------------------------


def test_secrets_push_pushes_absent_from_env(tmp_path):
    env = tmp_path / ".env"
    env.write_text("ANTHROPIC_API_KEY=fake-value\n")
    config = _write_fixture_yaml(tmp_path)

    runner = CliRunner()
    mock_client = MagicMock()
    mock_client.get_secret.side_effect = ResourceNotFoundError("not found")
    with patch(
        "vystak_cli.commands.secrets._make_kv_secret_client",
        return_value=mock_client,
    ):
        result = runner.invoke(
            secrets,
            ["push", "--file", str(config), "--env-file", str(env)],
        )

    assert result.exit_code == 0, result.output
    mock_client.set_secret.assert_called_once_with("ANTHROPIC_API_KEY", "fake-value")
    assert "pushed" in result.output
    assert "ANTHROPIC_API_KEY" in result.output


def test_secrets_push_skips_existing_without_force(tmp_path):
    env = tmp_path / ".env"
    env.write_text("ANTHROPIC_API_KEY=fake-value\n")
    config = _write_fixture_yaml(tmp_path)

    runner = CliRunner()
    mock_client = MagicMock()
    mock_client.get_secret.return_value = MagicMock(value="already-there")
    with patch(
        "vystak_cli.commands.secrets._make_kv_secret_client",
        return_value=mock_client,
    ):
        result = runner.invoke(
            secrets,
            ["push", "--file", str(config), "--env-file", str(env)],
        )

    assert result.exit_code == 0, result.output
    mock_client.set_secret.assert_not_called()
    assert "skip" in result.output


def test_secrets_push_force_overwrites(tmp_path):
    env = tmp_path / ".env"
    env.write_text("ANTHROPIC_API_KEY=new\n")
    config = _write_fixture_yaml(tmp_path)

    runner = CliRunner()
    mock_client = MagicMock()
    mock_client.get_secret.return_value = MagicMock(value="old")
    with patch(
        "vystak_cli.commands.secrets._make_kv_secret_client",
        return_value=mock_client,
    ):
        result = runner.invoke(
            secrets,
            ["push", "--force", "--file", str(config), "--env-file", str(env)],
        )

    assert result.exit_code == 0, result.output
    mock_client.set_secret.assert_called_once_with("ANTHROPIC_API_KEY", "new")


def test_secrets_push_missing_without_allow_missing_errors(tmp_path):
    env = tmp_path / ".env"
    env.write_text("")
    config = _write_fixture_yaml(tmp_path)

    runner = CliRunner()
    mock_client = MagicMock()
    mock_client.get_secret.side_effect = ResourceNotFoundError("no")
    with patch(
        "vystak_cli.commands.secrets._make_kv_secret_client",
        return_value=mock_client,
    ):
        result = runner.invoke(
            secrets,
            ["push", "--file", str(config), "--env-file", str(env)],
        )

    assert result.exit_code != 0
    mock_client.set_secret.assert_not_called()
    assert "ANTHROPIC_API_KEY" in result.output


def test_secrets_push_allow_missing_skips(tmp_path):
    env = tmp_path / ".env"
    env.write_text("")
    config = _write_fixture_yaml(tmp_path)

    runner = CliRunner()
    mock_client = MagicMock()
    mock_client.get_secret.side_effect = ResourceNotFoundError("no")
    with patch(
        "vystak_cli.commands.secrets._make_kv_secret_client",
        return_value=mock_client,
    ):
        result = runner.invoke(
            secrets,
            ["push", "--allow-missing", "--file", str(config), "--env-file", str(env)],
        )

    assert result.exit_code == 0, result.output
    mock_client.set_secret.assert_not_called()
    assert "missing" in result.output


# ---------------------------------------------------------------------------
# set
# ---------------------------------------------------------------------------


def test_secrets_set_pushes_one(tmp_path):
    config = _write_fixture_yaml(tmp_path)
    runner = CliRunner()
    mock_client = MagicMock()
    with patch(
        "vystak_cli.commands.secrets._make_kv_secret_client",
        return_value=mock_client,
    ):
        result = runner.invoke(
            secrets,
            ["set", "ANTHROPIC_API_KEY=explicit", "--file", str(config)],
        )
    assert result.exit_code == 0, result.output
    mock_client.set_secret.assert_called_once_with("ANTHROPIC_API_KEY", "explicit")
    # Assignment value must not leak into output
    assert "explicit" not in result.output


def test_secrets_set_requires_assignment(tmp_path):
    config = _write_fixture_yaml(tmp_path)
    runner = CliRunner()
    result = runner.invoke(
        secrets,
        ["set", "ANTHROPIC_API_KEY", "--file", str(config)],
    )
    assert result.exit_code != 0
    assert "NAME=VALUE" in result.output


# ---------------------------------------------------------------------------
# diff
# ---------------------------------------------------------------------------


def test_secrets_diff_shows_present_missing_different(tmp_path):
    env = tmp_path / ".env"
    env.write_text("A=a-env\nB=b-env\n")
    config = _write_fixture_yaml_with_two(tmp_path, ["A", "B", "C"])
    runner = CliRunner()
    mock_client = MagicMock()

    def _get(n):
        if n == "A":
            m = MagicMock()
            m.value = "a-env"
            return m
        if n == "B":
            m = MagicMock()
            m.value = "b-different"
            return m
        raise ResourceNotFoundError("no")

    mock_client.get_secret.side_effect = _get
    with patch(
        "vystak_cli.commands.secrets._make_kv_secret_client",
        return_value=mock_client,
    ):
        result = runner.invoke(
            secrets,
            ["diff", "--file", str(config), "--env-file", str(env)],
        )

    assert result.exit_code == 0, result.output
    out = result.output
    assert "A" in out and "same" in out.lower()
    assert "B" in out and "differs" in out.lower()
    assert "C" in out and "missing" in out.lower()
    # Values MUST NEVER print.
    assert "a-env" not in out
    assert "b-env" not in out
    assert "b-different" not in out


def test_secrets_diff_marks_vault_only(tmp_path):
    env = tmp_path / ".env"
    env.write_text("")
    config = _write_fixture_yaml(tmp_path)
    runner = CliRunner()
    mock_client = MagicMock()
    mock_client.get_secret.return_value = MagicMock(value="some-value")
    with patch(
        "vystak_cli.commands.secrets._make_kv_secret_client",
        return_value=mock_client,
    ):
        result = runner.invoke(
            secrets,
            ["diff", "--file", str(config), "--env-file", str(env)],
        )

    assert result.exit_code == 0, result.output
    assert "ANTHROPIC_API_KEY" in result.output
    assert "vault-only" in result.output
    assert "some-value" not in result.output


# ---------------------------------------------------------------------------
# HashiCorp Vault backend dispatch
# ---------------------------------------------------------------------------

VAULT_FIXTURE_YAML = """\
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
    secrets: [{name: ANTHROPIC_API_KEY}]
    platform: local
"""


def test_list_dispatches_to_vault_backend(tmp_path):
    config = tmp_path / "vystak.yaml"
    config.write_text(VAULT_FIXTURE_YAML)
    runner = CliRunner()
    with patch(
        "vystak_cli.commands.secrets._vault_list_names",
        return_value=["FOO"],
    ) as mock_list:
        result = runner.invoke(secrets, ["list", "--file", str(config)])
    assert result.exit_code == 0, result.output
    mock_list.assert_called_once()
    assert "ANTHROPIC_API_KEY" in result.output
    assert "absent in vault" in result.output


def test_push_dispatches_to_vault_backend(tmp_path):
    config = tmp_path / "vystak.yaml"
    config.write_text(VAULT_FIXTURE_YAML)
    env = tmp_path / ".env"
    env.write_text("ANTHROPIC_API_KEY=sk-value\n")
    runner = CliRunner()
    with patch("vystak_cli.commands.secrets._make_vault_client") as mock_vc:
        fake = MagicMock()
        fake.kv_get.return_value = None
        mock_vc.return_value = fake
        result = runner.invoke(
            secrets,
            ["push", "--file", str(config), "--env-file", str(env)],
        )
    assert result.exit_code == 0, result.output
    fake.kv_put.assert_called_once_with("ANTHROPIC_API_KEY", "sk-value")


def test_list_never_prints_values_vault_backend(tmp_path):
    config = tmp_path / "vystak.yaml"
    config.write_text(VAULT_FIXTURE_YAML)
    runner = CliRunner()
    with patch(
        "vystak_cli.commands.secrets._vault_list_names",
        return_value=["ANTHROPIC_API_KEY"],
    ):
        result = runner.invoke(secrets, ["list", "--file", str(config)])
    # Value must never appear
    assert "sk-" not in result.output


# ---------------------------------------------------------------------------
# rotate-approle
# ---------------------------------------------------------------------------


def test_rotate_approle_single_principal(tmp_path):
    config = tmp_path / "vystak.yaml"
    config.write_text(VAULT_FIXTURE_YAML)
    runner = CliRunner()
    with patch("vystak_cli.commands.secrets._make_vault_client") as mock_vc:
        fake = MagicMock()
        fake.upsert_approle.return_value = ("role-new", "secret-new")
        mock_vc.return_value = fake
        with patch("vystak_cli.commands.secrets._write_approle_volume"):
            with patch("vystak_cli.commands.secrets._restart_sidecar"):
                result = runner.invoke(
                    secrets,
                    [
                        "rotate-approle",
                        "assistant-agent",
                        "--file",
                        str(config),
                    ],
                )
    assert result.exit_code == 0, result.output
    fake.upsert_approle.assert_called_once()
    assert "rotated" in result.output
    assert "assistant-agent" in result.output


def test_rotate_approle_kv_type_not_applicable(tmp_path):
    config = tmp_path / "vystak.yaml"
    config.write_text(
        """\
providers:
  azure: {type: azure, config: {location: eastus2, resource_group: rg}}
  anthropic: {type: anthropic}
platforms:
  aca: {type: container-apps, provider: azure}
vault:
  name: v
  provider: azure
  type: key-vault
  mode: deploy
  config: {vault_name: v}
models:
  sonnet: {provider: anthropic, model_name: claude-sonnet-4-20250514}
agents:
  - name: assistant
    model: sonnet
    secrets: [{name: ANTHROPIC_API_KEY}]
    platform: aca
"""
    )
    runner = CliRunner()
    result = runner.invoke(
        secrets,
        ["rotate-approle", "assistant-agent", "--file", str(config)],
    )
    assert result.exit_code != 0
    # either word shows this isn't for KV-backed setups
    out = result.output.lower()
    assert "not applicable" in out or "vault" in out


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
