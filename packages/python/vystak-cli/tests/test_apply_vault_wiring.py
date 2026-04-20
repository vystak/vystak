"""Tests that `vystak apply` loads `.env` and threads vault context to the provider.

The real provisioning loop is mocked at
``vystak_cli.commands.apply._run_provider_apply`` so these tests exercise only
the CLI plumbing — option parsing, definition loading, env file loading, and
the handoff to ``_run_provider_apply``. They do **not** spin up Azure clients.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner
from vystak_cli.cli import cli

FIXTURE_YAML_WITH_VAULT = """\
providers:
  azure: {type: azure, config: {location: eastus2}}
  anthropic: {type: anthropic}
platforms:
  aca: {type: container-apps, provider: azure}
vault:
  name: vystak-vault
  provider: azure
  mode: deploy
  config: {vault_name: vystak-vault}
models:
  sonnet: {provider: anthropic, model_name: claude-sonnet-4-20250514}
agents:
  - name: assistant
    model: sonnet
    secrets: [{name: ANTHROPIC_API_KEY}]
    platform: aca
"""


FIXTURE_YAML_NO_VAULT = """\
providers:
  anthropic: {type: anthropic}
models:
  sonnet: {provider: anthropic, model_name: claude-sonnet-4-20250514}
agents:
  - name: assistant
    model: sonnet
"""


def _write_vault_yaml(dir_: Path) -> Path:
    p = dir_ / "vystak.yaml"
    p.write_text(FIXTURE_YAML_WITH_VAULT)
    return p


def _write_no_vault_yaml(dir_: Path) -> Path:
    p = dir_ / "vystak.yaml"
    p.write_text(FIXTURE_YAML_NO_VAULT)
    return p


def test_apply_loads_env_and_passes_to_provider(tmp_path):
    """When `.env` is present, `vystak apply` parses it and threads the dict
    plus the declared Vault through to `_run_provider_apply`."""
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        td_path = Path(td)
        config = _write_vault_yaml(td_path)
        env = td_path / ".env"
        env.write_text("ANTHROPIC_API_KEY=test-val\n")

        with patch("vystak_cli.commands.apply._run_provider_apply") as mock_apply:
            result = runner.invoke(
                cli,
                ["apply", "--file", str(config), "--env-file", str(env)],
                catch_exceptions=False,
            )
    assert result.exit_code == 0, result.output
    mock_apply.assert_called_once()
    kwargs = mock_apply.call_args.kwargs
    assert kwargs["env_values"]["ANTHROPIC_API_KEY"] == "test-val"
    assert kwargs["vault"] is not None
    assert kwargs["vault"].name == "vystak-vault"
    assert kwargs["force"] is False
    assert kwargs["allow_missing"] is False
    assert len(kwargs["agents"]) == 1
    assert kwargs["agents"][0].name == "assistant"


def test_apply_missing_env_file_is_not_fatal(tmp_path):
    """`.env` is optional — when absent, `env_values` is an empty dict, not an error."""
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        td_path = Path(td)
        config = _write_vault_yaml(td_path)
        # Do NOT create .env

        with patch("vystak_cli.commands.apply._run_provider_apply") as mock_apply:
            result = runner.invoke(
                cli,
                ["apply", "--file", str(config)],
                catch_exceptions=False,
            )
    assert result.exit_code == 0, result.output
    mock_apply.assert_called_once()
    kwargs = mock_apply.call_args.kwargs
    assert kwargs["env_values"] == {}
    assert kwargs["vault"] is not None


def test_apply_force_flag_is_threaded(tmp_path):
    """`--force` is passed through to `_run_provider_apply` so the Azure
    provider can flip SecretSyncNode into overwrite mode."""
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        td_path = Path(td)
        config = _write_vault_yaml(td_path)
        env = td_path / ".env"
        env.write_text("ANTHROPIC_API_KEY=v\n")

        with patch("vystak_cli.commands.apply._run_provider_apply") as mock_apply:
            result = runner.invoke(
                cli,
                ["apply", "--file", str(config), "--env-file", str(env), "--force"],
                catch_exceptions=False,
            )
    assert result.exit_code == 0, result.output
    kwargs = mock_apply.call_args.kwargs
    assert kwargs["force"] is True


def test_apply_allow_missing_flag_is_threaded(tmp_path):
    """`--allow-missing` is passed through so SecretSyncNode tolerates
    secrets that are absent in both `.env` and the vault."""
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        td_path = Path(td)
        config = _write_vault_yaml(td_path)
        env = td_path / ".env"
        env.write_text("\n")  # empty

        with patch("vystak_cli.commands.apply._run_provider_apply") as mock_apply:
            result = runner.invoke(
                cli,
                [
                    "apply",
                    "--file",
                    str(config),
                    "--env-file",
                    str(env),
                    "--allow-missing",
                ],
                catch_exceptions=False,
            )
    assert result.exit_code == 0, result.output
    kwargs = mock_apply.call_args.kwargs
    assert kwargs["allow_missing"] is True


def test_apply_without_vault_passes_none(tmp_path):
    """Configurations that don't declare a vault still load and hand vault=None
    to the provisioner — the provider treats that as env-passthrough mode."""
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        td_path = Path(td)
        config = _write_no_vault_yaml(td_path)

        with patch("vystak_cli.commands.apply._run_provider_apply") as mock_apply:
            result = runner.invoke(
                cli,
                ["apply", "--file", str(config)],
                catch_exceptions=False,
            )
    assert result.exit_code == 0, result.output
    kwargs = mock_apply.call_args.kwargs
    assert kwargs["vault"] is None
