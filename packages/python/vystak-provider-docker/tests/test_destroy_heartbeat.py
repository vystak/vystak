"""Tests for DockerProvider.destroy_heartbeat()."""

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture()
def _patched_docker_errors():
    """Stub ``docker.errors.NotFound`` so the provider can catch it off mocks."""
    fake_not_found = type("NotFound", (Exception,), {})
    with patch("docker.errors") as mock_errors:
        mock_errors.NotFound = fake_not_found
        yield fake_not_found


def test_destroy_heartbeat_stops_and_removes_container(_patched_docker_errors):
    from vystak_provider_docker.provider import DockerProvider

    provider = DockerProvider.__new__(DockerProvider)
    provider._client = MagicMock()
    container = MagicMock()
    provider._client.containers.get.return_value = container

    provider.destroy_heartbeat()

    provider._client.containers.get.assert_called_once_with("vystak-heartbeat")
    container.stop.assert_called_once()
    container.remove.assert_called_once()


def test_destroy_heartbeat_not_found_is_noop(_patched_docker_errors):
    """Calling destroy_heartbeat when no container exists must not raise."""
    from vystak_provider_docker.provider import DockerProvider

    provider = DockerProvider.__new__(DockerProvider)
    provider._client = MagicMock()
    provider._client.containers.get.side_effect = _patched_docker_errors(
        "not found",
    )

    provider.destroy_heartbeat()  # should not raise
