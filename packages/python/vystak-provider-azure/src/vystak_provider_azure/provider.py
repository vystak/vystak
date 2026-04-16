"""AzureProvider — deploys agents to Azure Container Apps via ProvisionGraph."""

import hashlib
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
from vystak.provisioning import ProvisionGraph
from vystak.schema.agent import Agent
from vystak_provider_docker.secrets import get_resource_password

from vystak_provider_azure.auth import get_credential, get_location, get_subscription_id
from vystak_provider_azure.nodes import (
    ACAEnvironmentNode,
    ACRNode,
    AzurePostgresNode,
    ContainerAppNode,
    LogAnalyticsNode,
    ResourceGroupNode,
)


class AzureProvider(PlatformProvider):
    """Deploys and manages agents on Azure Container Apps."""

    def __init__(self):
        self._generated_code: GeneratedCode | None = None
        self._agent: Agent | None = None
        self._listener = None

    def set_listener(self, listener) -> None:
        self._listener = listener

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
        return cfg.get("resource_group", f"vystak-{agent_name}-rg")

    def _acr_name(self, agent_name: str) -> str:
        cfg = self._platform_config()
        raw = cfg.get("registry", "")
        if raw:
            return raw.replace(".azurecr.io", "")
        # Derive from RG name so agents in the same RG share one registry
        rg = self._rg_name(agent_name)
        digest = hashlib.md5(rg.encode()).hexdigest()[:8]
        return f"vystak{digest}"

    def _env_name(self, agent_name: str) -> str:
        cfg = self._platform_config()
        if cfg.get("environment"):
            return cfg["environment"]
        # Derive from RG name so agents in the same RG share an environment
        rg = self._rg_name(agent_name)
        return f"{rg}-env"

    def _tags(self, agent_name: str) -> dict:
        tags = {
            "vystak:managed": "true",
            "vystak:agent": agent_name,
        }
        cfg = self._platform_config()
        tags.update(cfg.get("tags", {}))
        return tags

    @staticmethod
    def _postgres_server_name(rg_name: str, service_name: str) -> str:
        """Derive a globally unique Postgres server name from RG + service name."""
        import re

        raw = f"{rg_name}-{service_name}"
        sanitized = re.sub(r"[^a-z0-9-]", "-", raw.lower())
        sanitized = sanitized.strip("-")[:63]
        return sanitized

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
        """Read the deployed hash from Container App tags."""
        try:
            cfg = self._platform_config()
            credential = get_credential()
            subscription_id = get_subscription_id(cfg)
            rg_name = self._rg_name(agent_name)

            from azure.mgmt.appcontainers import ContainerAppsAPIClient

            aca_client = ContainerAppsAPIClient(credential, subscription_id)

            app = aca_client.container_apps.get(rg_name, agent_name)
            if app.tags:
                return app.tags.get("vystak:hash")
        except Exception:
            pass
        return None

    def plan(self, agent: Agent, current_hash: str | None) -> DeployPlan:
        tree = hash_agent(agent)
        target_hash = tree.root

        if current_hash == target_hash:
            return DeployPlan(
                agent_name=agent.name,
                actions=[],
                current_hash=current_hash,
                target_hash=target_hash,
                changes={},
            )

        if current_hash is None:
            return DeployPlan(
                agent_name=agent.name,
                actions=["Create new deployment on Azure Container Apps"],
                current_hash=None,
                target_hash=target_hash,
                changes={"all": (None, target_hash)},
            )

        return DeployPlan(
            agent_name=agent.name,
            actions=["Update deployment on Azure Container Apps"],
            current_hash=current_hash,
            target_hash=target_hash,
            changes={"root": (current_hash, target_hash)},
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

            # Collect unique managed Postgres services from agent
            postgres_services = {}
            for svc in [self._agent.sessions, self._agent.memory] + list(self._agent.services):
                if (
                    svc
                    and svc.type == "postgres"
                    and svc.is_managed
                    and svc.name not in postgres_services
                ):
                    postgres_services[svc.name] = svc

            # Create Postgres client only if needed
            postgres_client = None
            if postgres_services:
                from azure.mgmt.rdbms.postgresql_flexibleservers import PostgreSQLManagementClient

                postgres_client = PostgreSQLManagementClient(credential, subscription_id)

            graph = ProvisionGraph()

            if self._listener:
                graph.set_listener(self._listener)

            graph.add(
                ResourceGroupNode(
                    client=resource_client,
                    rg_name=rg_name,
                    location=location,
                    tags=tags,
                )
            )

            graph.add(
                LogAnalyticsNode(
                    client=la_client,
                    rg_name=rg_name,
                    workspace_name=f"{rg_name}-logs",
                    location=location,
                    tags=tags,
                )
            )

            graph.add(
                ACRNode(
                    client=acr_client,
                    rg_name=rg_name,
                    registry_name=acr_name,
                    location=location,
                    existing=acr_existing,
                    tags=tags,
                )
            )

            graph.add(
                ACAEnvironmentNode(
                    client=aca_client,
                    rg_name=rg_name,
                    env_name=env_name,
                    location=location,
                    existing=env_existing,
                    tags=tags,
                )
            )

            secrets_path = Path(".vystak") / "secrets.json"
            for svc_name, svc in postgres_services.items():
                server_name = self._postgres_server_name(rg_name, svc_name)
                password = get_resource_password(f"azure-postgres-{server_name}", secrets_path)
                graph.add(
                    AzurePostgresNode(
                        client=postgres_client,
                        rg_name=rg_name,
                        server_name=server_name,
                        service_name=svc_name,
                        location=location,
                        admin_password=password,
                        config=svc.config,
                        tags=tags,
                    )
                )

            graph.add(
                ContainerAppNode(
                    aca_client=aca_client,
                    docker_client=docker_client,
                    rg_name=rg_name,
                    agent=self._agent,
                    generated_code=self._generated_code,
                    plan=plan,
                    platform_config=cfg,
                )
            )

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

    def list_resources(self, agent_name: str) -> list[dict]:
        """List all Azure resources tagged for this agent. Returns list of {name, type, id}."""
        cfg = self._platform_config()
        credential = get_credential()
        subscription_id = get_subscription_id(cfg)
        rg_name = self._rg_name(agent_name)

        from azure.mgmt.resource import ResourceManagementClient

        resource_client = ResourceManagementClient(credential, subscription_id)

        try:
            tag_filter = f"tagName eq 'vystak:agent' and tagValue eq '{agent_name}'"
            resources = list(
                resource_client.resources.list_by_resource_group(
                    rg_name,
                    filter=tag_filter,
                )
            )
        except Exception:
            resources = []

        result = []
        for r in resources:
            result.append(
                {
                    "name": r.name,
                    "type": r.type,
                    "id": r.id,
                }
            )

        # Include the RG itself if auto-created
        if not cfg.get("resource_group"):
            result.append(
                {
                    "name": rg_name,
                    "type": "Microsoft.Resources/resourceGroups",
                    "id": f"/subscriptions/{subscription_id}/resourceGroups/{rg_name}",
                }
            )

        return result

    def destroy(
        self, agent_name: str, include_resources: bool = False, no_wait: bool = False
    ) -> None:
        cfg = self._platform_config()
        credential = get_credential()
        subscription_id = get_subscription_id(cfg)
        rg_name = self._rg_name(agent_name)

        from azure.mgmt.appcontainers import ContainerAppsAPIClient

        aca_client = ContainerAppsAPIClient(credential, subscription_id)

        # Always delete the Container App
        try:
            poller = aca_client.container_apps.begin_delete(rg_name, agent_name)
            if not no_wait:
                poller.result()
        except Exception:
            pass

        if not include_resources:
            return

        # Tag-based cleanup: find and delete all tagged resources
        from azure.mgmt.resource import ResourceManagementClient

        resource_client = ResourceManagementClient(credential, subscription_id)

        tag_filter = f"tagName eq 'vystak:agent' and tagValue eq '{agent_name}'"
        resources = list(
            resource_client.resources.list_by_resource_group(
                rg_name,
                filter=tag_filter,
            )
        )

        # Delete in reverse dependency order
        type_order = {
            "microsoft.app/containerapps": 0,
            "microsoft.app/managedenvironments": 1,
            "microsoft.containerregistry/registries": 2,
            "microsoft.operationalinsights/workspaces": 3,
            "microsoft.network/virtualnetworks": 4,
            "microsoft.dbforpostgresql/flexibleservers": 5,
            "microsoft.keyvault/vaults": 6,
        }

        resources.sort(key=lambda r: type_order.get(r.type.lower(), 99))

        pollers = []
        for resource in resources:
            try:
                poller = resource_client.resources.begin_delete_by_id(
                    resource.id,
                    api_version=self._api_version(resource.type),
                )
                if no_wait:
                    pollers.append((resource.name, poller))
                else:
                    poller.result()
            except Exception:
                pass

        # Delete auto-created RG
        if not cfg.get("resource_group"):
            try:
                poller = resource_client.resource_groups.begin_delete(rg_name)
                if not no_wait:
                    poller.result()
            except Exception:
                pass

    @staticmethod
    def _api_version(resource_type: str) -> str:
        """Get the API version for a given Azure resource type."""
        versions = {
            "microsoft.app/containerapps": "2024-03-01",
            "microsoft.app/managedenvironments": "2024-03-01",
            "microsoft.containerregistry/registries": "2023-07-01",
            "microsoft.operationalinsights/workspaces": "2023-09-01",
            "microsoft.network/virtualnetworks": "2024-01-01",
            "microsoft.dbforpostgresql/flexibleservers": "2023-12-01-preview",
            "microsoft.keyvault/vaults": "2023-07-01",
        }
        return versions.get(resource_type.lower(), "2024-01-01")

    def status(self, agent_name: str) -> AgentStatus:
        try:
            cfg = self._platform_config()
            credential = get_credential()
            subscription_id = get_subscription_id(cfg)

            from azure.mgmt.appcontainers import ContainerAppsAPIClient

            aca_client = ContainerAppsAPIClient(credential, subscription_id)
            rg_name = self._rg_name(agent_name)

            app = aca_client.container_apps.get(rg_name, agent_name)
            fqdn = (
                app.configuration.ingress.fqdn
                if app.configuration and app.configuration.ingress
                else None
            )

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
