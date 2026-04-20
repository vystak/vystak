"""Tests for the ``vystak secrets`` CLI subcommand group.

Uses direct ``from vystak_cli.commands.secrets import secrets`` invocation
against the ``secrets`` group directly (via CliRunner), which avoids forcing
construction of the full top-level ``cli`` group and the transitive imports
in ``vystak_cli.commands.apply`` that require ``vystak_transport_http``.

A minimal ``sys.modules`` stub for the optional transport packages is
installed at import time so ``vystak_cli.commands.__init__`` does not blow up
when pytest discovers this file. The stub only fills the handful of symbols
that ``vystak_provider_docker.transport_wiring`` reads at import time.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

# --- workaround: stub optional transport plugins so the commands package
#     __init__ (which transitively imports vystak_provider_docker.transport_wiring)
#     can be imported in this test process. This is purely a pre-existing-issue
#     workaround — unrelated to the secrets subcommand itself.
if "vystak_transport_http" not in sys.modules:
    _stub_http = types.ModuleType("vystak_transport_http")

    class _HttpTransportPluginStub:
        pass

    _stub_http.HttpTransportPlugin = _HttpTransportPluginStub  # type: ignore[attr-defined]
    sys.modules["vystak_transport_http"] = _stub_http

if "vystak_transport_nats" not in sys.modules:
    _stub_nats = types.ModuleType("vystak_transport_nats")

    class _NatsTransportPluginStub:
        pass

    _stub_nats.NatsTransportPlugin = _NatsTransportPluginStub  # type: ignore[attr-defined]
    sys.modules["vystak_transport_nats"] = _stub_nats


import pytest  # noqa: E402
from azure.core.exceptions import ResourceNotFoundError  # noqa: E402
from click.testing import CliRunner  # noqa: E402
from vystak_cli.commands.secrets import secrets  # noqa: E402

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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
