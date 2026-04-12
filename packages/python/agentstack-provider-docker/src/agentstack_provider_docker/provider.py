"""Docker platform provider — builds and runs agents as Docker containers."""

import os
from pathlib import Path

import docker
import docker.errors

from agentstack.hash import hash_agent
from agentstack.providers.base import (
    AgentStatus,
    DeployPlan,
    DeployResult,
    GeneratedCode,
    PlatformProvider,
)
from agentstack.schema.agent import Agent
from agentstack.schema.resource import SessionStore
from agentstack_provider_docker.network import ensure_network
from agentstack_provider_docker.resources import (
    destroy_resource,
    provision_resource,
)


DOCKERFILE_TEMPLATE = """\
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["python", "{entrypoint}"]
"""

SECRETS_PATH = Path(".agentstack") / "secrets.json"


class DockerProvider(PlatformProvider):
    """Deploys and manages agents as Docker containers."""

    def __init__(self):
        self._client = self._create_client()
        self._generated_code: GeneratedCode | None = None
        self._agent: Agent | None = None
        self._resource_info: list[dict] = []

    @staticmethod
    def _create_client():
        try:
            return docker.from_env()
        except docker.errors.DockerException:
            desktop_socket = Path.home() / ".docker" / "run" / "docker.sock"
            if desktop_socket.exists():
                return docker.DockerClient(base_url=f"unix://{desktop_socket}")
            raise

    def set_generated_code(self, code: GeneratedCode) -> None:
        self._generated_code = code

    def set_agent(self, agent: Agent) -> None:
        self._agent = agent

    def _container_name(self, agent_name: str) -> str:
        return f"agentstack-{agent_name}"

    def _get_container(self, agent_name: str):
        try:
            return self._client.containers.get(self._container_name(agent_name))
        except docker.errors.NotFound:
            return None

    def _build_env(self) -> dict[str, str]:
        env = {}
        if self._agent:
            for secret in self._agent.secrets:
                value = os.environ.get(secret.name)
                if value:
                    env[secret.name] = value
            for info in self._resource_info:
                if info["engine"] in ("postgres", "sqlite"):
                    env["SESSION_STORE_URL"] = info["connection_string"]
        return env

    def _build_volumes(self) -> dict:
        volumes = {}
        for info in self._resource_info:
            if info["engine"] == "sqlite":
                volumes[info["volume_name"]] = {"bind": "/data", "mode": "rw"}
        return volumes

    def get_hash(self, agent_name: str) -> str | None:
        container = self._get_container(agent_name)
        if container is None:
            return None
        return container.labels.get("agentstack.hash")

    def plan(self, agent: Agent, current_hash: str | None) -> DeployPlan:
        tree = hash_agent(agent)
        target_hash = tree.root
        container = self._get_container(agent.name)

        if container is None:
            return DeployPlan(
                agent_name=agent.name,
                actions=["Create new deployment"],
                current_hash=None,
                target_hash=target_hash,
                changes={"all": (None, target_hash)},
            )

        deployed_hash = container.labels.get("agentstack.hash")
        if deployed_hash == target_hash:
            return DeployPlan(
                agent_name=agent.name,
                actions=[],
                current_hash=deployed_hash,
                target_hash=target_hash,
                changes={},
            )

        return DeployPlan(
            agent_name=agent.name,
            actions=["Update deployment"],
            current_hash=deployed_hash,
            target_hash=target_hash,
            changes={"root": (deployed_hash, target_hash)},
        )

    def apply(self, plan: DeployPlan) -> DeployResult:
        if not self._generated_code:
            return DeployResult(
                agent_name=plan.agent_name,
                success=False,
                hash=plan.target_hash,
                message="No generated code set. Call set_generated_code() first.",
            )

        try:
            # 1. Ensure network
            network = ensure_network(self._client)

            # 2. Provision resources
            self._resource_info = []
            if self._agent:
                for resource in self._agent.resources:
                    if isinstance(resource, SessionStore) or resource.engine in ("postgres", "sqlite"):
                        info = provision_resource(
                            self._client, resource, network, SECRETS_PATH
                        )
                        self._resource_info.append(info)

            # 3. Stop existing agent container
            existing = self._get_container(plan.agent_name)
            if existing is not None:
                existing.stop()
                existing.remove()

            # 4. Build image
            build_dir = Path(".agentstack") / plan.agent_name
            build_dir.mkdir(parents=True, exist_ok=True)
            for filename, content in self._generated_code.files.items():
                (build_dir / filename).write_text(content)
            dockerfile_content = DOCKERFILE_TEMPLATE.format(
                entrypoint=self._generated_code.entrypoint
            )
            (build_dir / "Dockerfile").write_text(dockerfile_content)
            image_tag = f"{self._container_name(plan.agent_name)}:latest"
            self._client.images.build(path=str(build_dir), tag=image_tag)

            # 5. Run agent container on network
            container_name = self._container_name(plan.agent_name)
            host_port = self._agent.port if self._agent and self._agent.port else None
            self._client.containers.run(
                image_tag,
                name=container_name,
                detach=True,
                ports={"8000/tcp": host_port},
                environment=self._build_env(),
                volumes=self._build_volumes(),
                network=network.name,
                labels={
                    "agentstack.hash": plan.target_hash,
                    "agentstack.agent": plan.agent_name,
                },
            )

            # Get the actual port
            container = self._client.containers.get(container_name)
            port_info = container.ports.get("8000/tcp")
            actual_port = port_info[0]["HostPort"] if port_info else "?"

            return DeployResult(
                agent_name=plan.agent_name,
                success=True,
                hash=plan.target_hash,
                message=f"Deployed {plan.agent_name} at http://localhost:{actual_port}",
            )
        except Exception as e:
            return DeployResult(
                agent_name=plan.agent_name,
                success=False,
                hash=plan.target_hash,
                message=f"Deployment failed: {e}",
            )

    def destroy(self, agent_name: str, include_resources: bool = False) -> None:
        container = self._get_container(agent_name)
        if container is not None:
            container.stop()
            container.remove()

        if include_resources and self._agent:
            for resource in self._agent.resources:
                destroy_resource(self._client, resource.name)

    def status(self, agent_name: str) -> AgentStatus:
        container = self._get_container(agent_name)
        if container is None:
            return AgentStatus(agent_name=agent_name, running=False, hash=None)
        return AgentStatus(
            agent_name=agent_name,
            running=container.status == "running",
            hash=container.labels.get("agentstack.hash"),
            info={
                "container": self._container_name(agent_name),
                "status": container.status,
                "ports": container.ports,
            },
        )
