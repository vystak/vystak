"""Resource provisioning for Docker — Postgres containers and SQLite volumes."""

from pathlib import Path

import docker
import docker.errors

from vystak.schema.resource import Resource
from vystak_provider_docker.secrets import get_resource_password


def _resource_container_name(resource_name: str) -> str:
    return f"vystak-resource-{resource_name}"


def _volume_name(resource_name: str) -> str:
    return f"vystak-data-{resource_name}"


def provision_resource(
    client, resource: Resource, network, secrets_path: Path
) -> dict:
    """Provision backing infrastructure for a resource. Returns connection info."""
    if resource.engine == "postgres":
        return _provision_postgres(client, resource, network, secrets_path)
    elif resource.engine == "sqlite":
        return _provision_sqlite(client, resource, secrets_path)
    else:
        raise ValueError(f"Unsupported session store engine: {resource.engine}")


def _wait_for_postgres(client, container_name: str, timeout: int = 60) -> None:
    """Wait until postgres is ready to accept connections."""
    import time
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            container = client.containers.get(container_name)
            result = container.exec_run(
                ["pg_isready", "-U", "vystak", "-d", "vystak"],
                demux=False,
            )
            if result.exit_code == 0:
                return
        except Exception:
            pass
        time.sleep(1)
    raise TimeoutError(f"Postgres container {container_name} did not become ready within {timeout}s")


def _sync_postgres_password(client, container_name: str, password: str) -> None:
    """Ensure the postgres user password matches the stored secret."""
    try:
        container = client.containers.get(container_name)
        sql = f"ALTER USER vystak WITH PASSWORD '{password}';"
        container.exec_run(
            ["psql", "-U", "vystak", "-d", "vystak", "-c", sql],
            demux=False,
        )
    except Exception:
        pass


def _provision_postgres(client, resource: Resource, network, secrets_path: Path) -> dict:
    container_name = _resource_container_name(resource.name)
    volume_name = _volume_name(resource.name)

    password = get_resource_password(resource.name, secrets_path)

    existing = client.containers.list(filters={"name": container_name}, all=True)
    if existing:
        container = existing[0]
        if container.status != "running":
            container.start()
        _wait_for_postgres(client, container_name)
        _sync_postgres_password(client, container_name, password)
        return {
            "engine": "postgres",
            "container_name": container_name,
            "connection_string": _postgres_conn_string(resource.name, password),
        }

    client.containers.run(
        "postgres:16-alpine",
        name=container_name,
        detach=True,
        environment={
            "POSTGRES_DB": "vystak",
            "POSTGRES_USER": "vystak",
            "POSTGRES_PASSWORD": password,
        },
        volumes={volume_name: {"bind": "/var/lib/postgresql/data", "mode": "rw"}},
        network=network.name,
        labels={
            "vystak.resource": resource.name,
            "vystak.engine": "postgres",
        },
    )

    _wait_for_postgres(client, container_name)

    return {
        "engine": "postgres",
        "container_name": container_name,
        "connection_string": _postgres_conn_string(resource.name, password),
    }


def _provision_sqlite(client, resource: Resource, secrets_path: Path) -> dict:
    volume_name = _volume_name(resource.name)
    existing = client.volumes.list(filters={"name": volume_name})
    if not existing:
        client.volumes.create(volume_name)

    return {
        "engine": "sqlite",
        "volume_name": volume_name,
        "connection_string": f"/data/{resource.name}.db",
    }


def destroy_resource(client, resource_name: str) -> None:
    """Stop and remove a resource container. Keeps volumes."""
    container_name = _resource_container_name(resource_name)
    containers = client.containers.list(filters={"name": container_name}, all=True)
    for container in containers:
        container.stop()
        container.remove()


def get_connection_string(resource_name: str, engine: str, secrets_path: Path) -> str:
    """Get the connection string for a provisioned resource."""
    if engine == "postgres":
        password = get_resource_password(resource_name, secrets_path)
        return _postgres_conn_string(resource_name, password)
    elif engine == "sqlite":
        return f"/data/{resource_name}.db"
    else:
        raise ValueError(f"Unsupported engine: {engine}")


def _postgres_conn_string(resource_name: str, password: str) -> str:
    host = _resource_container_name(resource_name)
    return f"postgresql://vystak:{password}@{host}:5432/vystak"
