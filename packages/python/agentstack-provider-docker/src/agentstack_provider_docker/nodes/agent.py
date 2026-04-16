"""DockerAgentNode — builds and runs an agent as a Docker container."""

import os
from pathlib import Path

from agentstack.provisioning.health import HealthCheck, NoopHealthCheck
from agentstack.provisioning.node import Provisionable, ProvisionResult
from agentstack.providers.base import DeployPlan, GeneratedCode
from agentstack.schema.agent import Agent

import docker.errors


class DockerAgentNode(Provisionable):
    """Builds a Docker image and runs an agent container."""

    def __init__(self, client, agent: Agent, generated_code: GeneratedCode, plan: DeployPlan):
        self._client = client
        self._agent = agent
        self._generated_code = generated_code
        self._plan = plan

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
        return f"agentstack-{self._agent.name}"

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
            build_dir = Path(".agentstack") / self._agent.name
            build_dir.mkdir(parents=True, exist_ok=True)
            for filename, content in self._generated_code.files.items():
                file_path = build_dir / filename
                file_path.parent.mkdir(parents=True, exist_ok=True)
                file_path.write_text(content)

            # Bundle OpenAI-compatible schema types for Docker deployment
            import agentstack.schema.openai as _openai_schema
            _openai_src = Path(_openai_schema.__file__)
            if _openai_src.exists():
                (build_dir / "openai_types.py").write_text(_openai_src.read_text())

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
                f'CMD ["python", "{self._generated_code.entrypoint}"]\n'
            )
            (build_dir / "Dockerfile").write_text(dockerfile_content)

            # Build image
            image_tag = f"{container_name}:latest"
            self._client.images.build(path=str(build_dir), tag=image_tag)

            # Build env vars
            env = {}
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
                    "agentstack.hash": self._plan.target_hash,
                    "agentstack.agent": self._agent.name,
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
