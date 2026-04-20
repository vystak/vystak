"""Tests for Docker provider node types."""

from unittest.mock import MagicMock, patch

import pytest
from vystak.provisioning.health import CommandHealthCheck, NoopHealthCheck
from vystak.provisioning.node import ProvisionResult


@pytest.fixture()
def _patched_docker_errors():
    """Stub ``docker.errors.NotFound`` so nodes can catch it off mocks."""
    fake_not_found = type("NotFound", (Exception,), {})
    with patch("docker.errors") as mock_errors:
        mock_errors.NotFound = fake_not_found
        yield fake_not_found


class TestDockerNetworkNode:
    def test_provision_creates_network(self):
        from vystak_provider_docker.nodes.network import DockerNetworkNode

        client = MagicMock()
        client.networks.list.return_value = []
        network = MagicMock()
        network.name = "vystak-net"
        client.networks.create.return_value = network
        node = DockerNetworkNode(client)
        assert node.name == "network"
        assert node.depends_on == []
        result = node.provision(context={})
        assert result.success
        assert result.info["network_name"] == "vystak-net"

    def test_provision_reuses_existing(self):
        from vystak_provider_docker.nodes.network import DockerNetworkNode

        client = MagicMock()
        existing = MagicMock()
        existing.name = "vystak-net"
        client.networks.list.return_value = [existing]
        node = DockerNetworkNode(client)
        result = node.provision(context={})
        assert result.success
        client.networks.create.assert_not_called()

    def test_health_check_is_noop(self):
        from vystak_provider_docker.nodes.network import DockerNetworkNode

        node = DockerNetworkNode(MagicMock())
        assert isinstance(node.health_check(), NoopHealthCheck)


class TestDockerServiceNode:
    @pytest.fixture()
    def mock_client(self):
        return MagicMock()

    def test_provision_postgres(self, mock_client, tmp_path):
        from vystak_provider_docker.nodes.service import DockerServiceNode

        mock_client.containers.list.return_value = []
        with patch(
            "vystak_provider_docker.nodes.service.get_resource_password",
            return_value="testpass",
        ):
            svc = MagicMock()
            svc.name = "sessions"
            svc.engine = "postgres"
            svc.depends_on = []
            node = DockerServiceNode(mock_client, svc, tmp_path / "secrets.json")
            assert node.name == "sessions"
            network = MagicMock()
            network.name = "vystak-net"
            context = {
                "network": ProvisionResult(name="network", success=True, info={"network": network})
            }
            result = node.provision(context=context)
            assert result.success
            assert result.info["engine"] == "postgres"
            assert "connection_string" in result.info
            mock_client.containers.run.assert_called_once()

    def test_provision_sqlite(self, mock_client, tmp_path):
        from vystak_provider_docker.nodes.service import DockerServiceNode

        mock_client.volumes.list.return_value = []
        svc = MagicMock()
        svc.name = "sessions"
        svc.engine = "sqlite"
        svc.depends_on = []
        node = DockerServiceNode(mock_client, svc, tmp_path / "secrets.json")
        result = node.provision(context={})
        assert result.success
        assert result.info["engine"] == "sqlite"

    def test_depends_on_includes_network(self, mock_client, tmp_path):
        from vystak_provider_docker.nodes.service import DockerServiceNode

        svc = MagicMock()
        svc.name = "sessions"
        svc.engine = "postgres"
        svc.depends_on = []
        node = DockerServiceNode(mock_client, svc, tmp_path / "secrets.json")
        assert "network" in node.depends_on

    def test_depends_on_includes_explicit(self, mock_client, tmp_path):
        from vystak_provider_docker.nodes.service import DockerServiceNode

        svc = MagicMock()
        svc.name = "cache"
        svc.engine = "redis"
        svc.depends_on = ["sessions"]
        node = DockerServiceNode(mock_client, svc, tmp_path / "secrets.json")
        assert "sessions" in node.depends_on
        assert "network" in node.depends_on

    def test_health_check_postgres(self, mock_client, tmp_path):
        from vystak_provider_docker.nodes.service import DockerServiceNode

        mock_client.containers.list.return_value = []
        with patch(
            "vystak_provider_docker.nodes.service.get_resource_password",
            return_value="testpass",
        ):
            svc = MagicMock()
            svc.name = "sessions"
            svc.engine = "postgres"
            svc.depends_on = []
            node = DockerServiceNode(mock_client, svc, tmp_path / "secrets.json")
            network = MagicMock()
            network.name = "vystak-net"
            node.provision(
                context={
                    "network": ProvisionResult(
                        name="network", success=True, info={"network": network}
                    )
                }
            )
            check = node.health_check()
            assert isinstance(check, CommandHealthCheck)

    def test_health_check_sqlite(self, mock_client, tmp_path):
        from vystak_provider_docker.nodes.service import DockerServiceNode

        svc = MagicMock()
        svc.name = "sessions"
        svc.engine = "sqlite"
        svc.depends_on = []
        node = DockerServiceNode(mock_client, svc, tmp_path / "secrets.json")
        assert isinstance(node.health_check(), NoopHealthCheck)

    def test_destroy_stops_and_removes_container(self, mock_client, tmp_path):
        from vystak_provider_docker.nodes.service import DockerServiceNode

        container = MagicMock()
        mock_client.containers.list.return_value = [container]
        svc = MagicMock()
        svc.name = "sessions"
        svc.engine = "postgres"
        svc.depends_on = []
        node = DockerServiceNode(mock_client, svc, tmp_path / "secrets.json")
        node.destroy()
        container.stop.assert_called_once()
        container.remove.assert_called_once()

    def test_provision_postgres_reuses_existing(self, mock_client, tmp_path):
        from vystak_provider_docker.nodes.service import DockerServiceNode

        existing_container = MagicMock()
        existing_container.status = "running"
        mock_client.containers.list.return_value = [existing_container]
        with patch(
            "vystak_provider_docker.nodes.service.get_resource_password",
            return_value="testpass",
        ):
            svc = MagicMock()
            svc.name = "sessions"
            svc.engine = "postgres"
            svc.depends_on = []
            node = DockerServiceNode(mock_client, svc, tmp_path / "secrets.json")
            network = MagicMock()
            network.name = "vystak-net"
            result = node.provision(
                context={
                    "network": ProvisionResult(
                        name="network", success=True, info={"network": network}
                    )
                }
            )
            assert result.success
            mock_client.containers.run.assert_not_called()


