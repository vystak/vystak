"""DockerAgentNode — builds and runs an agent as a Docker container."""

import os
import shutil
from pathlib import Path

import docker.errors
from vystak.providers.base import DeployPlan, GeneratedCode
from vystak.provisioning.health import HealthCheck, NoopHealthCheck
from vystak.provisioning.node import Provisionable, ProvisionResult
from vystak.schema.agent import Agent


class DockerAgentNode(Provisionable):
    """Builds a Docker image and runs an agent container."""

    def __init__(
        self,
        client,
        agent: Agent,
        generated_code: GeneratedCode,
        plan: DeployPlan,
        *,
        peer_routes_json: str = "{}",
        extra_env: dict[str, str] | None = None,
    ):
        self._client = client
        self._agent = agent
        self._generated_code = generated_code
        self._plan = plan
        self._peer_routes_json = peer_routes_json
        self._extra_env = extra_env or {}
        self._vault_secrets_volume: str | None = None
        self._workspace_host: str | None = None
        self._default_path_env: dict[str, str] | None = None
        self._default_path_ssh_host_dir: str | None = None

    def set_vault_context(self, *, secrets_volume_name: str) -> None:
        """Declare the per-principal secrets volume. Triggers entrypoint-shim
        injection + /shared mount during provision()."""
        self._vault_secrets_volume = secrets_volume_name

    def set_default_path_context(
        self,
        *,
        env: dict[str, str],
        ssh_host_dir: str | None = None,
    ) -> None:
        """Declare the default (no-Vault) delivery context.

        ``env`` is added directly to the container environment (equivalent to
        ``--env-file``). ``ssh_host_dir`` is the host directory produced by
        ``WorkspaceSshKeygenNode`` — individual files are bind-mounted into
        the container's ``/shared/ssh/`` paths so existing agent-side code
        (which reads ``/vystak/ssh/*`` via the symlink) works unchanged.
        """
        self._default_path_env = dict(env)
        self._default_path_ssh_host_dir = ssh_host_dir

    def set_workspace_context(self, *, workspace_host: str) -> None:
        """Declare that this agent should RPC into a workspace container
        over SSH.

        Sets VYSTAK_WORKSPACE_HOST in the container env so agent-side code
        can resolve the workspace's internal DNS name. The SSH key material
        is rendered by the agent's vault-agent sidecar into /shared/ssh/
        (same per-principal secrets volume that carries secrets.env); the
        Dockerfile emitted here symlinks /vystak/ssh → /shared/ssh so
        agent-side code can reference the canonical /vystak/ssh/* paths.
        """
        self._workspace_host = workspace_host

    @property
    def name(self) -> str:
        return f"agent:{self._agent.name}"

    @property
    def depends_on(self) -> list[str]:
        deps = ["network"]
        if self._agent.sessions is not None:
            deps.append(self._agent.sessions.name)
        if self._agent.memory is not None:
            deps.append(self._agent.memory.name)
        for svc in self._agent.services:
            deps.append(svc.name)
        return deps

    def _container_name(self) -> str:
        return f"vystak-{self._agent.name}"

    def provision(self, context: dict) -> ProvisionResult:
        try:
            container_name = self._container_name()
            network = context["network"].info["network"]

            # Stop existing container
            try:
                existing = self._client.containers.get(container_name)
                existing.stop()
                existing.remove()
            except docker.errors.NotFound:
                pass

            # Write build files
            build_dir = Path(".vystak") / self._agent.name
            build_dir.mkdir(parents=True, exist_ok=True)
            for filename, content in self._generated_code.files.items():
                file_path = build_dir / filename
                file_path.parent.mkdir(parents=True, exist_ok=True)
                file_path.write_text(content)

            # Bundle OpenAI-compatible schema types for Docker deployment
            import vystak.schema.openai as _openai_schema

            _openai_src = Path(_openai_schema.__file__)
            if _openai_src.exists():
                (build_dir / "openai_types.py").write_text(_openai_src.read_text())

            # Bundle unpublished vystak + vystak_adapter_langchain + transports
            # source trees onto the container's PYTHONPATH (via COPY . . in the Dockerfile).
            # vystak_adapter_langchain is bundled because the generated server.py
            # imports from its `compaction` subpackage when compaction is enabled.
            import vystak
            import vystak_adapter_langchain
            import vystak_transport_http
            import vystak_transport_nats

            _bundled_mods = (
                vystak,
                vystak_adapter_langchain,
                vystak_transport_http,
                vystak_transport_nats,
            )
            for _mod in _bundled_mods:
                _src = Path(_mod.__file__).parent
                _dst = build_dir / _src.name
                if _dst.exists():
                    shutil.rmtree(_dst)
                shutil.copytree(_src, _dst)

            # Build Dockerfile
            mcp_installs = ""
            needs_node = False
            if self._agent.mcp_servers:
                install_cmds = []
                for mcp in self._agent.mcp_servers:
                    if mcp.install:
                        install_cmds.append(f"RUN {mcp.install}")
                    for field in (mcp.install or "", mcp.command or ""):
                        if "npm" in field or "npx" in field:
                            needs_node = True
                if install_cmds:
                    mcp_installs = "\n".join(install_cmds) + "\n"

            node_install = ""
            if needs_node:
                node_install = (
                    "RUN apt-get update && apt-get install -y nodejs npm "
                    "&& rm -rf /var/lib/apt/lists/*\n"
                )

            dockerfile_content = (
                "FROM python:3.11-slim\n"
                "WORKDIR /app\n"
                f"{node_install}"
                f"{mcp_installs}"
                "COPY requirements.txt .\n"
                "RUN pip install --no-cache-dir -r requirements.txt\n"
                "COPY . .\n"
            )
            if self._vault_secrets_volume:
                from vystak_provider_docker.templates import generate_entrypoint_shim

                (build_dir / "entrypoint-shim.sh").write_text(generate_entrypoint_shim())
                dockerfile_content += (
                    "COPY entrypoint-shim.sh /vystak/entrypoint-shim.sh\n"
                    "RUN chmod +x /vystak/entrypoint-shim.sh\n"
                    'ENTRYPOINT ["/vystak/entrypoint-shim.sh"]\n'
                )
            if self._workspace_host:
                # Agent-side SSH keys are rendered by the vault-agent sidecar
                # into /shared/ssh/* (the agent-secrets volume mounted at
                # /shared). Expose them at the canonical /vystak/ssh/* path
                # via a symlink — agent-side code reads from /vystak/ssh/.
                dockerfile_content += (
                    "RUN mkdir -p /vystak && ln -sf /shared/ssh /vystak/ssh\n"
                )
            dockerfile_content += (
                f'CMD ["python", "{self._generated_code.entrypoint}"]\n'
            )
            (build_dir / "Dockerfile").write_text(dockerfile_content)

            # Build image
            image_tag = f"{container_name}:latest"
            self._client.images.build(path=str(build_dir), tag=image_tag)

            # Build env vars
            env: dict[str, str] = {
                "VYSTAK_TRANSPORT_TYPE": "http",
                "VYSTAK_ROUTES_JSON": self._peer_routes_json,
            }
            for secret in self._agent.secrets:
                value = os.environ.get(secret.name)
                if value:
                    env[secret.name] = value
            # Connection strings from upstream services
            if self._agent.sessions:
                dep_result = context.get(self._agent.sessions.name)
                if dep_result and dep_result.info.get("connection_string"):
                    env["SESSION_STORE_URL"] = dep_result.info["connection_string"]

            if self._agent.memory:
                dep_result = context.get(self._agent.memory.name)
                if dep_result and dep_result.info.get("connection_string"):
                    env["MEMORY_STORE_URL"] = dep_result.info["connection_string"]

            # Caller-supplied overrides (e.g. transport-plugin env contract)
            # take precedence over the defaults above.
            env.update(self._extra_env)

            # Default path delivers secrets via docker run environment=;
            # Vault path delivers via Vault Agent → /shared/secrets.env → shim.
            if self._default_path_env is not None:
                for key, value in self._default_path_env.items():
                    env[key] = value

            if self._workspace_host:
                env["VYSTAK_WORKSPACE_HOST"] = self._workspace_host

            # Build volumes
            volumes = {}
            for dep_name in self.depends_on:
                if dep_name == "network":
                    continue
                dep_result = context.get(dep_name)
                if dep_result and dep_result.info.get("engine") == "sqlite":
                    volumes[dep_result.info["volume_name"]] = {
                        "bind": "/data",
                        "mode": "rw",
                    }
            if self._vault_secrets_volume:
                # Vault path: entire /shared populated by Vault Agent sidecar.
                volumes[self._vault_secrets_volume] = {
                    "bind": "/shared",
                    "mode": "ro",
                }
            elif self._default_path_ssh_host_dir:
                # Default path: bind-mount individual SSH files to /shared/ssh/*.
                from pathlib import Path as _Path

                ssh_dir = _Path(self._default_path_ssh_host_dir)
                volumes[str(ssh_dir / "client-key")] = {
                    "bind": "/shared/ssh/id_ed25519",
                    "mode": "ro",
                }
                volumes[str(ssh_dir / "host-key.pub")] = {
                    "bind": "/shared/ssh/host_key.pub",
                    "mode": "ro",
                }

            # Run container
            host_port = self._agent.port if self._agent.port else None
            self._client.containers.run(
                image_tag,
                name=container_name,
                detach=True,
                ports={"8000/tcp": host_port},
                environment=env,
                volumes=volumes,
                network=network.name,
                labels={
                    "vystak.hash": self._plan.target_hash,
                    "vystak.agent": self._agent.name,
                },
            )

            # Get the actual port
            container = self._client.containers.get(container_name)
            port_info = container.ports.get("8000/tcp")
            actual_port = port_info[0]["HostPort"] if port_info else "?"
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
            return ProvisionResult(
                name=self.name,
                success=False,
                error=str(e),
            )

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
