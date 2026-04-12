from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture()
def mock_docker_client():
    with patch("agentstack_provider_docker.network.docker") as mock_docker:
        client = MagicMock()
        mock_docker.from_env.return_value = client
        yield client


class TestEnsureNetwork:
    def test_creates_network(self, mock_docker_client):
        from agentstack_provider_docker.network import ensure_network

        mock_docker_client.networks.list.return_value = []
        network = ensure_network(mock_docker_client)
        mock_docker_client.networks.create.assert_called_once_with("agentstack-net", driver="bridge")

    def test_reuses_existing(self, mock_docker_client):
        from agentstack_provider_docker.network import ensure_network

        existing = MagicMock()
        existing.name = "agentstack-net"
        mock_docker_client.networks.list.return_value = [existing]
        network = ensure_network(mock_docker_client)
        mock_docker_client.networks.create.assert_not_called()
        assert network == existing
