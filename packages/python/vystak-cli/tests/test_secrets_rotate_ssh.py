"""Tests for vystak secrets rotate-ssh <agent>."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from click.testing import CliRunner
from vystak_cli.commands.secrets import secrets

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


def test_rotate_ssh_regenerates_and_pushes(tmp_path):
    config = tmp_path / "vystak.yaml"
    config.write_text(YAML)
    runner = CliRunner()

    # The vault client the CLI builds — mock_vault.kv_get returns None so
    # WorkspaceSshKeygenNode.provision runs the keygen path and emits four
    # kv_put calls.
    mock_vault = MagicMock()
    mock_vault.kv_get.return_value = None
    mock_docker = MagicMock()

    # Stub out the actual file IO inside WorkspaceSshKeygenNode.provision.
    # The node writes files via a throwaway alpine container, then reads
    # them back with pathlib. We don't want a real Docker round-trip or
    # real files, so we patch tempfile + pathlib.Path.read_text.
    from contextlib import contextmanager

    @contextmanager
    def _fake_tmpdir():
        yield "/tmp/fake-keygen"

    fake_client_priv = MagicMock()
    fake_client_priv.read_text.return_value = "CLIENT_PRIV\n"
    fake_client_pub = MagicMock()
    fake_client_pub.read_text.return_value = "CLIENT_PUB\n"
    fake_host_priv = MagicMock()
    fake_host_priv.read_text.return_value = "HOST_PRIV\n"
    fake_host_pub = MagicMock()
    fake_host_pub.read_text.return_value = "HOST_PUB\n"

    fake_outdir = MagicMock()
    fake_outdir.__truediv__.side_effect = {
        "client-key": fake_client_priv,
        "client-key.pub": fake_client_pub,
        "host-key": fake_host_priv,
        "host-key.pub": fake_host_pub,
    }.get

    with patch(
        "vystak_cli.commands.secrets._make_vault_client", return_value=mock_vault
    ), patch(
        "vystak_cli.commands.secrets._get_docker_client", return_value=mock_docker
    ), patch(
        "vystak_provider_docker.nodes.workspace_ssh_keygen.tempfile.TemporaryDirectory",
        _fake_tmpdir,
    ), patch(
        "vystak_provider_docker.nodes.workspace_ssh_keygen.pathlib.Path",
        return_value=fake_outdir,
    ):
        result = runner.invoke(
            secrets, ["rotate-ssh", "assistant", "--file", str(config)]
        )
    assert result.exit_code == 0, result.output
    # Four kv_put calls (client-key, host-key, client-key-pub, host-key-pub)
    assert mock_vault.kv_put.call_count == 4


def test_rotate_ssh_for_nonexistent_agent_errors(tmp_path):
    config = tmp_path / "vystak.yaml"
    config.write_text(YAML)
    runner = CliRunner()
    result = runner.invoke(secrets, ["rotate-ssh", "nope", "--file", str(config)])
    assert result.exit_code != 0
    assert "nope" in result.output.lower()
