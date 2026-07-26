"""Tests for DockerProvider.apply() threading scheduler_enabled onto the
DockerAgentNode it constructs.

Per-agent variant: scheduler_enabled is True when the agent itself carries
a heartbeat or non-empty schedules, OR the platform's scheduler toggle is
enabled. It does NOT consider whether *other* agents on the same platform
declare schedules (documented nice-to-have, not implemented — see task-9
report).
"""

from unittest.mock import MagicMock, patch

import pytest
from vystak.providers.base import DeployPlan, FileBundle
from vystak.provisioning.node import ProvisionResult
from vystak.schema.agent import Agent
from vystak.schema.heartbeat import Heartbeat
from vystak.schema.model import Model
from vystak.schema.platform import Platform, SchedulerConfig
from vystak.schema.provider import Provider
from vystak.schema.schedule import ScheduledTask
from vystak_provider_docker.nodes.agent import DockerAgentNode
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


@pytest.fixture()
def sample_code():
    return FileBundle(
        files={
            "agent.py": "# agent code",
            "server.py": "# server code",
            "requirements.txt": "fastapi\nuvicorn\n",
        },
        entrypoint="server.py",
    )


def _model():
    return Model(
        name="claude",
        provider=Provider(name="anthropic", type="anthropic"),
        model_name="claude-sonnet-4-20250514",
    )


def _run_apply(provider, agent, sample_code):
    provider.set_generated_code(sample_code)
    provider.set_agent(agent)
    plan = DeployPlan(
        agent_name=agent.name,
        actions=["Create"],
        current_hash=None,
        target_hash="abc123",
        changes={},
    )
    mock_results = {
        "network": ProvisionResult(name="network", success=True, info={"network": MagicMock()}),
        f"agent:{agent.name}": ProvisionResult(
            name=f"agent:{agent.name}",
            success=True,
            info={"url": "http://localhost:8080"},
        ),
    }
    added_nodes: list = []
    with patch("vystak.provisioning.ProvisionGraph") as MockGraph:
        mock_graph = MagicMock()
        mock_graph.execute.return_value = mock_results
        mock_graph.add.side_effect = lambda node: added_nodes.append(node)
        MockGraph.return_value = mock_graph
        result = provider.apply(plan)
    assert result.success is True
    agent_nodes = [n for n in added_nodes if isinstance(n, DockerAgentNode)]
    assert len(agent_nodes) == 1
    return agent_nodes[0]


class TestSchedulerEnabledWiring:
    def test_agent_with_heartbeat_gets_scheduler_enabled(
        self, provider, mock_docker_client, sample_code
    ):
        agent = Agent(
            name="bot",
            framework="langchain-python",
            default_model=_model(),
            heartbeat=Heartbeat(schedule="*/30 * * * *", target_channel="x.channels.dev"),
        )
        node = _run_apply(provider, agent, sample_code)
        assert node._scheduler_enabled is True

    def test_agent_with_schedules_gets_scheduler_enabled(
        self, provider, mock_docker_client, sample_code
    ):
        agent = Agent(
            name="worker",
            framework="langchain-python",
            default_model=_model(),
            schedules=[ScheduledTask(name="digest", cron="0 9 * * 1")],
        )
        node = _run_apply(provider, agent, sample_code)
        assert node._scheduler_enabled is True

    def test_platform_toggle_enables_even_without_agent_schedules(
        self, provider, mock_docker_client, sample_code
    ):
        platform = Platform(
            name="local",
            type="docker",
            provider=Provider(name="docker", type="docker"),
            scheduler=SchedulerConfig(enabled=True),
        )
        agent = Agent(
            name="idle",
            framework="langchain-python",
            default_model=_model(),
            platform=platform,
        )
        node = _run_apply(provider, agent, sample_code)
        assert node._scheduler_enabled is True

    def test_no_heartbeat_no_schedules_no_toggle_disables(
        self, provider, mock_docker_client, sample_code
    ):
        agent = Agent(
            name="plain",
            framework="langchain-python",
            default_model=_model(),
        )
        node = _run_apply(provider, agent, sample_code)
        assert node._scheduler_enabled is False

    def test_platform_toggle_disabled_and_no_schedules_disables(
        self, provider, mock_docker_client, sample_code
    ):
        platform = Platform(
            name="local",
            type="docker",
            provider=Provider(name="docker", type="docker"),
            scheduler=SchedulerConfig(enabled=False),
        )
        agent = Agent(
            name="plain",
            framework="langchain-python",
            default_model=_model(),
            platform=platform,
        )
        node = _run_apply(provider, agent, sample_code)
        assert node._scheduler_enabled is False
