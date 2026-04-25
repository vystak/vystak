"""Tests for DockerChannelNode — volume mounts and state persistence."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from vystak.schema.channel import Channel
from vystak.schema.common import ChannelType
from vystak.schema.platform import Platform
from vystak.schema.provider import Provider
from vystak_provider_docker.nodes.channel import DockerChannelNode


@pytest.fixture()
def mock_docker_errors():
    """Return a dict of docker.errors exception types for use in tests."""

    class NotFound(Exception):
        pass

    class DockerException(Exception):
        pass

    return {"NotFound": NotFound, "DockerException": DockerException}


def _make_channel(channel_type: ChannelType, name: str = "slack-main") -> Channel:
    docker_provider = Provider(name="docker", type="docker")
    platform = Platform(name="local", type="docker", provider=docker_provider)
    return Channel(
        name=name,
        type=channel_type,
        platform=platform,
        config={"port": 8080},
    )


def _make_node(client, channel: Channel) -> DockerChannelNode:
    code = type(
        "_GC",
        (),
        {
            "files": {
                "server.py": "print('ok')",
                "Dockerfile": "FROM python:3.11-slim\nCMD [\"python\", \"server.py\"]\n",
                "requirements.txt": "",
            },
            "entrypoint": "server.py",
        },
    )()
    return DockerChannelNode(client, channel, code, target_hash="testhash")


class TestSlackStateVolumeMount:
    """DockerChannelNode mounts a named state volume at /data for Slack channels."""

    def test_slack_channel_mounts_state_volume(self, tmp_path, monkeypatch):
        """containers.run is called with the state volume bound to /data."""
        monkeypatch.chdir(tmp_path)

        import docker as _docker

        client = MagicMock()
        channel = _make_channel(ChannelType.SLACK)

        # First containers.get() — existing container check — raises NotFound.
        # Second containers.get() — after containers.run — returns new container.
        new_container = MagicMock()
        new_container.ports = {"8080/tcp": [{"HostPort": "8080"}]}
        client.containers.get.side_effect = [
            _docker.errors.NotFound("x"),
            new_container,
        ]

        # Volume already exists
        client.volumes.get.return_value = MagicMock()

        node = _make_node(client, channel)
        network_mock = MagicMock()
        network_mock.name = "vystak-net"
        context = {"network": MagicMock(info={"network": network_mock})}

        # Patch shutil.copytree to avoid filesystem side-effects and patch
        # docker.images.build (already on the mock client).
        with patch("shutil.copytree"):
            result = node.provision(context)

        assert result.success, result.error

        _, run_kwargs = client.containers.run.call_args
        volumes = run_kwargs.get("volumes", {})
        state_volume_name = "vystak-slack-main-state"
        assert state_volume_name in volumes, (
            f"Expected '{state_volume_name}' in volumes dict. Got: {list(volumes.keys())}"
        )
        assert volumes[state_volume_name]["bind"] == "/data"
        assert volumes[state_volume_name]["mode"] == "rw"

    def test_slack_channel_creates_volume_if_missing(self, tmp_path, monkeypatch):
        """When the state volume doesn't exist yet, volumes.create is called."""
        monkeypatch.chdir(tmp_path)

        import docker as _docker

        client = MagicMock()
        channel = _make_channel(ChannelType.SLACK)

        new_container = MagicMock()
        new_container.ports = {"8080/tcp": [{"HostPort": "8080"}]}
        client.containers.get.side_effect = [
            _docker.errors.NotFound("x"),
            new_container,
        ]

        # Volume does NOT exist — volumes.get raises NotFound
        client.volumes.get.side_effect = _docker.errors.NotFound("not found")

        node = _make_node(client, channel)
        network_mock = MagicMock()
        network_mock.name = "vystak-net"
        context = {"network": MagicMock(info={"network": network_mock})}

        with patch("shutil.copytree"):
            result = node.provision(context)

        assert result.success, result.error
        client.volumes.create.assert_called_once_with(name="vystak-slack-main-state")

    def test_non_slack_channel_does_not_mount_state_volume(self, tmp_path, monkeypatch):
        """API-type channels do NOT get the state volume."""
        monkeypatch.chdir(tmp_path)

        import docker as _docker

        client = MagicMock()
        channel = _make_channel(ChannelType.API, name="api-main")

        new_container = MagicMock()
        new_container.ports = {"8080/tcp": [{"HostPort": "8080"}]}
        client.containers.get.side_effect = [
            _docker.errors.NotFound("x"),
            new_container,
        ]

        node = _make_node(client, channel)
        network_mock = MagicMock()
        network_mock.name = "vystak-net"
        context = {"network": MagicMock(info={"network": network_mock})}

        with patch("shutil.copytree"):
            result = node.provision(context)

        assert result.success, result.error

        _, run_kwargs = client.containers.run.call_args
        volumes = run_kwargs.get("volumes", {})
        state_volume_name = "vystak-api-main-state"
        assert state_volume_name not in volumes, (
            "API channel should not get a state volume"
        )
        # volumes.get/create should NOT be called for state volume on non-Slack
        client.volumes.create.assert_not_called()
