"""OtelLgtmNode — runs grafana/otel-lgtm as the shared telemetry sink.

Single container provisioned per-platform when any agent or channel
has telemetry enabled. The image bundles Grafana + Tempo (traces) +
Mimir (metrics) + a pre-wired OTLP receiver, so it accepts both
traces and metrics on the same endpoint and renders them in one UI.

Listens on:

* 4317 (OTLP gRPC) — what agents + channels export to
* 4318 (OTLP HTTP) — alternative export path (not used by default)
* 3000 (Grafana UI) — exposed on the host as 13000 (3000 collides
  with common dev servers like Next.js / Docusaurus)

Containers reach the collector via the internal Docker DNS name
``vystak-otel:4317``. The host can browse the Grafana UI at
``http://localhost:13000`` (anonymous viewer access is enabled by
default in the upstream image).
"""

from vystak.provisioning.health import HealthCheck, NoopHealthCheck
from vystak.provisioning.node import Provisionable, ProvisionResult


class OtelLgtmNode(Provisionable):
    """Provisions a grafana/otel-lgtm container on the shared vystak-net.

    Other containers reach the OTLP gRPC receiver at
    ``vystak-otel:4317``. Grafana UI is on the host at
    ``http://localhost:3000``.
    """

    IMAGE = "grafana/otel-lgtm:0.11.10"
    CONTAINER_NAME = "vystak-otel"

    def __init__(self, client):
        self._client = client

    @property
    def name(self) -> str:
        return "otel-lgtm"

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
                # Container's 3000 → host 13000 (avoids clash with
                # Next.js / Docusaurus dev servers also defaulting to
                # 3000). 4317/4318 internal only.
                ports={
                    "3000/tcp": 13000,
                    "4317/tcp": 4317,
                    "4318/tcp": 4318,
                },
                labels={"vystak.service": "otel-lgtm"},
            )
        return ProvisionResult(
            name=self.name,
            success=True,
            info={
                "otlp_grpc": f"http://{self.CONTAINER_NAME}:4317",
                "otlp_http": f"http://{self.CONTAINER_NAME}:4318",
                "ui": "http://localhost:13000",
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
