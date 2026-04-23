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
        *,
        extra_env: dict[str, str] | None = None,
    ):
        self._client = client
        self._channel = channel
        self._generated_code = generated_code
        self._target_hash = target_hash
        self._host_port = host_port
        self._container_port = container_port
        self._extra_env = extra_env or {}
        self._vault_secrets_volume: str | None = None

    def set_vault_context(self, *, secrets_volume_name: str) -> None:
        """Declare the per-principal secrets volume. Triggers entrypoint-shim
        injection + /shared mount during provision()."""
        self._vault_secrets_volume = secrets_volume_name

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

            # Vault context: emit shim + rewrite Dockerfile to run under ENTRYPOINT.
            # The channel plugin supplies the Dockerfile in generated_code.files,
            # so unlike DockerAgentNode we have to post-process it here.
            if self._vault_secrets_volume:
                from vystak_provider_docker.templates import generate_entrypoint_shim

                (build_dir / "entrypoint-shim.sh").write_text(generate_entrypoint_shim())
                dockerfile_path = build_dir / "Dockerfile"
                if dockerfile_path.exists():
                    original = dockerfile_path.read_text()
                    shim_block = (
                        "COPY entrypoint-shim.sh /vystak/entrypoint-shim.sh\n"
                        "RUN chmod +x /vystak/entrypoint-shim.sh\n"
                        'ENTRYPOINT ["/vystak/entrypoint-shim.sh"]\n'
                    )
                    # Insert shim immediately before the first CMD directive so
                    # ENTRYPOINT wraps the channel plugin's own CMD.
                    lines = original.splitlines(keepends=True)
                    inserted = False
                    rewritten: list[str] = []
                    for line in lines:
                        if not inserted and line.lstrip().startswith("CMD"):
                            rewritten.append(shim_block)
                            inserted = True
                        rewritten.append(line)
                    if not inserted:
                        # No CMD found — append shim + leave original intact.
                        rewritten.append(shim_block)
                    dockerfile_path.write_text("".join(rewritten))

            # Bundle unpublished vystak + vystak_transport_http + vystak_transport_nats
            # source trees onto the container's PYTHONPATH (via COPY . . in the Dockerfile).
            import vystak
            import vystak_transport_http
            import vystak_transport_nats

            for _mod in (vystak, vystak_transport_http, vystak_transport_nats):
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

            # Caller-supplied overrides (e.g. transport-plugin env contract)
            # take precedence over the defaults above.
            env.update(self._extra_env)

            volumes: dict[str, dict[str, str]] = {}
            if self._vault_secrets_volume:
                volumes[self._vault_secrets_volume] = {
                    "bind": "/shared",
                    "mode": "ro",
                }

            self._client.containers.run(
                image_tag,
                name=container_name,
                detach=True,
                ports={f"{self._container_port}/tcp": self._host_port},
                environment=env,
                volumes=volumes,
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
