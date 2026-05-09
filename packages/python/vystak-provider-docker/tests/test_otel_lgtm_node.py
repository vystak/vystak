"""Tests for OtelLgtmNode — the shared OTLP collector + Grafana stack."""

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


class TestOtelLgtmNode:
    def test_name_and_depends_on(self):
        from vystak_provider_docker.nodes.otel_lgtm import OtelLgtmNode

        node = OtelLgtmNode(MagicMock())
        assert node.name == "otel-lgtm"
        assert node.depends_on == ["network"]

    def test_provision_creates_container(self, _patched_docker_errors):
        from vystak_provider_docker.nodes.otel_lgtm import OtelLgtmNode

        client = MagicMock()
        client.containers.get.side_effect = _patched_docker_errors("not found")
        network = MagicMock()
        network.name = "vystak-net"
        context = {
            "network": ProvisionResult(name="network", success=True, info={"network": network})
        }
        node = OtelLgtmNode(client)
        result = node.provision(context=context)
        assert result.success
        # OTLP endpoints + Grafana UI exposed in result info.
        assert result.info["otlp_grpc"] == "http://vystak-otel:4317"
        assert result.info["otlp_http"] == "http://vystak-otel:4318"
        assert result.info["ui"] == "http://localhost:13000"
        client.images.pull.assert_called_once_with(OtelLgtmNode.IMAGE)
        client.containers.run.assert_called_once()
        _, kwargs = client.containers.run.call_args
        assert kwargs["name"] == "vystak-otel"
        assert kwargs["network"] == "vystak-net"
        # 3000 published to the host; 4317/4318 internal-only by Docker default.
        assert kwargs["ports"] == {
            "3000/tcp": 13000,
            "4317/tcp": 4317,
            "4318/tcp": 4318,
        }
        assert kwargs["labels"] == {"vystak.service": "otel-lgtm"}

    def test_provision_reuses_running_container(self, _patched_docker_errors):
        from vystak_provider_docker.nodes.otel_lgtm import OtelLgtmNode

        client = MagicMock()
        existing = MagicMock()
        existing.status = "running"
        client.containers.get.return_value = existing
        network = MagicMock()
        network.name = "vystak-net"
        context = {
            "network": ProvisionResult(name="network", success=True, info={"network": network})
        }
        node = OtelLgtmNode(client)
        result = node.provision(context=context)
        assert result.success
        client.containers.run.assert_not_called()
        existing.start.assert_not_called()

    def test_provision_restarts_stopped_container(self, _patched_docker_errors):
        from vystak_provider_docker.nodes.otel_lgtm import OtelLgtmNode

        client = MagicMock()
        existing = MagicMock()
        existing.status = "exited"
        client.containers.get.return_value = existing
        network = MagicMock()
        network.name = "vystak-net"
        context = {
            "network": ProvisionResult(name="network", success=True, info={"network": network})
        }
        node = OtelLgtmNode(client)
        result = node.provision(context=context)
        assert result.success
        existing.start.assert_called_once()
        client.containers.run.assert_not_called()

    def test_destroy_removes_container(self, _patched_docker_errors):
        from vystak_provider_docker.nodes.otel_lgtm import OtelLgtmNode

        client = MagicMock()
        container = MagicMock()
        client.containers.get.return_value = container
        OtelLgtmNode(client).destroy()
        container.stop.assert_called_once()
        container.remove.assert_called_once()

    def test_destroy_not_found_is_noop(self, _patched_docker_errors):
        from vystak_provider_docker.nodes.otel_lgtm import OtelLgtmNode

        client = MagicMock()
        client.containers.get.side_effect = _patched_docker_errors("not found")
        OtelLgtmNode(client).destroy()  # should not raise
