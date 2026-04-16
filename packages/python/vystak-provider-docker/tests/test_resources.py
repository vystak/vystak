from unittest.mock import MagicMock, patch

import pytest
from vystak.schema.provider import Provider
from vystak.schema.resource import SessionStore


@pytest.fixture()
def mock_docker_client():
    with (
        patch("vystak_provider_docker.resources.docker") as mock_docker,
        patch("vystak_provider_docker.resources._wait_for_postgres"),
        patch("vystak_provider_docker.resources._sync_postgres_password"),
    ):
        client = MagicMock()
        mock_docker.from_env.return_value = client
        mock_docker.errors.NotFound = type("NotFound", (Exception,), {})
        yield client


@pytest.fixture()
def docker_provider():
    return Provider(name="docker", type="docker")


class TestProvisionPostgres:
    def test_creates_container(self, mock_docker_client, docker_provider, tmp_path):
        from vystak_provider_docker.resources import provision_resource

        mock_docker_client.containers.list.return_value = []
        network = MagicMock()
        network.name = "vystak-net"

        resource = SessionStore(name="sessions", provider=docker_provider, engine="postgres")
        secrets_path = tmp_path / ".vystak" / "secrets.json"

        result = provision_resource(mock_docker_client, resource, network, secrets_path)

        mock_docker_client.containers.run.assert_called_once()
        call_kwargs = mock_docker_client.containers.run.call_args
        assert call_kwargs[0][0] == "postgres:16-alpine"
        assert result["engine"] == "postgres"
        assert "connection_string" in result
        assert "vystak-resource-sessions" in result["connection_string"]

    def test_reuses_existing(self, mock_docker_client, docker_provider, tmp_path):
        from vystak_provider_docker.resources import provision_resource

        existing = MagicMock()
        existing.name = "vystak-resource-sessions"
        mock_docker_client.containers.list.return_value = [existing]
        network = MagicMock()

        resource = SessionStore(name="sessions", provider=docker_provider, engine="postgres")
        secrets_path = tmp_path / ".vystak" / "secrets.json"

        result = provision_resource(mock_docker_client, resource, network, secrets_path)
        mock_docker_client.containers.run.assert_not_called()
        assert result["engine"] == "postgres"


class TestProvisionSqlite:
    def test_creates_volume(self, mock_docker_client, docker_provider, tmp_path):
        from vystak_provider_docker.resources import provision_resource

        mock_docker_client.volumes.list.return_value = []
        network = MagicMock()

        resource = SessionStore(name="sessions", provider=docker_provider, engine="sqlite")
        secrets_path = tmp_path / ".vystak" / "secrets.json"

        result = provision_resource(mock_docker_client, resource, network, secrets_path)
        mock_docker_client.volumes.create.assert_called_once_with("vystak-data-sessions")
        assert result["engine"] == "sqlite"
        assert result["volume_name"] == "vystak-data-sessions"

    def test_reuses_existing_volume(self, mock_docker_client, docker_provider, tmp_path):
        from vystak_provider_docker.resources import provision_resource

        existing_vol = MagicMock()
        existing_vol.name = "vystak-data-sessions"
        mock_docker_client.volumes.list.return_value = [existing_vol]
        network = MagicMock()

        resource = SessionStore(name="sessions", provider=docker_provider, engine="sqlite")
        secrets_path = tmp_path / ".vystak" / "secrets.json"

        provision_resource(mock_docker_client, resource, network, secrets_path)
        mock_docker_client.volumes.create.assert_not_called()


class TestDestroyResource:
    def test_removes_container_keeps_volume(self, mock_docker_client):
        from vystak_provider_docker.resources import destroy_resource

        container = MagicMock()
        mock_docker_client.containers.list.return_value = [container]

        destroy_resource(mock_docker_client, "sessions")
        container.stop.assert_called_once()
        container.remove.assert_called_once()

    def test_no_container_no_error(self, mock_docker_client):
        from vystak_provider_docker.resources import destroy_resource

        mock_docker_client.containers.list.return_value = []
        destroy_resource(mock_docker_client, "sessions")


class TestGetConnectionString:
    def test_postgres(self, tmp_path):
        from vystak_provider_docker.resources import get_connection_string
        from vystak_provider_docker.secrets import save_secrets

        secrets_path = tmp_path / ".vystak" / "secrets.json"
        save_secrets(secrets_path, {"resources": {"sessions": {"password": "testpass"}}})

        conn = get_connection_string("sessions", "postgres", secrets_path)
        assert conn == "postgresql://vystak:testpass@vystak-resource-sessions:5432/vystak"

    def test_sqlite(self, tmp_path):
        from vystak_provider_docker.resources import get_connection_string

        secrets_path = tmp_path / ".vystak" / "secrets.json"
        conn = get_connection_string("sessions", "sqlite", secrets_path)
        assert conn == "/data/sessions.db"