class TestDockerAgentNode:
    def test_name_and_depends_on(self):
        from vystak_provider_docker.nodes.agent import DockerAgentNode

        client = MagicMock()
        agent = MagicMock()
        agent.name = "my-agent"
        agent.sessions = MagicMock()
        agent.sessions.name = "sessions"
        agent.memory = MagicMock()
        agent.memory.name = "memory"
        agent.services = []
        code = MagicMock()
        plan = MagicMock()
        node = DockerAgentNode(client, agent, code, plan)
        assert node.name == "agent:my-agent"
        assert "network" in node.depends_on
        assert "sessions" in node.depends_on
        assert "memory" in node.depends_on

    def test_health_check_is_noop(self):
        from vystak_provider_docker.nodes.agent import DockerAgentNode

        client = MagicMock()
        agent = MagicMock()
        agent.name = "my-agent"
        agent.sessions = None
        agent.memory = None
        agent.services = []
        node = DockerAgentNode(client, agent, MagicMock(), MagicMock())
        assert isinstance(node.health_check(), NoopHealthCheck)

    def test_extra_env_defaults_to_empty(self):
        from vystak_provider_docker.nodes.agent import DockerAgentNode

        agent = MagicMock()
        agent.name = "a"
        agent.sessions = None
        agent.memory = None
        agent.services = []
        node = DockerAgentNode(MagicMock(), agent, MagicMock(), MagicMock())
        assert node._extra_env == {}

    def test_extra_env_stored(self):
        from vystak_provider_docker.nodes.agent import DockerAgentNode

        agent = MagicMock()
        agent.name = "a"
        agent.sessions = None
        agent.memory = None
        agent.services = []
        node = DockerAgentNode(
            MagicMock(),
            agent,
            MagicMock(),
            MagicMock(),
            extra_env={"VYSTAK_TRANSPORT_TYPE": "nats"},
        )
        assert node._extra_env["VYSTAK_TRANSPORT_TYPE"] == "nats"


