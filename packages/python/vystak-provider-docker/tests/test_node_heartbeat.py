"""Tests for DockerHeartbeatNode volume + port wiring (scheduler container)."""

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture()
def _patched_docker_errors():
    """Stub ``docker.errors.NotFound`` so the node can catch it off mocks."""
    fake_not_found = type("NotFound", (Exception,), {})
    with patch("docker.errors") as mock_errors:
        mock_errors.NotFound = fake_not_found
        yield fake_not_found


@pytest.fixture()
def _no_copytree(monkeypatch):
    """provision() bundles real vystak source trees via shutil.copytree —
    stub it out so these tests stay hermetic and fast."""
    import shutil

    monkeypatch.setattr(shutil, "copytree", lambda *a, **k: None)
    monkeypatch.setattr(shutil, "rmtree", lambda *a, **k: None)


def _make_context():
    network_info = MagicMock()
    network_info.name = "vystak-net"
    return {"network": MagicMock(info={"network": network_info})}


def _make_bundle():
    return type(
        "_GC",
        (),
        {"files": {"Dockerfile": "FROM python:3.11-slim\n"}},
    )()


class TestDockerHeartbeatNodeVolumeAndPorts:
    def test_creates_scheduler_volume_when_missing(
        self, tmp_path, monkeypatch, _patched_docker_errors, _no_copytree
    ):
        from vystak_provider_docker.nodes.heartbeat import DockerHeartbeatNode

        monkeypatch.chdir(tmp_path)
        client = MagicMock()
        client.containers.get.side_effect = _patched_docker_errors("no container")
        client.volumes.get.side_effect = _patched_docker_errors("no volume")

        node = DockerHeartbeatNode(client, _make_bundle())
        result = node.provision(_make_context())

        assert result.success, result.error
        client.volumes.get.assert_called_once_with("vystak-scheduler-data")
        client.volumes.create.assert_called_once_with("vystak-scheduler-data")

    def test_reuses_existing_scheduler_volume(
        self, tmp_path, monkeypatch, _patched_docker_errors, _no_copytree
    ):
        from vystak_provider_docker.nodes.heartbeat import DockerHeartbeatNode

        monkeypatch.chdir(tmp_path)
        client = MagicMock()
        client.containers.get.side_effect = _patched_docker_errors("no container")
        client.volumes.get.return_value = MagicMock()  # volume already exists

        node = DockerHeartbeatNode(client, _make_bundle())
        result = node.provision(_make_context())

        assert result.success, result.error
        client.volumes.create.assert_not_called()

    def test_run_binds_volume_and_port(
        self, tmp_path, monkeypatch, _patched_docker_errors, _no_copytree
    ):
        from vystak_provider_docker.nodes.heartbeat import DockerHeartbeatNode

        monkeypatch.chdir(tmp_path)
        client = MagicMock()
        client.containers.get.side_effect = _patched_docker_errors("no container")
        client.volumes.get.side_effect = _patched_docker_errors("no volume")

        node = DockerHeartbeatNode(client, _make_bundle())
        result = node.provision(_make_context())

        assert result.success, result.error
        _, kwargs = client.containers.run.call_args
        assert kwargs["volumes"] == {
            "vystak-scheduler-data": {"bind": "/data", "mode": "rw"}
        }
        assert kwargs["ports"] == {"8081/tcp": ("127.0.0.1", 9797)}

    def test_destroy_keeps_the_volume(self, _patched_docker_errors):
        from vystak_provider_docker.nodes.heartbeat import DockerHeartbeatNode

        client = MagicMock()
        container = MagicMock()
        client.containers.get.return_value = container

        node = DockerHeartbeatNode(client, _make_bundle())
        node.destroy()

        container.stop.assert_called_once()
        container.remove.assert_called_once()
        client.volumes.get.assert_not_called()
        client.volumes.remove.assert_not_called()
