"""Resource provisioning for Docker — Postgres containers and SQLite volumes."""

from pathlib import Path

import docker
import docker.errors

from agentstack.schema.resource import Resource
from agentstack_provider_docker.secrets import get_resource_password


def _resource_container_name(resource_name: str) -> str:
    return f"agentstack-resource-{resource_name}"


def _volume_name(resource_name: str) -> str:
    return f"agentstack-data-{resource_name}"


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


def _provision_postgres(client, resource: Resource, network, secrets_path: Path) -> dict:
    container_name = _resource_container_name(resource.name)
    volume_name = _volume_name(resource.name)

    existing = client.containers.list(filters={"name": container_name}, all=True)
    if existing:
        password = get_resource_password(resource.name, secrets_path)
        return {
            "engine": "postgres",
            "container_name": container_name,
            "connection_string": _postgres_conn_string(resource.name, password),
        }

    password = get_resource_password(resource.name, secrets_path)
    client.containers.run(
        "postgres:16-alpine",
        name=container_name,
        detach=True,
        environment={
            "POSTGRES_DB": "agentstack",
            "POSTGRES_USER": "agentstack",
            "POSTGRES_PASSWORD": password,
        },
        volumes={volume_name: {"bind": "/var/lib/postgresql/data", "mode": "rw"}},
        network=network.name,
        labels={
            "agentstack.resource": resource.name,
            "agentstack.engine": "postgres",
        },
    )

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
    return f"postgresql://agentstack:{password}@{host}:5432/agentstack"
