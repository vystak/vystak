"""NatsServerNode — runs nats:2.10-alpine with JetStream as a container."""

from vystak.provisioning.health import HealthCheck, NoopHealthCheck
from vystak.provisioning.node import Provisionable, ProvisionResult


class NatsServerNode(Provisionable):
    """Provisions a NATS JetStream server container on the shared vystak-net.

    The container listens on ``nats://vystak-nats:4222`` and persists
    JetStream state to the ``vystak-nats-data`` volume.
    """

    IMAGE = "nats:2.10-alpine"
    CONTAINER_NAME = "vystak-nats"

    def __init__(self, client):
        self._client = client

    @property
    def name(self) -> str:
        return "nats-server"

    @property
    def depends_on(self) -> list[str]:
        return ["network"]

    def provision(self, context: dict) -> ProvisionResult:
        import docker.errors

        network = context["network"].info["network"]
        try:
            existing = self._client.containers.get(self.CONTAINER_NAME)
            if existing.status != "running":
                existing.start()
        except docker.errors.NotFound:
            self._client.images.pull(self.IMAGE)
            self._client.containers.run(
                self.IMAGE,
                name=self.CONTAINER_NAME,
                detach=True,
                command=["-js", "-sd", "/data"],
                network=network.name,
                ports={"4222/tcp": 4222},
                volumes={"vystak-nats-data": {"bind": "/data", "mode": "rw"}},
                labels={"vystak.service": "nats"},
            )
        return ProvisionResult(
            name=self.name,
            success=True,
            info={"url": f"nats://{self.CONTAINER_NAME}:4222"},
        )

    def health_check(self) -> HealthCheck:
        return NoopHealthCheck()

    def destroy(self) -> None:
        import docker.errors

        try:
            c = self._client.containers.get(self.CONTAINER_NAME)
            c.stop()
            c.remove()
        except docker.errors.NotFound:
            pass
