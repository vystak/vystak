from unittest.mock import MagicMock, patch

import pytest

from agentstack.providers.base import DeployPlan, GeneratedCode
from agentstack.schema.agent import Agent
from agentstack.schema.model import Model
from agentstack.schema.provider import Provider
from agentstack.schema.service import Postgres

from agentstack_provider_docker.provider import DockerProvider


@pytest.fixture()
def mock_docker_client():
    with patch("agentstack_provider_docker.provider.docker") as mock_docker, \
         patch("agentstack_provider_docker.provider.ensure_network") as mock_network, \
         patch("agentstack_provider_docker.provider.provision_resource") as mock_provision:
        client = MagicMock()
        mock_docker.from_env.return_value = client
        mock_docker.errors.NotFound = type("NotFound", (Exception,), {})
        mock_docker.errors.DockerException = type("DockerException", (Exception,), {})
        mock_network.return_value = MagicMock(name="agentstack-net")
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
        assert provider._container_name("my-bot") == "agentstack-my-bot"


class TestGetHash:
    def test_returns_hash_from_label(self, provider, mock_docker_client):
        client, _ = mock_docker_client
        container = MagicMock()
        container.labels = {"agentstack.hash": "abc123"}
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
        from agentstack.hash import hash_agent
        client, _ = mock_docker_client
        tree = hash_agent(sample_agent)
        container = MagicMock()
        container.labels = {"agentstack.hash": tree.root}
        client.containers.get.return_value = container
        plan = provider.plan(sample_agent, tree.root)
        assert plan.actions == []

    def test_update(self, provider, sample_agent, mock_docker_client):
        client, _ = mock_docker_client
        container = MagicMock()
        container.labels = {"agentstack.hash": "old-hash"}
        client.containers.get.return_value = container
        plan = provider.plan(sample_agent, "old-hash")
        assert len(plan.actions) > 0


class TestApply:
    def test_builds_and_runs(self, provider, mock_docker_client, sample_code, not_found_error):
        client, _ = mock_docker_client
        # First call: no existing container. After run: return a container with ports.
        deployed_container = MagicMock()
        deployed_container.ports = {"8000/tcp": [{"HostPort": "8080"}]}
        client.containers.get.side_effect = [not_found_error("not found"), deployed_container]
        client.images.build.return_value = (MagicMock(), [])
        provider.set_generated_code(sample_code)
        plan = DeployPlan(agent_name="test-bot", actions=["Create"], current_hash=None, target_hash="abc123", changes={})
        result = provider.apply(plan)
        assert result.success is True
        assert "localhost" in result.message
        client.images.build.assert_called_once()
        client.containers.run.assert_called_once()

    def test_replaces_existing(self, provider, mock_docker_client, sample_code):
        client, _ = mock_docker_client
        existing = MagicMock()
        client.containers.get.return_value = existing
        client.images.build.return_value = (MagicMock(), [])
        provider.set_generated_code(sample_code)
        plan = DeployPlan(agent_name="test-bot", actions=["Update"], current_hash="old", target_hash="new", changes={})
        result = provider.apply(plan)
        assert result.success is True
        existing.stop.assert_called_once()
        existing.remove.assert_called_once()


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


class TestBuildEnvWithServices:
    def test_sessions_connection_string(self, provider, mock_docker_client):
        docker_prov = Provider(name="docker", type="docker")
        agent = Agent(
            name="test-bot",
            model=Model(
                name="claude",
                provider=Provider(name="anthropic", type="anthropic"),
                model_name="claude-sonnet-4-20250514",
            ),
            sessions=Postgres(provider=docker_prov),
        )
        provider.set_agent(agent)
        provider._resource_info = [{"engine": "postgres", "connection_string": "postgresql://test"}]
        env = provider._build_env()
        assert env.get("SESSION_STORE_URL") == "postgresql://test"


class TestStatus:
    def test_running(self, provider, mock_docker_client):
        client, _ = mock_docker_client
        container = MagicMock()
        container.status = "running"
        container.labels = {"agentstack.hash": "abc123"}
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
