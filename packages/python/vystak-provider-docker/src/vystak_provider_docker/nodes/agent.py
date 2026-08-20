"""DockerAgentNode — builds and runs an agent as a Docker container."""

import os
import shutil
from pathlib import Path

import docker.errors
from vystak.providers.base import DeployPlan, FileBundle
from vystak.provisioning.health import HealthCheck, NoopHealthCheck
from vystak.provisioning.node import Provisionable, ProvisionResult
from vystak.schema.agent import Agent


def mcp_toolchain_layers(mcp_servers) -> str:
    """Dockerfile RUN lines for toolchains the agent's MCP servers need.

    Sniffs ``command`` only (it's the bare executable): ``npx`` → node,
    ``uvx`` → uv. Anything else is assumed present in the base image or
    user-owned Dockerfile.
    """
    needs_node = any(m.command == "npx" for m in mcp_servers)
    needs_uv = any(m.command == "uvx" for m in mcp_servers)
    layers = ""
    if needs_node:
        layers += (
            "RUN apt-get update && apt-get install -y nodejs npm "
            "&& rm -rf /var/lib/apt/lists/*\n"
        )
    if needs_uv:
        layers += "RUN pip install --no-cache-dir uv\n"
    return layers


class DockerAgentNode(Provisionable):
    """Builds a Docker image and runs an agent container."""

    def __init__(
        self,
        client,
        agent: Agent,
        generated_code: FileBundle,
        plan: DeployPlan,
        *,
        peer_routes_json: str = "{}",
        extra_env: dict[str, str] | None = None,
        scheduler_enabled: bool = False,
    ):
        self._client = client
        self._agent = agent
        self._generated_code = generated_code
        self._plan = plan
        self._peer_routes_json = peer_routes_json
        self._extra_env = extra_env or {}
        self._scheduler_enabled = scheduler_enabled
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

    def _default_data_volume_name(self) -> str:
        return f"vystak-agent-{self._agent.name}-data"

    def _build_volumes(self, context: dict) -> dict:
        """Assemble the container's volume mounts.

        The /data mount can come from any sqlite-backed dependency in
        ``depends_on`` — a declared `sessions:` service, `memory:`, or a
        sqlite entry in `services:` — not just `sessions:` specifically.
        Agents where nothing claims /data still get a durable volume — the
        langchain template writes /data/sessions.db (checkpointer) and
        /data/turns.db (turn journal) by default, so durability would
        otherwise silently evaporate on container replacement.
        """
        volumes: dict = {}
        for dep_name in self.depends_on:
            if dep_name == "network":
                continue
            dep_result = context.get(dep_name)
            if dep_result and dep_result.info.get("engine") == "sqlite":
                volumes[dep_result.info["volume_name"]] = {
                    "bind": "/data",
                    "mode": "rw",
                }
        if not any(v.get("bind") == "/data" for v in volumes.values()):
            # No sqlite dependency (sessions or otherwise) claimed /data —
            # fall back to a per-agent volume so /data is always durable.
            volumes[self._default_data_volume_name()] = {
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
            # Assemble known_hosts so the agent's asyncssh client can
            # verify the workspace host key (test_plan gap #2 / V11).
            host_key_pub_path = ssh_dir / "host-key.pub"
            if self._workspace_host and host_key_pub_path.exists():
                known_hosts_path = ssh_dir / "known_hosts"
                host_key_pub = host_key_pub_path.read_text().strip()
                known_hosts_path.write_text(f"{self._workspace_host} {host_key_pub}\n")
                volumes[str(known_hosts_path)] = {
                    "bind": "/shared/ssh/known_hosts",
                    "mode": "ro",
                }
        return volumes

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

            # Bundle unpublished vystak + transport source trees onto the
            # container's PYTHONPATH (via COPY . . in the Dockerfile). The
            # framework template ships its own runtime under _vystak/ (already
            # bundled above via _generated_code.files), so no framework adapter
            # source needs to be copied here.
            import vystak
            import vystak_transport_http
            import vystak_transport_nats

            _bundled_mods = (
                vystak,
                vystak_transport_http,
                vystak_transport_nats,
            )
            for _mod in _bundled_mods:
                _src = Path(_mod.__file__).parent
                _dst = build_dir / _src.name
                if _dst.exists():
                    shutil.rmtree(_dst)
                shutil.copytree(_src, _dst)

            # Use the user's Dockerfile when scaffolded by the framework template
            # (it's already in build_dir from _generated_code.files). Only generate
            # one when the user hasn't provided one — needed for legacy/vault paths
            # that customize the build with sidecars or shims.
            user_dockerfile = build_dir / "Dockerfile"
            user_provided_dockerfile = user_dockerfile.exists()

            if not user_provided_dockerfile:
                dockerfile_content = (
                    "FROM python:3.11-slim\n"
                    "WORKDIR /app\n"
                    f"{mcp_toolchain_layers(self._agent.mcp_servers)}"
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
            agent_port = self._agent.port or 8000
            env: dict[str, str] = {
                "VYSTAK_TRANSPORT_TYPE": "http",
                "VYSTAK_ROUTES_JSON": self._peer_routes_json,
                # Public URL the agent advertises in its AgentCard. Peers
                # use this URL to call back via the SDK client; it MUST be
                # the Docker DNS hostname, not localhost (which is the
                # listener-side default in app_factory).
                "VYSTAK_AGENT_PUBLIC_URL": f"http://{container_name}:{agent_port}",
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

            if self._scheduler_enabled:
                env["VYSTAK_SCHEDULER_URL"] = "http://vystak-heartbeat:8081"
                env["VYSTAK_AGENT_CANONICAL"] = self._agent.canonical_name

            # Build volumes. When nothing else claims /data (no `sessions:`
            # and no other sqlite-backed dependency bound there), this
            # creates (idempotently) the fallback per-agent data volume so
            # /data is always durable across container replacement. Like
            # DockerServiceNode's sqlite/postgres volumes, this volume
            # survives `vystak destroy` by convention (see destroy() below)
            # — a later `vystak apply` reusing the same agent name resumes
            # against whatever /data/sessions.db and /data/turns.db already
            # hold on this volume, not a clean slate.
            volumes = self._build_volumes(context)
            data_volume_name = self._default_data_volume_name()
            if data_volume_name in volumes:
                existing_volumes = self._client.volumes.list(
                    filters={"name": data_volume_name}
                )
                if not existing_volumes:
                    self._client.volumes.create(data_volume_name)

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
        """Stop and remove the agent container.

        Data-bearing volumes (both a declared `sessions:` volume and the
        fallback per-agent data volume `vystak-agent-<name>-data` created
        when there's no `sessions:` declaration) are intentionally left in
        place — this mirrors DockerServiceNode.destroy(), which keeps
        sqlite/postgres volumes so durable state survives a redeploy.
        Volume cleanup on destroy would defeat the point of this task
        (durability across container replacement).

        Operational consequence: `vystak destroy` followed by `vystak apply`
        with the same agent name resumes against the stale
        /data/sessions.db and /data/turns.db already on that volume — the
        same stale-volume failure family CLAUDE.md documents for
        `vault_clean`/`postgres_clean` (the `vystak-vault-data` and
        `vystak-data-*` volumes surviving destroy across test runs). Any
        release-test fixture that expects a clean /data per run for a
        sessionless agent must clean `vystak-agent-*-data` the same way
        `postgres_clean` cleans `vystak-data-*`.
        """
        container_name = self._container_name()
        try:
            container = self._client.containers.get(container_name)
            container.stop()
            container.remove()
        except docker.errors.NotFound:
            pass
