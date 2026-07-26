"""Tests for DockerProvider.apply_scheduler() and the apply_heartbeat alias."""

from unittest.mock import MagicMock, patch

import pytest
from vystak.schema.agent import Agent
from vystak.schema.model import Model
from vystak.schema.platform import Platform, SchedulerConfig
from vystak.schema.provider import Provider
from vystak.schema.schedule import ScheduledTask
from vystak_provider_docker.provider import DockerProvider


@pytest.fixture()
def mock_docker_client():
    with patch("vystak_provider_docker.provider.docker") as mock_docker:
        client = MagicMock()
        mock_docker.from_env.return_value = client
        mock_docker.errors.NotFound = type("NotFound", (Exception,), {})
        mock_docker.errors.DockerException = type("DockerException", (Exception,), {})
        mock_docker.errors.APIError = type("APIError", (Exception,), {})
        yield client, mock_docker.errors


@pytest.fixture()
def provider(mock_docker_client):
    return DockerProvider()


def _model():
    return Model(
        name="claude",
        provider=Provider(name="anthropic", type="anthropic"),
        model_name="claude-sonnet-4-20250514",
    )


class TestApplySchedulerProvisioning:
    def test_provisions_for_schedules_only_agent(self, provider, mock_docker_client):
        """An agent with no heartbeat but non-empty schedules must still
        cause the scheduler container to be provisioned."""
        from vystak_provider_docker.nodes.heartbeat import DockerHeartbeatNode

        agent = Agent(
            name="worker",
            framework="langchain-python",
            default_model=_model(),
            schedules=[ScheduledTask(name="digest", cron="0 9 * * 1")],
        )

        added_nodes: list = []
        with patch("vystak.provisioning.ProvisionGraph") as MockGraph:
            mock_graph = MagicMock()
            mock_graph.add.side_effect = lambda node: added_nodes.append(node)
            MockGraph.return_value = mock_graph
            provider.apply_scheduler([agent], [])

        assert any(isinstance(n, DockerHeartbeatNode) for n in added_nodes)
        mock_graph.execute.assert_called_once()

    def test_empty_list_with_platform_toggle_still_provisions(
        self, provider, mock_docker_client
    ):
        """Zero schedule/heartbeat agents, but platform.scheduler.enabled is
        True — the container must still be provisioned. Critical: the SAME
        platform object driving the outer decision must reach apply_scheduler
        so its inner guard doesn't independently return early."""
        from vystak_provider_docker.nodes.heartbeat import DockerHeartbeatNode

        platform = Platform(
            name="local",
            type="docker",
            provider=Provider(name="docker", type="docker"),
            scheduler=SchedulerConfig(enabled=True),
        )

        added_nodes: list = []
        with patch("vystak.provisioning.ProvisionGraph") as MockGraph:
            mock_graph = MagicMock()
            mock_graph.add.side_effect = lambda node: added_nodes.append(node)
            MockGraph.return_value = mock_graph
            provider.apply_scheduler([], [], platform=platform)

        assert any(isinstance(n, DockerHeartbeatNode) for n in added_nodes)
        mock_graph.execute.assert_called_once()

    def test_empty_list_without_toggle_returns_early(self, provider, mock_docker_client):
        """No schedule/heartbeat agents and no platform toggle: still a
        no-op, matching the pre-Task-9 early-return behavior."""
        with patch("vystak.provisioning.ProvisionGraph") as MockGraph:
            provider.apply_scheduler([], [])
            MockGraph.assert_not_called()

    def test_empty_list_with_disabled_toggle_returns_early(
        self, provider, mock_docker_client
    ):
        platform = Platform(
            name="local",
            type="docker",
            provider=Provider(name="docker", type="docker"),
            scheduler=SchedulerConfig(enabled=False),
        )
        with patch("vystak.provisioning.ProvisionGraph") as MockGraph:
            provider.apply_scheduler([], [], platform=platform)
            MockGraph.assert_not_called()

    def test_empty_list_with_no_scheduler_config_returns_early(
        self, provider, mock_docker_client
    ):
        platform = Platform(
            name="local",
            type="docker",
            provider=Provider(name="docker", type="docker"),
        )
        with patch("vystak.provisioning.ProvisionGraph") as MockGraph:
            provider.apply_scheduler([], [], platform=platform)
            MockGraph.assert_not_called()

    def test_agent_addresses_cover_every_passed_agent(self, provider, mock_docker_client):
        with patch("vystak_heartbeat.plugin.build_bundle") as mock_build_bundle, patch(
            "vystak.provisioning.ProvisionGraph"
        ) as MockGraph:
            mock_graph = MagicMock()
            MockGraph.return_value = mock_graph
            a1 = Agent(
                name="a1", framework="langchain-python", default_model=_model(),
                heartbeat=None, schedules=[ScheduledTask(name="d", cron="0 9 * * 1")],
            )
            a2 = Agent(
                name="a2", framework="langchain-python", default_model=_model(),
                schedules=[ScheduledTask(name="e", cron="0 10 * * 1")],
            )
            provider.apply_scheduler([a1, a2], [])

        _, kwargs = mock_build_bundle.call_args
        assert kwargs["agent_addresses"] == {
            a1.canonical_name: "http://vystak-a1:8000/a2a",
            a2.canonical_name: "http://vystak-a2:8000/a2a",
        }
        assert kwargs["agents_with_schedules"] == [a1, a2]

    def test_provider_uses_sqlite_store_cfg(self, provider, mock_docker_client):
        """Provider must always use SQLite for the scheduler store (not Postgres).
        This pins the design boundary: provider stays sqlite-only by design;
        opt-in Postgres is via direct build_bundle calls with store_cfg."""
        with patch("vystak_heartbeat.plugin.build_bundle") as mock_build_bundle, patch(
            "vystak.provisioning.ProvisionGraph"
        ) as MockGraph:
            mock_graph = MagicMock()
            MockGraph.return_value = mock_graph
            agent = Agent(
                name="bot",
                framework="langchain-python",
                default_model=_model(),
                schedules=[ScheduledTask(name="task", cron="0 9 * * 1")],
            )
            provider.apply_scheduler([agent], [])

        _, kwargs = mock_build_bundle.call_args
        assert kwargs["store_cfg"] == {"type": "sqlite", "path": "/data/scheduler.db"}


class TestApplyHeartbeatAlias:
    def test_delegates_to_apply_scheduler(self, provider, mock_docker_client):
        agents = ["sentinel-agents"]
        channels = ["sentinel-channels"]
        platform = object()
        with patch.object(provider, "apply_scheduler") as mock_apply_scheduler:
            provider.apply_heartbeat(agents, channels, platform=platform)

        mock_apply_scheduler.assert_called_once_with(
            agents, channels, platform=platform
        )
