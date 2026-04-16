"""Docker platform provider — builds and runs agents as Docker containers."""

import os
from pathlib import Path

import docker
import docker.errors
from vystak.hash import hash_agent
from vystak.providers.base import (
    AgentStatus,
    DeployPlan,
    DeployResult,
    GeneratedCode,
    PlatformProvider,
)
from vystak.schema.agent import Agent
from vystak.schema.channel import SlackChannel

from vystak_provider_docker.gateway import (
    build_gateway_image,
    destroy_gateway,
    provision_gateway,
    write_gateway_source,
    write_routes_file,
)

DOCKERFILE_TEMPLATE = """\
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["python", "{entrypoint}"]
"""

SECRETS_PATH = Path(".vystak") / "secrets.json"


class DockerProvider(PlatformProvider):
    """Deploys and manages agents as Docker containers."""

    def __init__(self):
        self._client = self._create_client()
        self._generated_code: GeneratedCode | None = None
        self._agent: Agent | None = None

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
        return f"vystak-{agent_name}"

    def _get_container(self, agent_name: str):
        try:
            return self._client.containers.get(self._container_name(agent_name))
        except docker.errors.NotFound:
            return None

    def _all_services(self) -> list:
        """Collect all services from sessions, memory, services, and legacy resources."""
        from vystak.schema.service import Service

        result = []
        if self._agent:
            if self._agent.sessions and isinstance(self._agent.sessions, Service):
                result.append(self._agent.sessions)
            if self._agent.memory and isinstance(self._agent.memory, Service):
                result.append(self._agent.memory)
            result.extend(self._agent.services)
            # Legacy fallback: if no new-style services, use resources
            if not result:
                for resource in self._agent.resources:
                    if resource.engine in ("postgres", "sqlite"):
                        result.append(resource)
        return result

    def _collect_gateway_info(self) -> dict:
        """Extract gateway/provider/route info from agent channels."""
        if not self._agent:
            return {}

        gateways = {}

        for channel in self._agent.channels:
            if not isinstance(channel, SlackChannel):
                continue

            cp = channel.provider
            gw = cp.gateway
            gw_name = gw.name

            if gw_name not in gateways:
                gateways[gw_name] = {"gateway": gw, "providers": {}, "routes": []}

            gw_info = gateways[gw_name]

            if cp.name not in gw_info["providers"]:
                config = dict(cp.config)
                resolved_config = {}
                for key, value in config.items():
                    if hasattr(value, "name"):
                        resolved_config[key] = os.environ.get(value.name, "")
                    else:
                        resolved_config[key] = value
                gw_info["providers"][cp.name] = {
                    "name": cp.name,
                    "type": cp.type,
                    "config": resolved_config,
                }

            agent_url = f"http://{self._container_name(self._agent.name)}:8000"
            gw_info["routes"].append(
                {
                    "provider_name": cp.name,
                    "agent_name": self._agent.name,
                    "agent_url": agent_url,
                    "channels": channel.channels,
                    "listen": channel.listen,
                    "threads": channel.threads,
                    "dm": channel.dm,
                }
            )

        return gateways

    def provision_gateways(self, network) -> None:
        """Provision gateway containers for the agent's channels."""
        gateways = self._collect_gateway_info()

        for gw_name, gw_info in gateways.items():
            gateway = gw_info["gateway"]
            gateway_dir = Path(".vystak") / f"gateway-{gw_name}"

            write_gateway_source(gateway_dir)

            routes_path = gateway_dir / "routes.json"
            write_routes_file(routes_path, list(gw_info["providers"].values()), gw_info["routes"])

            build_gateway_image(self._client, gw_name, str(gateway_dir))

            env = {}
            for prov in gw_info["providers"].values():
                for key, value in prov["config"].items():
                    if isinstance(value, str) and value:
                        env_key = f"{prov['name'].upper().replace('-', '_')}_{key.upper()}"
                        env[env_key] = value

            port = gateway.config.get("port", 8080)
            provision_gateway(
                self._client, gw_name, network, routes_path=str(routes_path), env=env, port=port
            )

    def destroy_gateways(self) -> None:
        """Destroy gateway containers for the agent's channels."""
        gateways = self._collect_gateway_info()
        for gw_name in gateways:
            destroy_gateway(self._client, gw_name)

    def get_hash(self, agent_name: str) -> str | None:
        container = self._get_container(agent_name)
        if container is None:
            return None
        return container.labels.get("vystak.hash")

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

        deployed_hash = container.labels.get("vystak.hash")
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
            from vystak.provisioning import ProvisionGraph

            from vystak_provider_docker.nodes import (
                DockerAgentNode,
                DockerGatewayNode,
                DockerNetworkNode,
                DockerServiceNode,
            )

            graph = ProvisionGraph()

            # Network
            graph.add(DockerNetworkNode(self._client))

            # Services (sessions, memory, services list)
            for svc in self._all_services():
                if svc.engine in ("postgres", "sqlite"):
                    node = DockerServiceNode(self._client, svc, SECRETS_PATH)
                    graph.add(node)

            # Agent container
            agent_node = DockerAgentNode(
                self._client,
                self._agent,
                self._generated_code,
                plan,
            )
            graph.add(agent_node)

            # Gateways
            for gw_name, gw_info in self._collect_gateway_info().items():
                gw_node = DockerGatewayNode(
                    self._client,
                    gw_name,
                    gw_info,
                    self._agent.name,
                )
                graph.add(gw_node)

            # Execute the graph
            results = graph.execute()

            # Extract result from agent node
            agent_result = results.get(f"agent:{plan.agent_name}")
            if agent_result and agent_result.success:
                url = agent_result.info.get("url", "?")
                return DeployResult(
                    agent_name=plan.agent_name,
                    success=True,
                    hash=plan.target_hash,
                    message=f"Deployed {plan.agent_name} at {url}",
                )

            return DeployResult(
                agent_name=plan.agent_name,
                success=False,
                hash=plan.target_hash,
                message="Agent node not found in provision results",
            )

        except Exception as e:
            return DeployResult(
                agent_name=plan.agent_name,
                success=False,
                hash=plan.target_hash,
                message=f"Deployment failed: {e}",
            )

    def destroy(self, agent_name: str, include_resources: bool = False, **kwargs) -> None:
        container = self._get_container(agent_name)
        if container is not None:
            container.stop()
            container.remove()

        if include_resources and self._agent:
            from vystak_provider_docker.nodes.service import DockerServiceNode

            for svc in self._all_services():
                node = DockerServiceNode(self._client, svc, SECRETS_PATH)
                node.destroy()
            self.destroy_gateways()

    def status(self, agent_name: str) -> AgentStatus:
        container = self._get_container(agent_name)
        if container is None:
            return AgentStatus(agent_name=agent_name, running=False, hash=None)
        return AgentStatus(
            agent_name=agent_name,
            running=container.status == "running",
            hash=container.labels.get("vystak.hash"),
            info={
                "container": self._container_name(agent_name),
                "status": container.status,
                "ports": container.ports,
            },
        )
