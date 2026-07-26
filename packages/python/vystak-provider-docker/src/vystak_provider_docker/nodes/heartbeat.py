"""DockerHeartbeatNode — builds and runs the vystak-heartbeat container."""

import shutil
from pathlib import Path

import docker.errors
from vystak.providers.base import FileBundle
from vystak.provisioning.health import HealthCheck, NoopHealthCheck
from vystak.provisioning.node import Provisionable, ProvisionResult

CONTAINER_NAME = "vystak-heartbeat"
IMAGE_TAG = "vystak-heartbeat:latest"
SCHEDULER_VOLUME = "vystak-scheduler-data"


class DockerHeartbeatNode(Provisionable):
    """Builds a Docker image and runs the vystak-heartbeat container on vystak-net.

    Provisioned at most once per platform — the caller (DockerProvider) is
    responsible for ensuring this node is only added when at least one agent
    carries a ``heartbeat`` declaration.
    """

    def __init__(
        self,
        client,
        generated_code: FileBundle,
        *,
        extra_env: dict[str, str] | None = None,
    ):
        self._client = client
        self._generated_code = generated_code
        self._extra_env = extra_env or {}

    @property
    def name(self) -> str:
        return "heartbeat"

    @property
    def depends_on(self) -> list[str]:
        return ["network"]

    def provision(self, context: dict) -> ProvisionResult:
        try:
            network = context["network"].info["network"]

            # Remove any stale container before rebuilding.
            try:
                existing = self._client.containers.get(CONTAINER_NAME)
                existing.stop()
                existing.remove()
            except docker.errors.NotFound:
                pass

            build_dir = Path(".vystak") / "heartbeat"
            build_dir.mkdir(parents=True, exist_ok=True)
            for filename, content in self._generated_code.files.items():
                (build_dir / filename).write_text(content)

            # Bundle unpublished vystak source trees so `COPY . .` in the
            # Dockerfile picks them up without a PyPI release.  Mirror the
            # same set as DockerChannelNode, plus vystak_heartbeat itself.
            import vystak
            import vystak_channel_runtime
            import vystak_heartbeat
            import vystak_transport_http
            import vystak_transport_nats

            for _mod in [
                vystak,
                vystak_channel_runtime,
                vystak_heartbeat,
                vystak_transport_http,
                vystak_transport_nats,
            ]:
                _src = Path(_mod.__file__).parent
                _dst = build_dir / _src.name
                if _dst.exists():
                    shutil.rmtree(_dst)
                shutil.copytree(_src, _dst)

            self._client.images.build(path=str(build_dir), tag=IMAGE_TAG)

            # Ensure the scheduler's SQLite store volume exists — persists
            # across redeploys; destroy() intentionally leaves it in place.
            try:
                self._client.volumes.get(SCHEDULER_VOLUME)
            except docker.errors.NotFound:
                self._client.volumes.create(SCHEDULER_VOLUME)

            env: dict[str, str] = {}
            # Caller-supplied overrides (e.g. OTel env vars).
            env.update(self._extra_env)

            self._client.containers.run(
                IMAGE_TAG,
                name=CONTAINER_NAME,
                detach=True,
                network=network.name,
                environment=env,
                volumes={SCHEDULER_VOLUME: {"bind": "/data", "mode": "rw"}},
                ports={"8081/tcp": ("127.0.0.1", 9797)},
                labels={"vystak.service": "heartbeat"},
            )

            return ProvisionResult(
                name=self.name,
                success=True,
                info={"container_name": CONTAINER_NAME},
            )
        except Exception as e:
            return ProvisionResult(name=self.name, success=False, error=str(e))

    def health_check(self) -> HealthCheck:
        return NoopHealthCheck()

    def destroy(self) -> None:
        try:
            c = self._client.containers.get(CONTAINER_NAME)
            c.stop()
            c.remove()
        except docker.errors.NotFound:
            pass
