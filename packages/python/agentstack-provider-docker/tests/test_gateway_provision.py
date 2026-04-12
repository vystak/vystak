import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agentstack_provider_docker.gateway import (
    build_gateway_image,
    destroy_gateway,
    provision_gateway,
    write_gateway_source,
    write_routes_file,
)


class TestWriteGatewaySource:
    def test_writes_files(self, tmp_path):
        gateway_dir = tmp_path / "gateway"
        write_gateway_source(gateway_dir)
        assert (gateway_dir / "server.py").exists()
        assert (gateway_dir / "router.py").exists()
        assert (gateway_dir / "providers" / "slack.py").exists()
        assert (gateway_dir / "providers" / "base.py").exists()
        assert (gateway_dir / "requirements.txt").exists()
        assert (gateway_dir / "Dockerfile").exists()

    def test_server_py_content(self, tmp_path):
        gateway_dir = tmp_path / "gateway"
        write_gateway_source(gateway_dir)
        content = (gateway_dir / "server.py").read_text()
        assert "FastAPI" in content


class TestWriteRoutesFile:
    def test_writes_valid_json(self, tmp_path):
        routes_path = tmp_path / "routes.json"
        write_routes_file(routes_path, [
            {"name": "test-slack", "type": "slack", "config": {"bot_token": "xoxb-test"}},
        ], [
            {"provider_name": "test-slack", "agent_name": "bot", "agent_url": "http://bot:8000", "channels": ["#test"], "listen": "mentions", "threads": True, "dm": True},
        ])
        data = json.loads(routes_path.read_text())
        assert len(data["providers"]) == 1
        assert len(data["routes"]) == 1
        assert data["routes"][0]["agent_name"] == "bot"

    def test_overwrites_existing(self, tmp_path):
        routes_path = tmp_path / "routes.json"
        routes_path.write_text("{}")
        write_routes_file(routes_path, [], [{"agent_name": "bot"}])
        data = json.loads(routes_path.read_text())
        assert len(data["routes"]) == 1


class TestBuildGatewayImage:
    @patch("agentstack_provider_docker.gateway.docker")
    def test_builds_image(self, mock_docker):
        client = MagicMock()
        client.images.build.return_value = (MagicMock(), [])
        build_gateway_image(client, "main-gateway", "/tmp/gateway")
        client.images.build.assert_called_once()
        call_kwargs = client.images.build.call_args
        assert "agentstack-gateway-main-gateway" in str(call_kwargs)


class TestProvisionGateway:
    @patch("agentstack_provider_docker.gateway.docker")
    def test_starts_new(self, mock_docker):
        client = MagicMock()
        mock_docker.errors.NotFound = type("NotFound", (Exception,), {})
        client.containers.get.side_effect = mock_docker.errors.NotFound("not found")
        network = MagicMock()
        network.name = "agentstack-net"
        provision_gateway(client, "main-gateway", network, routes_path="/tmp/routes.json", env={"SLACK_TOKEN": "test"}, port=8080)
        client.containers.run.assert_called_once()

    @patch("agentstack_provider_docker.gateway.docker")
    def test_restarts_existing(self, mock_docker):
        client = MagicMock()
        mock_docker.errors.NotFound = type("NotFound", (Exception,), {})
        existing = MagicMock()
        client.containers.get.return_value = existing
        network = MagicMock()
        network.name = "agentstack-net"
        provision_gateway(client, "main-gateway", network, routes_path="/tmp/routes.json", env={}, port=8080)
        existing.stop.assert_called_once()
        existing.remove.assert_called_once()
        client.containers.run.assert_called_once()


class TestDestroyGateway:
    @patch("agentstack_provider_docker.gateway.docker")
    def test_removes(self, mock_docker):
        client = MagicMock()
        mock_docker.errors.NotFound = type("NotFound", (Exception,), {})
        container = MagicMock()
        client.containers.get.return_value = container
        destroy_gateway(client, "main-gateway")
        container.stop.assert_called_once()
        container.remove.assert_called_once()

    @patch("agentstack_provider_docker.gateway.docker")
    def test_not_found(self, mock_docker):
        client = MagicMock()
        mock_docker.errors.NotFound = type("NotFound", (Exception,), {})
        client.containers.get.side_effect = mock_docker.errors.NotFound("not found")
        destroy_gateway(client, "main-gateway")
