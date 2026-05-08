"""Tests for JaegerNode — the shared OTLP collector container."""

from unittest.mock import MagicMock, patch

import pytest
from vystak.provisioning.node import ProvisionResult


@pytest.fixture()
def _patched_docker_errors():
    """Stub ``docker.errors.NotFound`` so nodes can catch it off mocks."""
    fake_not_found = type("NotFound", (Exception,), {})
    with patch("docker.errors") as mock_errors:
        mock_errors.NotFound = fake_not_found
        yield fake_not_found


class TestJaegerNode:
    def test_name_and_depends_on(self):
        from vystak_provider_docker.nodes.jaeger import JaegerNode

        node = JaegerNode(MagicMock())
        assert node.name == "jaeger"
        assert node.depends_on == ["network"]

    def test_provision_creates_container(self, _patched_docker_errors):
        from vystak_provider_docker.nodes.jaeger import JaegerNode

        client = MagicMock()
        client.containers.get.side_effect = _patched_docker_errors("not found")
        network = MagicMock()
        network.name = "vystak-net"
        context = {
            "network": ProvisionResult(name="network", success=True, info={"network": network})
        }
        node = JaegerNode(client)
        result = node.provision(context=context)
        assert result.success
        # OTLP endpoints + UI exposed in result info.
        assert result.info["otlp_grpc"] == "http://vystak-jaeger:4317"
        assert result.info["otlp_http"] == "http://vystak-jaeger:4318"
        assert result.info["ui"] == "http://localhost:16686"
        client.images.pull.assert_called_once_with("jaegertracing/all-in-one:1.64")
        client.containers.run.assert_called_once()
        _, kwargs = client.containers.run.call_args
        assert kwargs["name"] == "vystak-jaeger"
        assert kwargs["network"] == "vystak-net"
        # 16686 published to the host; 4317/4318 internal-only by Docker default.
        assert kwargs["ports"] == {
            "16686/tcp": 16686,
            "4317/tcp": 4317,
            "4318/tcp": 4318,
        }
        assert kwargs["environment"] == {"COLLECTOR_OTLP_ENABLED": "true"}
        assert kwargs["labels"] == {"vystak.service": "jaeger"}

    def test_provision_reuses_running_container(self, _patched_docker_errors):
        from vystak_provider_docker.nodes.jaeger import JaegerNode

        client = MagicMock()
        existing = MagicMock()
        existing.status = "running"
        client.containers.get.return_value = existing
        network = MagicMock()
        network.name = "vystak-net"
        context = {
            "network": ProvisionResult(name="network", success=True, info={"network": network})
        }
        node = JaegerNode(client)
        result = node.provision(context=context)
        assert result.success
        client.containers.run.assert_not_called()
        existing.start.assert_not_called()

    def test_provision_restarts_stopped_container(self, _patched_docker_errors):
        from vystak_provider_docker.nodes.jaeger import JaegerNode

        client = MagicMock()
        existing = MagicMock()
        existing.status = "exited"
        client.containers.get.return_value = existing
        network = MagicMock()
        network.name = "vystak-net"
        context = {
            "network": ProvisionResult(name="network", success=True, info={"network": network})
        }
        node = JaegerNode(client)
        result = node.provision(context=context)
        assert result.success
        existing.start.assert_called_once()
        client.containers.run.assert_not_called()

    def test_destroy_removes_container(self, _patched_docker_errors):
        from vystak_provider_docker.nodes.jaeger import JaegerNode

        client = MagicMock()
        container = MagicMock()
        client.containers.get.return_value = container
        JaegerNode(client).destroy()
        container.stop.assert_called_once()
        container.remove.assert_called_once()

    def test_destroy_not_found_is_noop(self, _patched_docker_errors):
        from vystak_provider_docker.nodes.jaeger import JaegerNode

        client = MagicMock()
        client.containers.get.side_effect = _patched_docker_errors("not found")
        JaegerNode(client).destroy()  # should not raise
