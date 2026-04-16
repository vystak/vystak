from unittest.mock import MagicMock, patch

import pytest
from vystak.providers.base import DeployPlan, GeneratedCode
from vystak.provisioning.node import ProvisionResult
from vystak.schema.agent import Agent
from vystak.schema.model import Model
from vystak.schema.provider import Provider
from vystak_provider_docker.provider import DockerProvider


@pytest.fixture()
def mock_docker_client():
    with patch("vystak_provider_docker.provider.docker") as mock_docker:
        client = MagicMock()
        mock_docker.from_env.return_value = client
        mock_docker.errors.NotFound = type("NotFound", (Exception,), {})
        mock_docker.errors.DockerException = type("DockerException", (Exception,), {})
        yield client, mock_docker.errors


@pytest.fixture()
def provider(mock_docker_client):
    return DockerProvider()


@pytest.fixture()
def not_found_error(mock_docker_client):
    _, errors = mock_docker_client
    return errors.NotFound


@pytest.fixture()
def sample_agent():
    return Agent(
        name="test-bot",
        model=Model(
            name="claude",
            provider=Provider(name="anthropic", type="anthropic"),
            model_name="claude-sonnet-4-20250514",
        ),
    )


@pytest.fixture()
def sample_code():
    return GeneratedCode(
        files={
            "agent.py": "# agent code",
            "server.py": "# server code",
            "requirements.txt": "fastapi\nuvicorn\n",
        },
        entrypoint="server.py",
    )


class TestContainerNaming:
    def test_container_name(self, provider):
        assert provider._container_name("my-bot") == "vystak-my-bot"


class TestGetHash:
    def test_returns_hash_from_label(self, provider, mock_docker_client):
        client, _ = mock_docker_client
        container = MagicMock()
        container.labels = {"vystak.hash": "abc123"}
        client.containers.get.return_value = container
        assert provider.get_hash("test-bot") == "abc123"

    def test_returns_none_when_no_container(self, provider, mock_docker_client, not_found_error):
        client, _ = mock_docker_client
        client.containers.get.side_effect = not_found_error("not found")
        assert provider.get_hash("test-bot") is None


class TestPlan:
    def test_new_deployment(self, provider, sample_agent, mock_docker_client, not_found_error):
        client, _ = mock_docker_client
        client.containers.get.side_effect = not_found_error("not found")
        plan = provider.plan(sample_agent, None)
        assert plan.agent_name == "test-bot"
        assert len(plan.actions) > 0
        assert plan.current_hash is None

    def test_no_change(self, provider, sample_agent, mock_docker_client):
        from vystak.hash import hash_agent

        client, _ = mock_docker_client
        tree = hash_agent(sample_agent)
        container = MagicMock()
        container.labels = {"vystak.hash": tree.root}
        client.containers.get.return_value = container
        plan = provider.plan(sample_agent, tree.root)
        assert plan.actions == []

    def test_update(self, provider, sample_agent, mock_docker_client):
        client, _ = mock_docker_client
        container = MagicMock()
        container.labels = {"vystak.hash": "old-hash"}
        client.containers.get.return_value = container
        plan = provider.plan(sample_agent, "old-hash")
        assert len(plan.actions) > 0


class TestApply:
    def test_builds_and_runs(self, provider, mock_docker_client, sample_agent, sample_code):
        """Graph-based apply returns success when agent node succeeds."""
        provider.set_generated_code(sample_code)
        provider.set_agent(sample_agent)
        plan = DeployPlan(
            agent_name="test-bot",
            actions=["Create"],
            current_hash=None,
            target_hash="abc123",
            changes={},
        )

        mock_results = {
            "network": ProvisionResult(name="network", success=True, info={"network": MagicMock()}),
            "agent:test-bot": ProvisionResult(
                name="agent:test-bot",
                success=True,
                info={
                    "url": "http://localhost:8080",
                    "container_name": "vystak-test-bot",
                    "port": "8080",
                },
            ),
        }

        with patch("vystak.provisioning.ProvisionGraph") as MockGraph:
            mock_graph = MagicMock()
            mock_graph.execute.return_value = mock_results
            MockGraph.return_value = mock_graph
            result = provider.apply(plan)

        assert result.success is True
        assert "localhost" in result.message
        mock_graph.add.assert_called()
        mock_graph.execute.assert_called_once()

    def test_replaces_existing(self, provider, mock_docker_client, sample_agent, sample_code):
        """Graph-based apply handles update plans."""
        provider.set_generated_code(sample_code)
        provider.set_agent(sample_agent)
        plan = DeployPlan(
            agent_name="test-bot",
            actions=["Update"],
            current_hash="old",
            target_hash="new",
            changes={},
        )

        mock_results = {
            "network": ProvisionResult(name="network", success=True, info={"network": MagicMock()}),
            "agent:test-bot": ProvisionResult(
                name="agent:test-bot",
                success=True,
                info={
                    "url": "http://localhost:9090",
                    "container_name": "vystak-test-bot",
                    "port": "9090",
                },
            ),
        }

        with patch("vystak.provisioning.ProvisionGraph") as MockGraph:
            mock_graph = MagicMock()
            mock_graph.execute.return_value = mock_results
            MockGraph.return_value = mock_graph
            result = provider.apply(plan)

        assert result.success is True

    def test_no_generated_code(self, provider, mock_docker_client):
        """apply() returns failure when no generated code is set."""
        plan = DeployPlan(
            agent_name="test-bot",
            actions=["Create"],
            current_hash=None,
            target_hash="abc123",
            changes={},
        )
        result = provider.apply(plan)
        assert result.success is False
        assert "set_generated_code" in result.message


class TestDestroy:
    def test_removes_container(self, provider, mock_docker_client):
        client, _ = mock_docker_client
        container = MagicMock()
        client.containers.get.return_value = container
        provider.destroy("test-bot")
        container.stop.assert_called_once()
        container.remove.assert_called_once()

    def test_not_found(self, provider, mock_docker_client, not_found_error):
        client, _ = mock_docker_client
        client.containers.get.side_effect = not_found_error("not found")
        provider.destroy("test-bot")  # should not raise

    def test_include_resources(self, provider, mock_docker_client, sample_agent):
        """destroy with include_resources uses DockerServiceNode.destroy()."""
        client, _ = mock_docker_client
        container = MagicMock()
        client.containers.get.return_value = container
        # Empty containers list for service destroy
        client.containers.list.return_value = []
        provider.set_agent(sample_agent)
        with patch("vystak_provider_docker.provider.DockerProvider.destroy_gateways"):
            provider.destroy("test-bot", include_resources=True)
        container.stop.assert_called_once()
        container.remove.assert_called_once()


class TestStatus:
    def test_running(self, provider, mock_docker_client):
        client, _ = mock_docker_client
        container = MagicMock()
        container.status = "running"
        container.labels = {"vystak.hash": "abc123"}
        container.ports = {"8000/tcp": [{"HostPort": "32768"}]}
        client.containers.get.return_value = container
        status = provider.status("test-bot")
        assert status.running is True
        assert status.hash == "abc123"

    def test_not_found(self, provider, mock_docker_client, not_found_error):
        client, _ = mock_docker_client
        client.containers.get.side_effect = not_found_error("not found")
        status = provider.status("test-bot")
        assert status.running is False
        assert status.hash is None
