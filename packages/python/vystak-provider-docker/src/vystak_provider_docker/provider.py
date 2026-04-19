"""Docker platform provider — builds and runs agents as Docker containers."""

from pathlib import Path

import docker
import docker.errors
from vystak.channels import get_plugin
from vystak.hash import hash_agent, hash_channel
from vystak.providers.base import (
    AgentStatus,
    DeployPlan,
    DeployResult,
    GeneratedCode,
    PlatformProvider,
)
from vystak.schema.agent import Agent
from vystak.schema.channel import Channel

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

    def apply(self, plan: DeployPlan, *, peer_routes: str | None = None) -> DeployResult:
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
                peer_routes_json=peer_routes if peer_routes is not None else "{}",
            )
            graph.add(agent_node)

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

    # === Channel provisioning ===

    def _channel_container_name(self, channel_name: str) -> str:
        return f"vystak-channel-{channel_name}"

    def _get_channel_container(self, channel_name: str):
        try:
            return self._client.containers.get(self._channel_container_name(channel_name))
        except docker.errors.NotFound:
            return None

    def get_channel_hash(self, channel: Channel) -> str | None:
        container = self._get_channel_container(channel.name)
        if container is None:
            return None
        return container.labels.get("vystak.channel.hash")

    def plan_channel(self, channel: Channel, current_hash: str | None) -> DeployPlan:
        tree = hash_channel(channel)
        target_hash = tree.root
        container = self._get_channel_container(channel.name)

        if container is None:
            return DeployPlan(
                agent_name=channel.name,
                actions=["Create new channel deployment"],
                current_hash=None,
                target_hash=target_hash,
                changes={"all": (None, target_hash)},
            )

        deployed_hash = container.labels.get("vystak.channel.hash")
        if deployed_hash == target_hash:
            return DeployPlan(
                agent_name=channel.name,
                actions=[],
                current_hash=deployed_hash,
                target_hash=target_hash,
                changes={},
            )

        return DeployPlan(
            agent_name=channel.name,
            actions=["Update channel deployment"],
            current_hash=deployed_hash,
            target_hash=target_hash,
            changes={"root": (deployed_hash, target_hash)},
        )

    def apply_channel(
        self,
        plan: DeployPlan,
        channel: Channel,
        resolved_routes: dict[str, dict[str, str]],
    ) -> DeployResult:
        try:
            plugin = get_plugin(channel.type)
        except KeyError as e:
            return DeployResult(
                agent_name=plan.agent_name,
                success=False,
                hash=plan.target_hash,
                message=str(e),
            )

        try:
            code = plugin.generate_code(channel, resolved_routes)

            from vystak.provisioning import ProvisionGraph

            from vystak_provider_docker.nodes import DockerChannelNode, DockerNetworkNode

            host_port = channel.config.get("port", 8080)

            graph = ProvisionGraph()
            graph.add(DockerNetworkNode(self._client))
            channel_node = DockerChannelNode(
                self._client,
                channel,
                code,
                plan.target_hash,
                host_port=host_port,
            )
            graph.add(channel_node)

            results = graph.execute()
            channel_result = results.get(f"channel:{channel.name}")
            if channel_result and channel_result.success:
                url = channel_result.info.get("url", "?")
                return DeployResult(
                    agent_name=channel.name,
                    success=True,
                    hash=plan.target_hash,
                    message=f"Deployed channel {channel.name} at {url}",
                )

            error = channel_result.error if channel_result else "Channel node not found"
            return DeployResult(
                agent_name=channel.name,
                success=False,
                hash=plan.target_hash,
                message=f"Channel deployment failed: {error}",
            )
        except Exception as e:
            return DeployResult(
                agent_name=channel.name,
                success=False,
                hash=plan.target_hash,
                message=f"Channel deployment failed: {e}",
            )

    def destroy_channel(self, channel: Channel) -> None:
        container = self._get_channel_container(channel.name)
        if container is not None:
            container.stop()
            container.remove()

    def channel_status(self, channel: Channel) -> AgentStatus:
        container = self._get_channel_container(channel.name)
        if container is None:
            return AgentStatus(agent_name=channel.name, running=False, hash=None)
        return AgentStatus(
            agent_name=channel.name,
            running=container.status == "running",
            hash=container.labels.get("vystak.channel.hash"),
            info={
                "container": self._channel_container_name(channel.name),
                "status": container.status,
                "ports": container.ports,
            },
        )
