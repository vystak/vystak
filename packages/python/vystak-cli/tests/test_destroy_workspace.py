"""Tests for --delete-workspace-data and --keep-workspace flags."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from click.testing import CliRunner
from vystak_cli.commands.destroy import destroy as destroy_cmd

YAML = """\
providers: {docker: {type: docker}, anthropic: {type: anthropic}}
platforms: {local: {type: docker, provider: docker}}
vault: {name: v, provider: docker, type: vault, mode: deploy, config: {}}
models: {sonnet: {provider: anthropic, model_name: claude-sonnet-4-20250514}}
agents:
  - name: assistant
    model: sonnet
    platform: local
    workspace: {name: dev, image: python:3.12-slim}
"""


def test_destroy_delete_workspace_data(tmp_path):
    config = tmp_path / "vystak.yaml"
    config.write_text(YAML)
    provider = MagicMock()
    runner = CliRunner()
    with patch("vystak_cli.commands.destroy.get_provider", return_value=provider):
        result = runner.invoke(
            destroy_cmd, ["--file", str(config), "--delete-workspace-data"]
        )
    assert result.exit_code == 0, result.output
    assert provider.destroy.call_args.kwargs.get("delete_workspace_data") is True


def test_destroy_keep_workspace(tmp_path):
    config = tmp_path / "vystak.yaml"
    config.write_text(YAML)
    provider = MagicMock()
    runner = CliRunner()
    with patch("vystak_cli.commands.destroy.get_provider", return_value=provider):
        result = runner.invoke(
            destroy_cmd, ["--file", str(config), "--keep-workspace"]
        )
    assert result.exit_code == 0, result.output
    assert provider.destroy.call_args.kwargs.get("keep_workspace") is True
