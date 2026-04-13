"""DockerServiceNode — provisions backing services (postgres, sqlite, etc.)."""

from pathlib import Path

from agentstack.provisioning.health import (
    CommandHealthCheck,
    HealthCheck,
    NoopHealthCheck,
)
from agentstack.provisioning.node import Provisionable, ProvisionResult
from agentstack_provider_docker.secrets import get_resource_password


def _resource_container_name(resource_name: str) -> str:
    return f"agentstack-resource-{resource_name}"


def _volume_name(resource_name: str) -> str:
    return f"agentstack-data-{resource_name}"


def _postgres_conn_string(resource_name: str, password: str) -> str:
    host = _resource_container_name(resource_name)
    return f"postgresql://agentstack:{password}@{host}:5432/agentstack"


class DockerServiceNode(Provisionable):
    """Provisions a backing service (postgres container, sqlite volume, etc.)."""

    def __init__(self, client, service, secrets_path: Path):
        self._client = client
        self._service = service
        self._secrets_path = secrets_path
        self._container = None  # Set after provisioning postgres

    @property
    def name(self) -> str:
        return self._service.name

    @property
    def depends_on(self) -> list[str]:
        deps = list(self._service.depends_on)
        if "network" not in deps:
            deps.append("network")
        return deps

    def provision(self, context: dict) -> ProvisionResult:
        engine = self._service.engine
        if engine == "postgres":
            return self._provision_postgres(context)
        elif engine == "sqlite":
            return self._provision_sqlite(context)
        else:
            return ProvisionResult(
                name=self.name,
                success=False,
                error=f"Unsupported engine: {engine}",
            )

    def _provision_postgres(self, context: dict) -> ProvisionResult:
        container_name = _resource_container_name(self._service.name)
        volume_name = _volume_name(self._service.name)
        password = get_resource_password(self._service.name, self._secrets_path)
        network = context["network"].info["network"]

        existing = self._client.containers.list(
            filters={"name": container_name}, all=True
        )
        if existing:
            container = existing[0]
            if container.status != "running":
                container.start()
            self._container = container
            # Sync password for existing volumes that may have old passwords
            self._sync_postgres_password(container, password)
            return ProvisionResult(
                name=self.name,
                success=True,
                info={
                    "engine": "postgres",
                    "container_name": container_name,
                    "connection_string": _postgres_conn_string(
                        self._service.name, password
                    ),
                },
            )

        container = self._client.containers.run(
            "postgres:16-alpine",
            name=container_name,
            detach=True,
            environment={
                "POSTGRES_DB": "agentstack",
                "POSTGRES_USER": "agentstack",
                "POSTGRES_PASSWORD": password,
            },
            volumes={
                volume_name: {"bind": "/var/lib/postgresql/data", "mode": "rw"}
            },
            network=network.name,
            labels={
                "agentstack.resource": self._service.name,
                "agentstack.engine": "postgres",
            },
        )
        self._container = container

        return ProvisionResult(
            name=self.name,
            success=True,
            info={
                "engine": "postgres",
                "container_name": container_name,
                "connection_string": _postgres_conn_string(
                    self._service.name, password
                ),
            },
        )

    def _provision_sqlite(self, context: dict) -> ProvisionResult:
        volume_name = _volume_name(self._service.name)
        existing = self._client.volumes.list(filters={"name": volume_name})
        if not existing:
            self._client.volumes.create(volume_name)

        return ProvisionResult(
            name=self.name,
            success=True,
            info={
                "engine": "sqlite",
                "volume_name": volume_name,
                "connection_string": f"/data/{self._service.name}.db",
            },
        )

    @staticmethod
    def _sync_postgres_password(container, password: str) -> None:
        """Ensure the postgres user password matches the stored secret."""
        try:
            sql = f"ALTER USER agentstack WITH PASSWORD '{password}';"
            container.exec_run(
                ["psql", "-U", "agentstack", "-d", "agentstack", "-c", sql],
                demux=False,
            )
        except Exception:
            pass

    def health_check(self) -> HealthCheck:
        if self._service.engine == "postgres" and self._container is not None:
            return CommandHealthCheck(
                self._container,
                ["pg_isready", "-U", "agentstack", "-d", "agentstack"],
            )
        return NoopHealthCheck()

    def destroy(self) -> None:
        """Stop and remove the service container. Keeps volumes."""
        container_name = _resource_container_name(self._service.name)
        containers = self._client.containers.list(
            filters={"name": container_name}, all=True
        )
        for container in containers:
            container.stop()
            container.remove()