class TestDockerChannelNode:
    def test_extra_env_defaults_to_empty(self):
        from vystak_provider_docker.nodes.channel import DockerChannelNode

        channel = MagicMock()
        channel.name = "api"
        node = DockerChannelNode(MagicMock(), channel, MagicMock(), "hash")
        assert node._extra_env == {}

    def test_extra_env_stored(self):
        from vystak_provider_docker.nodes.channel import DockerChannelNode

        channel = MagicMock()
        channel.name = "api"
        node = DockerChannelNode(
            MagicMock(),
            channel,
            MagicMock(),
            "hash",
            extra_env={"VYSTAK_NATS_URL": "nats://vystak-nats:4222"},
        )
        assert node._extra_env == {"VYSTAK_NATS_URL": "nats://vystak-nats:4222"}


class TestNatsServerNode:
    def test_name_and_depends_on(self):
        from vystak_provider_docker.nodes.nats_server import NatsServerNode

        node = NatsServerNode(MagicMock())
        assert node.name == "nats-server"
        assert node.depends_on == ["network"]

    def test_provision_creates_container(self, _patched_docker_errors):
        from vystak_provider_docker.nodes.nats_server import NatsServerNode

        client = MagicMock()
        client.containers.get.side_effect = _patched_docker_errors("not found")
        network = MagicMock()
        network.name = "vystak-net"
        context = {
            "network": ProvisionResult(name="network", success=True, info={"network": network})
        }
        node = NatsServerNode(client)
        result = node.provision(context=context)
        assert result.success
        assert result.info["url"] == "nats://vystak-nats:4222"
        client.images.pull.assert_called_once_with("nats:2.10-alpine")
        client.containers.run.assert_called_once()
        _, kwargs = client.containers.run.call_args
        assert kwargs["name"] == "vystak-nats"
        assert kwargs["command"] == ["-js", "-sd", "/data"]
        assert kwargs["network"] == "vystak-net"
        assert kwargs["ports"] == {"4222/tcp": 4222}
        assert kwargs["labels"] == {"vystak.service": "nats"}

    def test_provision_reuses_running_container(self, _patched_docker_errors):
        from vystak_provider_docker.nodes.nats_server import NatsServerNode

        client = MagicMock()
        existing = MagicMock()
        existing.status = "running"
        client.containers.get.return_value = existing
        network = MagicMock()
        network.name = "vystak-net"
        context = {
            "network": ProvisionResult(name="network", success=True, info={"network": network})
        }
        node = NatsServerNode(client)
        result = node.provision(context=context)
        assert result.success
        client.containers.run.assert_not_called()
        existing.start.assert_not_called()

    def test_provision_restarts_stopped_container(self, _patched_docker_errors):
        from vystak_provider_docker.nodes.nats_server import NatsServerNode

        client = MagicMock()
        existing = MagicMock()
        existing.status = "exited"
        client.containers.get.return_value = existing
        network = MagicMock()
        network.name = "vystak-net"
        context = {
            "network": ProvisionResult(name="network", success=True, info={"network": network})
        }
        node = NatsServerNode(client)
        result = node.provision(context=context)
        assert result.success
        existing.start.assert_called_once()
        client.containers.run.assert_not_called()

    def test_destroy_removes_container(self, _patched_docker_errors):
        from vystak_provider_docker.nodes.nats_server import NatsServerNode

        client = MagicMock()
        container = MagicMock()
        client.containers.get.return_value = container
        NatsServerNode(client).destroy()
        container.stop.assert_called_once()
        container.remove.assert_called_once()

    def test_destroy_not_found_is_noop(self, _patched_docker_errors):
        from vystak_provider_docker.nodes.nats_server import NatsServerNode

        client = MagicMock()
        client.containers.get.side_effect = _patched_docker_errors("not found")
        NatsServerNode(client).destroy()  # should not raise
