"""AzureProvider — deploys agents to Azure Container Apps via ProvisionGraph."""

import hashlib
from pathlib import Path

import docker
import docker.errors

from agentstack.hash import hash_agent
from agentstack.provisioning import ProvisionGraph
from agentstack.providers.base import (
    AgentStatus,
    DeployPlan,
    DeployResult,
    GeneratedCode,
    PlatformProvider,
)
from agentstack.schema.agent import Agent

from agentstack_provider_azure.auth import get_credential, get_location, get_subscription_id
from agentstack_provider_azure.nodes import (
    ACRNode,
    ACAEnvironmentNode,
    ContainerAppNode,
    LogAnalyticsNode,
    ResourceGroupNode,
)


class AzureProvider(PlatformProvider):
    """Deploys and manages agents on Azure Container Apps."""

    def __init__(self):
        self._generated_code: GeneratedCode | None = None
        self._agent: Agent | None = None

    def set_generated_code(self, code: GeneratedCode) -> None:
        self._generated_code = code

    def set_agent(self, agent: Agent) -> None:
        self._agent = agent

    # ------------------------------------------------------------------
    # Config helpers
    # ------------------------------------------------------------------

    def _platform_config(self) -> dict:
        """Merge provider config with platform-level config."""
        if self._agent and self._agent.platform:
            merged = dict(self._agent.platform.config)
            merged.update(self._agent.platform.provider.config)
            return merged
        return {}

    def _rg_name(self, agent_name: str) -> str:
        cfg = self._platform_config()
        return cfg.get("resource_group", f"agentstack-{agent_name}-rg")

    def _acr_name(self, agent_name: str) -> str:
        cfg = self._platform_config()
        raw = cfg.get("registry", "")
        if raw:
            return raw.replace(".azurecr.io", "")
        digest = hashlib.md5(agent_name.encode()).hexdigest()[:8]
        return f"agentstack{digest}"

    def _env_name(self, agent_name: str) -> str:
        cfg = self._platform_config()
        return cfg.get("environment", f"agentstack-{agent_name}-env")

    def _tags(self, agent_name: str) -> dict:
        tags = {
            "agentstack:managed": "true",
            "agentstack:agent": agent_name,
        }
        cfg = self._platform_config()
        tags.update(cfg.get("tags", {}))
        return tags

    @staticmethod
    def _create_docker_client():
        try:
            return docker.from_env()
        except docker.errors.DockerException:
            desktop_socket = Path.home() / ".docker" / "run" / "docker.sock"
            if desktop_socket.exists():
                return docker.DockerClient(base_url=f"unix://{desktop_socket}")
            raise

    # ------------------------------------------------------------------
    # PlatformProvider interface
    # ------------------------------------------------------------------

    def get_hash(self, agent_name: str) -> str | None:
        # Phase 2a — no remote hash storage yet
        return None

    def plan(self, agent: Agent, current_hash: str | None) -> DeployPlan:
        tree = hash_agent(agent)
        return DeployPlan(
            agent_name=agent.name,
            actions=["Deploy to Azure Container Apps"],
            current_hash=current_hash,
            target_hash=tree.root,
            changes={"all": (current_hash, tree.root)},
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
            cfg = self._platform_config()
            credential = get_credential()
            subscription_id = get_subscription_id(cfg)
            location = get_location(cfg)

            # Lazy-create Azure management clients
            from azure.mgmt.appcontainers import ContainerAppsAPIClient
            from azure.mgmt.containerregistry import ContainerRegistryManagementClient
            from azure.mgmt.loganalytics import LogAnalyticsManagementClient
            from azure.mgmt.resource import ResourceManagementClient

            resource_client = ResourceManagementClient(credential, subscription_id)
            la_client = LogAnalyticsManagementClient(credential, subscription_id)
            acr_client = ContainerRegistryManagementClient(credential, subscription_id)
            aca_client = ContainerAppsAPIClient(credential, subscription_id)
            docker_client = self._create_docker_client()

            agent_name = plan.agent_name
            rg_name = self._rg_name(agent_name)
            acr_name = self._acr_name(agent_name)
            env_name = self._env_name(agent_name)
            location = get_location(cfg)
            tags = self._tags(agent_name)

            acr_existing = bool(cfg.get("registry"))
            env_existing = bool(cfg.get("environment"))

            graph = ProvisionGraph()

            graph.add(ResourceGroupNode(
                client=resource_client,
                rg_name=rg_name,
                location=location,
                tags=tags,
            ))

            graph.add(LogAnalyticsNode(
                client=la_client,
                rg_name=rg_name,
                workspace_name=f"{agent_name}-logs",
                location=location,
            ))

            graph.add(ACRNode(
                client=acr_client,
                rg_name=rg_name,
                registry_name=acr_name,
                location=location,
                existing=acr_existing,
            ))

            graph.add(ACAEnvironmentNode(
                client=aca_client,
                rg_name=rg_name,
                env_name=env_name,
                location=location,
                existing=env_existing,
            ))

            graph.add(ContainerAppNode(
                aca_client=aca_client,
                docker_client=docker_client,
                rg_name=rg_name,
                agent=self._agent,
                generated_code=self._generated_code,
                plan=plan,
                platform_config=cfg,
            ))

            results = graph.execute()

            app_result = results.get("container-app")
            if app_result and app_result.success:
                url = app_result.info.get("url", "?")
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
                message="Container app node not found in provision results",
            )

        except Exception as e:
            return DeployResult(
                agent_name=plan.agent_name,
                success=False,
                hash=plan.target_hash,
                message=f"Deployment failed: {e}",
            )

    def destroy(self, agent_name: str) -> None:
        cfg = self._platform_config()
        credential = get_credential()
        subscription_id = get_subscription_id(cfg)

        from azure.mgmt.appcontainers import ContainerAppsAPIClient

        aca_client = ContainerAppsAPIClient(credential, subscription_id)
        rg_name = self._rg_name(agent_name)

        aca_client.container_apps.begin_delete(rg_name, agent_name).result()

    def status(self, agent_name: str) -> AgentStatus:
        try:
            cfg = self._platform_config()
            credential = get_credential()
            subscription_id = get_subscription_id(cfg)

            from azure.mgmt.appcontainers import ContainerAppsAPIClient

            aca_client = ContainerAppsAPIClient(credential, subscription_id)
            rg_name = self._rg_name(agent_name)

            app = aca_client.container_apps.get(rg_name, agent_name)
            fqdn = app.configuration.ingress.fqdn if app.configuration and app.configuration.ingress else None

            return AgentStatus(
                agent_name=agent_name,
                running=app.provisioning_state == "Succeeded",
                hash=None,
                info={
                    "fqdn": fqdn,
                    "url": f"https://{fqdn}" if fqdn else None,
                    "provisioning_state": app.provisioning_state,
                },
            )
        except Exception:
            return AgentStatus(agent_name=agent_name, running=False, hash=None)
