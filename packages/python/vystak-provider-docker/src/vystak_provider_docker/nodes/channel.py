"""DockerChannelNode — builds and runs a channel as a Docker container."""

import os
import shutil
from pathlib import Path

import docker.errors
from vystak.providers.base import GeneratedCode
from vystak.provisioning.health import HealthCheck, NoopHealthCheck
from vystak.provisioning.node import Provisionable, ProvisionResult
from vystak.schema.channel import Channel


class DockerChannelNode(Provisionable):
    """Builds a Docker image and runs a channel container on vystak-net."""

    def __init__(
        self,
        client,
        channel: Channel,
        generated_code: GeneratedCode,
        target_hash: str,
        host_port: int = 8080,
        container_port: int = 8080,
    ):
        self._client = client
        self._channel = channel
        self._generated_code = generated_code
        self._target_hash = target_hash
        self._host_port = host_port
        self._container_port = container_port

    @property
    def name(self) -> str:
        return f"channel:{self._channel.name}"

    @property
    def depends_on(self) -> list[str]:
        return ["network"]

    def _container_name(self) -> str:
        return f"vystak-channel-{self._channel.name}"

    def provision(self, context: dict) -> ProvisionResult:
        try:
            container_name = self._container_name()
            network = context["network"].info["network"]

            try:
                existing = self._client.containers.get(container_name)
                existing.stop()
                existing.remove()
            except docker.errors.NotFound:
                pass

            build_dir = Path(".vystak") / "channels" / self._channel.name
            build_dir.mkdir(parents=True, exist_ok=True)
            for filename, content in self._generated_code.files.items():
                (build_dir / filename).write_text(content)

            # Bundle unpublished vystak + vystak_transport_http source trees
            # onto the container's PYTHONPATH (via COPY . . in the Dockerfile).
            import vystak
            import vystak_transport_http

            for _mod in (vystak, vystak_transport_http):
                _src = Path(_mod.__file__).parent
                _dst = build_dir / _src.name
                if _dst.exists():
                    shutil.rmtree(_dst)
                shutil.copytree(_src, _dst)

            image_tag = f"{container_name}:latest"
            self._client.images.build(path=str(build_dir), tag=image_tag)

            env = {
                "PORT": str(self._container_port),
            }
            for secret in self._channel.secrets:
                value = os.environ.get(secret.name)
                if value:
                    env[secret.name] = value

            self._client.containers.run(
                image_tag,
                name=container_name,
                detach=True,
                ports={f"{self._container_port}/tcp": self._host_port},
                environment=env,
                network=network.name,
                labels={
                    "vystak.channel.hash": self._target_hash,
                    "vystak.channel": self._channel.name,
                    "vystak.channel.type": self._channel.type.value,
                },
            )

            container = self._client.containers.get(container_name)
            port_info = container.ports.get(f"{self._container_port}/tcp")
            actual_port = port_info[0]["HostPort"] if port_info else str(self._host_port)
            url = f"http://localhost:{actual_port}"

            return ProvisionResult(
                name=self.name,
                success=True,
                info={
                    "url": url,
                    "container_name": container_name,
                    "port": actual_port,
                },
            )
        except Exception as e:
            return ProvisionResult(name=self.name, success=False, error=str(e))

    def health_check(self) -> HealthCheck:
        return NoopHealthCheck()

    def destroy(self) -> None:
        container_name = self._container_name()
        try:
            container = self._client.containers.get(container_name)
            container.stop()
            container.remove()
        except docker.errors.NotFound:
            pass
