"""Tests for Docker provider node types."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agentstack.provisioning.health import CommandHealthCheck, NoopHealthCheck
from agentstack.provisioning.node import ProvisionResult


class TestDockerNetworkNode:
    def test_provision_creates_network(self):
        from agentstack_provider_docker.nodes.network import DockerNetworkNode

        client = MagicMock()
        client.networks.list.return_value = []
        network = MagicMock()
        network.name = "agentstack-net"
        client.networks.create.return_value = network
        node = DockerNetworkNode(client)
        assert node.name == "network"
        assert node.depends_on == []
        result = node.provision(context={})
        assert result.success
        assert result.info["network_name"] == "agentstack-net"

    def test_provision_reuses_existing(self):
        from agentstack_provider_docker.nodes.network import DockerNetworkNode

        client = MagicMock()
        existing = MagicMock()
        existing.name = "agentstack-net"
        client.networks.list.return_value = [existing]
        node = DockerNetworkNode(client)
        result = node.provision(context={})
        assert result.success
        client.networks.create.assert_not_called()

    def test_health_check_is_noop(self):
        from agentstack_provider_docker.nodes.network import DockerNetworkNode

        node = DockerNetworkNode(MagicMock())
        assert isinstance(node.health_check(), NoopHealthCheck)


class TestDockerServiceNode:
    @pytest.fixture()
    def mock_client(self):
        return MagicMock()

    def test_provision_postgres(self, mock_client, tmp_path):
        from agentstack_provider_docker.nodes.service import DockerServiceNode

        mock_client.containers.list.return_value = []
        with patch(
            "agentstack_provider_docker.nodes.service.get_resource_password",
            return_value="testpass",
        ):
            svc = MagicMock()
            svc.name = "sessions"
            svc.engine = "postgres"
            svc.depends_on = []
            node = DockerServiceNode(mock_client, svc, tmp_path / "secrets.json")
            assert node.name == "sessions"
            network = MagicMock()
            network.name = "agentstack-net"
            context = {
                "network": ProvisionResult(
                    name="network", success=True, info={"network": network}
                )
            }
            result = node.provision(context=context)
            assert result.success
            assert result.info["engine"] == "postgres"
            assert "connection_string" in result.info
            mock_client.containers.run.assert_called_once()

    def test_provision_sqlite(self, mock_client, tmp_path):
        from agentstack_provider_docker.nodes.service import DockerServiceNode

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
        from agentstack_provider_docker.nodes.service import DockerServiceNode

        svc = MagicMock()
        svc.name = "sessions"
        svc.engine = "postgres"
        svc.depends_on = []
        node = DockerServiceNode(mock_client, svc, tmp_path / "secrets.json")
        assert "network" in node.depends_on

    def test_depends_on_includes_explicit(self, mock_client, tmp_path):
        from agentstack_provider_docker.nodes.service import DockerServiceNode

        svc = MagicMock()
        svc.name = "cache"
        svc.engine = "redis"
        svc.depends_on = ["sessions"]
        node = DockerServiceNode(mock_client, svc, tmp_path / "secrets.json")
        assert "sessions" in node.depends_on
        assert "network" in node.depends_on

    def test_health_check_postgres(self, mock_client, tmp_path):
        from agentstack_provider_docker.nodes.service import DockerServiceNode

        mock_client.containers.list.return_value = []
        with patch(
            "agentstack_provider_docker.nodes.service.get_resource_password",
            return_value="testpass",
        ):
            svc = MagicMock()
            svc.name = "sessions"
            svc.engine = "postgres"
            svc.depends_on = []
            node = DockerServiceNode(mock_client, svc, tmp_path / "secrets.json")
            network = MagicMock()
            network.name = "agentstack-net"
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
        from agentstack_provider_docker.nodes.service import DockerServiceNode

        svc = MagicMock()
        svc.name = "sessions"
        svc.engine = "sqlite"
        svc.depends_on = []
        node = DockerServiceNode(mock_client, svc, tmp_path / "secrets.json")
        assert isinstance(node.health_check(), NoopHealthCheck)

    def test_destroy_stops_and_removes_container(self, mock_client, tmp_path):
        from agentstack_provider_docker.nodes.service import DockerServiceNode

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
        from agentstack_provider_docker.nodes.service import DockerServiceNode

        existing_container = MagicMock()
        existing_container.status = "running"
        mock_client.containers.list.return_value = [existing_container]
        with patch(
            "agentstack_provider_docker.nodes.service.get_resource_password",
            return_value="testpass",
        ):
            svc = MagicMock()
            svc.name = "sessions"
            svc.engine = "postgres"
            svc.depends_on = []
            node = DockerServiceNode(mock_client, svc, tmp_path / "secrets.json")
            network = MagicMock()
            network.name = "agentstack-net"
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
        from agentstack_provider_docker.nodes.agent import DockerAgentNode

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
        from agentstack_provider_docker.nodes.agent import DockerAgentNode

        client = MagicMock()
        agent = MagicMock()
        agent.name = "my-agent"
        agent.sessions = None
        agent.memory = None
        agent.services = []
        node = DockerAgentNode(client, agent, MagicMock(), MagicMock())
        assert isinstance(node.health_check(), NoopHealthCheck)


class TestDockerGatewayNode:
    def test_name_and_depends_on(self):
        from agentstack_provider_docker.nodes.gateway import DockerGatewayNode

        client = MagicMock()
        node = DockerGatewayNode(client, "slack-gw", {}, "my-agent")
        assert node.name == "gateway:slack-gw"
        assert node.depends_on == ["agent:my-agent"]

    def test_health_check_is_noop(self):
        from agentstack_provider_docker.nodes.gateway import DockerGatewayNode

        client = MagicMock()
        node = DockerGatewayNode(client, "slack-gw", {}, "my-agent")
        assert isinstance(node.health_check(), NoopHealthCheck)
