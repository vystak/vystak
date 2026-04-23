"""Tests for `vystak destroy` with HashiCorp Vault flags."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from click.testing import CliRunner
from vystak_cli.commands.destroy import destroy as destroy_cmd

HASHI_YAML = """\
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
"""


def _write_yaml(tmp_path: Path) -> Path:
    p = tmp_path / "vystak.yaml"
    p.write_text(HASHI_YAML)
    return p


def test_destroy_default_preserves_vault(tmp_path):
    """Default `vystak destroy` does not pass delete_vault/keep_sidecars=True
    to the provider — both default to False."""
    config = _write_yaml(tmp_path)
    provider = MagicMock()
    runner = CliRunner()
    with patch(
        "vystak_cli.commands.destroy.get_provider", return_value=provider
    ):
        result = runner.invoke(destroy_cmd, ["--file", str(config)])
    assert result.exit_code == 0, result.output
    # destroy was called on the agent
    assert provider.destroy.called
    kwargs = provider.destroy.call_args.kwargs
    assert kwargs.get("delete_vault") is False
    assert kwargs.get("keep_sidecars") is False


def test_destroy_delete_vault_flag(tmp_path):
    config = _write_yaml(tmp_path)
    provider = MagicMock()
    runner = CliRunner()
    with patch(
        "vystak_cli.commands.destroy.get_provider", return_value=provider
    ):
        result = runner.invoke(
            destroy_cmd, ["--file", str(config), "--delete-vault"]
        )
    assert result.exit_code == 0, result.output
    kwargs = provider.destroy.call_args.kwargs
    assert kwargs.get("delete_vault") is True


def test_destroy_keep_sidecars_flag(tmp_path):
    config = _write_yaml(tmp_path)
    provider = MagicMock()
    runner = CliRunner()
    with patch(
        "vystak_cli.commands.destroy.get_provider", return_value=provider
    ):
        result = runner.invoke(
            destroy_cmd, ["--file", str(config), "--keep-sidecars"]
        )
    assert result.exit_code == 0, result.output
    kwargs = provider.destroy.call_args.kwargs
    assert kwargs.get("keep_sidecars") is True
