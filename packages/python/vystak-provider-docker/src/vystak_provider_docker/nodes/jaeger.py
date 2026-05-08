"""JaegerNode — runs jaegertracing/all-in-one as a shared collector container.

Single shared container provisioned per-platform when any agent or
channel has telemetry enabled. Listens on:

* 4317 (OTLP gRPC) — what agents + channels export to
* 4318 (OTLP HTTP) — alternative export path (not used by default)
* 16686 (UI) — exposed to the host so users can browse traces

Containers reach the collector via the internal Docker DNS name
``vystak-jaeger:4317``. The host can browse the UI at
``http://localhost:16686``.
"""

from vystak.provisioning.health import HealthCheck, NoopHealthCheck
from vystak.provisioning.node import Provisionable, ProvisionResult


class JaegerNode(Provisionable):
    """Provisions a Jaeger all-in-one container on the shared vystak-net.

    Other containers reach the collector via ``vystak-jaeger:4317``
    (OTLP gRPC). The Jaeger UI is exposed on the host at
    ``http://localhost:16686`` for trace inspection.
    """

    IMAGE = "jaegertracing/all-in-one:1.64"
    CONTAINER_NAME = "vystak-jaeger"

    def __init__(self, client):
        self._client = client

    @property
    def name(self) -> str:
        return "jaeger"

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
                network=network.name,
                # 16686 to host for UI access; 4317/4318 internal only.
                ports={
                    "16686/tcp": 16686,
                    "4317/tcp": 4317,
                    "4318/tcp": 4318,
                },
                environment={"COLLECTOR_OTLP_ENABLED": "true"},
                labels={"vystak.service": "jaeger"},
            )
        return ProvisionResult(
            name=self.name,
            success=True,
            info={
                "otlp_grpc": f"http://{self.CONTAINER_NAME}:4317",
                "otlp_http": f"http://{self.CONTAINER_NAME}:4318",
                "ui": "http://localhost:16686",
            },
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
