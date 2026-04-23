"""Tests for `vystak destroy` default-path state cleanup."""

from __future__ import annotations

from unittest.mock import patch

from click.testing import CliRunner
from vystak_cli.commands.destroy import (
    _cleanup_default_path_state,
)
from vystak_cli.commands.destroy import (
    destroy as destroy_cmd,
)

DEFAULT_PATH_YAML = """\
providers:
  docker: {type: docker}
  anthropic: {type: anthropic}
platforms:
  local: {type: docker, provider: docker}
models:
  sonnet: {provider: anthropic, model_name: claude-sonnet-4-20250514}
agents:
  - name: assistant
    model: sonnet
    platform: local
    secrets: [{name: ANTHROPIC_API_KEY}]
"""


def test_cleanup_default_path_state_removes_env_files_and_ssh(tmp_path, monkeypatch):
    """The helper removes per-principal env files and per-agent SSH directories."""
    monkeypatch.chdir(tmp_path)

    env_dir = tmp_path / ".vystak" / "env"
    ssh_dir = tmp_path / ".vystak" / "ssh" / "assistant"
    env_dir.mkdir(parents=True)
    ssh_dir.mkdir(parents=True)
    (env_dir / "assistant-agent.env").write_text("K=v")
    (env_dir / "assistant-workspace.env").write_text("K=v")
    (ssh_dir / "client-key").write_text("stub")

    # Object stub with just .name
    class _A:
        def __init__(self, name: str) -> None:
            self.name = name

    _cleanup_default_path_state([_A("assistant")])

    assert not (env_dir / "assistant-agent.env").exists()
    assert not (env_dir / "assistant-workspace.env").exists()
    assert not ssh_dir.exists()


def test_destroy_calls_default_path_cleanup_when_no_vault(tmp_path, monkeypatch):
    """Running `vystak destroy` on a no-vault config removes .vystak/env/* and .vystak/ssh/*."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "vystak.yaml").write_text(DEFAULT_PATH_YAML)

    env_dir = tmp_path / ".vystak" / "env"
    ssh_dir = tmp_path / ".vystak" / "ssh" / "assistant"
    env_dir.mkdir(parents=True)
    ssh_dir.mkdir(parents=True)
    (env_dir / "assistant-agent.env").write_text("K=v")
    (ssh_dir / "client-key").write_text("stub")

    # Stub provider so provider.destroy() doesn't try to touch Docker
    fake_provider = type(
        "_P",
        (),
        {
            "set_agent": lambda self, a: None,
            "set_vault": lambda self, v: None,
            "destroy": lambda self, *a, **kw: None,
            "list_resources": lambda self, name: [],
        },
    )()

    with patch(
        "vystak_cli.commands.destroy.get_provider", return_value=fake_provider
    ):
        runner = CliRunner()
        result = runner.invoke(destroy_cmd, ["--file", str(tmp_path / "vystak.yaml")])

    assert result.exit_code == 0, result.output
    assert not (env_dir / "assistant-agent.env").exists()
    assert not ssh_dir.exists()


def test_destroy_skips_default_path_cleanup_when_vault_declared(tmp_path, monkeypatch):
    """With a Vault declared, default-path state (.vystak/env/, .vystak/ssh/)
    is left alone — Vault-path state has its own lifecycle."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "vystak.yaml").write_text(
        "providers:\n"
        "  docker: {type: docker}\n"
        "  anthropic: {type: anthropic}\n"
        "platforms:\n"
        "  local: {type: docker, provider: docker}\n"
        "vault:\n"
        "  name: v\n"
        "  provider: docker\n"
        "  type: vault\n"
        "  mode: deploy\n"
        "  config: {}\n"
        "models:\n"
        "  sonnet: {provider: anthropic, model_name: claude-sonnet-4-20250514}\n"
        "agents:\n"
        "  - name: assistant\n"
        "    model: sonnet\n"
        "    platform: local\n"
        "    secrets: [{name: ANTHROPIC_API_KEY}]\n"
    )

    env_dir = tmp_path / ".vystak" / "env"
    env_dir.mkdir(parents=True)
    (env_dir / "assistant-agent.env").write_text("K=v")

    fake_provider = type(
        "_P",
        (),
        {
            "set_agent": lambda self, a: None,
            "set_vault": lambda self, v: None,
            "destroy": lambda self, *a, **kw: None,
            "list_resources": lambda self, name: [],
        },
    )()
    with patch(
        "vystak_cli.commands.destroy.get_provider", return_value=fake_provider
    ):
        runner = CliRunner()
        result = runner.invoke(destroy_cmd, ["--file", str(tmp_path / "vystak.yaml")])

    assert result.exit_code == 0, result.output
    # Vault path — default-path cleanup SHOULD NOT fire
    assert (env_dir / "assistant-agent.env").exists()
