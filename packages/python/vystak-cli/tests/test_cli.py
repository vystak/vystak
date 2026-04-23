from unittest.mock import MagicMock, patch

import yaml
from click.testing import CliRunner
from vystak_cli.cli import cli

SAMPLE_AGENT_YAML = {
    "name": "test-bot",
    "model": {
        "name": "claude",
        "provider": {"name": "anthropic", "type": "anthropic"},
        "model_name": "claude-sonnet-4-20250514",
    },
}


@patch("vystak_cli.commands.plan.get_provider")
def test_plan_new(mock_get_provider, tmp_path):
    from vystak.providers.base import DeployPlan

    mock_provider = MagicMock()
    mock_provider.get_hash.return_value = None
    mock_provider.plan.return_value = DeployPlan(
        agent_name="test-bot",
        actions=["Create new deployment"],
        current_hash=None,
        target_hash="abc123",
        changes={},
    )
    mock_get_provider.return_value = mock_provider

    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        from pathlib import Path

        Path(td).joinpath("vystak.yaml").write_text(yaml.dump(SAMPLE_AGENT_YAML))
        result = runner.invoke(cli, ["plan"])

    assert result.exit_code == 0, result.output
    assert "test-bot" in result.output
    assert "Create new deployment" in result.output


@patch("vystak_cli.commands.plan.get_provider")
def test_plan_up_to_date(mock_get_provider, tmp_path):
    from vystak.providers.base import DeployPlan

    mock_provider = MagicMock()
    mock_provider.get_hash.return_value = "abc123"
    mock_provider.plan.return_value = DeployPlan(
        agent_name="test-bot",
        actions=[],
        current_hash="abc123",
        target_hash="abc123",
        changes={},
    )
    mock_get_provider.return_value = mock_provider

    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        from pathlib import Path

        Path(td).joinpath("vystak.yaml").write_text(yaml.dump(SAMPLE_AGENT_YAML))
        result = runner.invoke(cli, ["plan"])

    assert result.exit_code == 0
    assert "up to date" in result.output.lower()


@patch("vystak_cli.commands.apply.get_provider")
def test_apply_success(mock_get_provider, tmp_path):
    from vystak.providers.base import DeployPlan, DeployResult

    mock_provider = MagicMock()
    mock_provider.get_hash.return_value = None
    mock_provider.plan.return_value = DeployPlan(
        agent_name="test-bot",
        actions=["Create new deployment"],
        current_hash=None,
        target_hash="abc123",
        changes={},
    )
    mock_provider.apply.return_value = DeployResult(
        agent_name="test-bot",
        success=True,
        hash="abc123",
        message="Deployed",
    )
    mock_get_provider.return_value = mock_provider

    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        from pathlib import Path

        Path(td).joinpath("vystak.yaml").write_text(yaml.dump(SAMPLE_AGENT_YAML))
        result = runner.invoke(cli, ["apply"])

    assert result.exit_code == 0, result.output
    assert "Deployed" in result.output


@patch("vystak_provider_docker.DockerProvider")
def test_destroy_success(mock_provider_cls):
    mock_provider = MagicMock()
    mock_provider_cls.return_value = mock_provider

    runner = CliRunner()
    result = runner.invoke(cli, ["destroy", "--name", "test-bot"])

    assert result.exit_code == 0
    assert "Destroyed" in result.output
    mock_provider.destroy.assert_called_once_with(
        "test-bot",
        include_resources=False,
        no_wait=False,
        delete_vault=False,
        keep_sidecars=False,
        delete_workspace_data=False,
        keep_workspace=False,
    )


@patch("vystak_provider_docker.DockerProvider")
def test_status_running(mock_provider_cls):
    from vystak.providers.base import AgentStatus

    mock_provider = MagicMock()
    mock_provider.status.return_value = AgentStatus(
        agent_name="test-bot",
        running=True,
        hash="abc123def456",
        info={"container": "vystak-test-bot", "ports": {"8000/tcp": [{"HostPort": "32768"}]}},
    )
    mock_provider_cls.return_value = mock_provider

    runner = CliRunner()
    result = runner.invoke(cli, ["status", "--name", "test-bot"])

    assert result.exit_code == 0
    assert "running" in result.output
    assert "32768" in result.output


@patch("vystak_provider_docker.DockerProvider")
def test_status_not_found(mock_provider_cls):
    from vystak.providers.base import AgentStatus

    mock_provider = MagicMock()
    mock_provider.status.return_value = AgentStatus(
        agent_name="test-bot",
        running=False,
        hash=None,
    )
    mock_provider_cls.return_value = mock_provider

    runner = CliRunner()
    result = runner.invoke(cli, ["status", "--name", "test-bot"])

    assert result.exit_code == 0
    assert "not deployed" in result.output
