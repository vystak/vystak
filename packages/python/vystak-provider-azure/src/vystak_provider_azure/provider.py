"""AzureProvider — deploys agents to Azure Container Apps via ProvisionGraph."""

import hashlib
from pathlib import Path

import docker
import docker.errors
from azure.keyvault.secrets import SecretClient
from azure.mgmt.appcontainers import ContainerAppsAPIClient
from azure.mgmt.authorization import AuthorizationManagementClient
from azure.mgmt.keyvault import KeyVaultManagementClient
from azure.mgmt.msi import ManagedServiceIdentityClient
from azure.mgmt.resource import ResourceManagementClient
from vystak.channels import get_plugin
from vystak.hash import hash_agent, hash_channel
from vystak.providers.base import (
    AgentStatus,
    DeployPlan,
    DeployResult,
    GeneratedCode,
    PlatformProvider,
)
from vystak.provisioning import ProvisionGraph
from vystak.schema.agent import Agent
from vystak.schema.channel import Channel
from vystak.schema.vault import Vault
from vystak_provider_docker.secrets import get_resource_password

from vystak_provider_azure.auth import get_credential, get_location, get_subscription_id
from vystak_provider_azure.nodes import (
    ACAEnvironmentNode,
    ACRNode,
    AzureChannelAppNode,
    AzurePostgresNode,
    ContainerAppNode,
    KeyVaultNode,
    KvGrantNode,
    LogAnalyticsNode,
    ResourceGroupNode,
    SecretSyncNode,
    UserAssignedIdentityNode,
)


class AzureProvider(PlatformProvider):
    """Deploys and manages agents on Azure Container Apps."""

    def __init__(self):
        self._generated_code: GeneratedCode | None = None
        self._agent: Agent | None = None
        self._listener = None
        self._vault: Vault | None = None
        self._env_values: dict[str, str] = {}
        self._force_sync: bool = False
        self._allow_missing: bool = False

    def set_listener(self, listener) -> None:
        self._listener = listener

    def set_generated_code(self, code: GeneratedCode) -> None:
        self._generated_code = code

    def set_agent(self, agent: Agent) -> None:
        self._agent = agent

    def set_vault(self, vault: Vault | None) -> None:
        """Declare the secrets backing store for this deploy.

        When set and the agent (or its workspace) declares any Secret, the
        provider adds KeyVault / UAMI / SecretSync / KvGrant nodes to the
        provisioning graph and switches ContainerAppNode into vault-backed
        mode (per-container secretRef + lifecycle:None identities).
        """
        self._vault = vault

    def set_env_values(self, values: dict[str, str]) -> None:
        """Supply deployer-side secret values (typically from a .env file).

        SecretSyncNode pushes values from this dict into the vault when the
        corresponding secret is absent (or when force=True). Values are only
        used during apply; they are never written to disk by vystak itself.
        """
        self._env_values = dict(values)

    def set_force_sync(self, force: bool) -> None:
        """If True, SecretSyncNode overwrites existing KV values (--force)."""
        self._force_sync = force

    def set_allow_missing(self, allow: bool) -> None:
        """If True, SecretSyncNode won't abort when a secret is absent everywhere."""
        self._allow_missing = allow

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

    def _tenant_id(self, cfg: dict) -> str:
        """Resolve the Azure tenant ID for the deploy.

        Falls back to an empty string when no tenant is configured — the
        KeyVaultNode only uses tenant_id in DEPLOY mode, and apply-time
        construction will populate this from CLI context there. Tests that
        mock the KV client never reach the tenant lookup.
        """
        return cfg.get("tenant_id", "")

    # ------------------------------------------------------------------
    # Graph construction
    # ------------------------------------------------------------------

    def _build_graph_for_tests(self, agent: Agent) -> ProvisionGraph:
        """Construct the provisioning graph for inspection in tests.

        Tests should patch the Azure client classes at module scope
        (`vystak_provider_azure.provider.*Client`) so no real API calls
        happen. The graph returned has the same structure `apply()` would
        build, minus Docker / DeployPlan bits.
        """
        cfg = self._platform_config()
        credential = get_credential()
        subscription_id = get_subscription_id(cfg)
        location = get_location(cfg)
        rg_name = self._rg_name(agent.name)
        tags = self._tags(agent.name)

        resource_client = ResourceManagementClient(credential, subscription_id)
        graph = ProvisionGraph()
        rg_node = ResourceGroupNode(
            client=resource_client,
            rg_name=rg_name,
            location=location,
            tags=tags,
        )
        graph.add(rg_node)

        self._add_vault_nodes(
            graph=graph,
            agent=agent,
            rg_name=rg_name,
            location=location,
            tags=tags,
            credential=credential,
            subscription_id=subscription_id,
            cfg=cfg,
        )
        return graph

    def _add_vault_nodes(
        self,
        *,
        graph: ProvisionGraph,
        agent: Agent,
        rg_name: str,
        location: str,
        tags: dict,
        credential,
        subscription_id: str,
        cfg: dict,
    ) -> tuple[KeyVaultNode | None, str | None, str | None, list[str], list[str]]:
        """Add Vault/Identity/Grant/SecretSync nodes when a Vault is declared.

        Returns (vault_node, agent_identity_name, workspace_identity_name,
        model_secrets, workspace_secrets) so the caller can wire the
        ContainerAppNode's vault context. When no Vault is declared,
        returns (None, None, None, [], []).

        Topological order the graph executes:
          RG -> Vault -> [Identity(s)] -> SecretSync -> [Grant(s)]
        Each Grant also depends on SecretSync so the secret value exists
        before the grant has any effect.
        """
        if self._vault is None:
            return (None, None, None, [], [])

        agent_secret_names = [s.name for s in agent.secrets]
        workspace_secret_names: list[str] = []
        if agent.workspace and agent.workspace.secrets:
            workspace_secret_names = [s.name for s in agent.workspace.secrets]

        # If nothing actually needs secrets, skip the whole subgraph.
        if not agent_secret_names and not workspace_secret_names:
            return (None, None, None, [], [])

        kv_mgmt_client = KeyVaultManagementClient(credential, subscription_id)
        vault_name = self._vault.config.get("vault_name") or self._vault.name
        vault_node = KeyVaultNode(
            client=kv_mgmt_client,
            rg_name=rg_name,
            vault_name=vault_name,
            location=location,
            mode=self._vault.mode,
            subscription_id=subscription_id,
            tenant_id=self._tenant_id(cfg),
            tags=tags,
        )
        graph.add(vault_node)
        graph.add_dependency(vault_node.name, "resource-group")

        msi_client = ManagedServiceIdentityClient(credential, subscription_id)

        agent_identity_node: UserAssignedIdentityNode | None = None
        workspace_identity_node: UserAssignedIdentityNode | None = None

        # Agent identity — only needed if agent has model secrets
        if agent_secret_names:
            existing_identity = getattr(agent, "identity", None)
            if existing_identity:
                agent_identity_node = UserAssignedIdentityNode.from_existing(
                    resource_id=existing_identity,
                    name=f"{agent.name}-agent",
                )
            else:
                agent_identity_node = UserAssignedIdentityNode(
                    client=msi_client,
                    rg_name=rg_name,
                    uami_name=f"{agent.name}-agent",
                    location=location,
                    tags=tags,
                )
            graph.add(agent_identity_node)
            graph.add_dependency(agent_identity_node.name, "resource-group")

        # Workspace identity — only needed if workspace has secrets
        if workspace_secret_names:
            existing_ws_identity = agent.workspace.identity if agent.workspace else None
            if existing_ws_identity:
                workspace_identity_node = UserAssignedIdentityNode.from_existing(
                    resource_id=existing_ws_identity,
                    name=f"{agent.name}-workspace",
                )
            else:
                workspace_identity_node = UserAssignedIdentityNode(
                    client=msi_client,
                    rg_name=rg_name,
                    uami_name=f"{agent.name}-workspace",
                    location=location,
                    tags=tags,
                )
            graph.add(workspace_identity_node)
            graph.add_dependency(workspace_identity_node.name, "resource-group")

        # SecretSync — runs after the vault exists; deployer credentials push
        # values for any declared secrets missing from KV.
        secret_client = SecretClient(
            vault_url=f"https://{vault_name}.vault.azure.net/",
            credential=credential,
        )
        all_declared = list(agent_secret_names) + list(workspace_secret_names)
        secret_sync = SecretSyncNode(
            client=secret_client,
            declared_secrets=all_declared,
            env_values=self._env_values,
            force=self._force_sync,
            allow_missing=self._allow_missing,
        )
        graph.add(secret_sync)
        graph.add_dependency(secret_sync.name, vault_node.name)

        # Grants — one per (identity, secret) pair, scoped to the individual
        # KV secret path. Each grant depends on the identity (principal_id),
        # the vault, and secret-sync (value must exist before the grant has
        # useful effect).
        auth_client = AuthorizationManagementClient(credential, subscription_id)
        vault_scope = (
            f"/subscriptions/{subscription_id}/resourceGroups/{rg_name}"
            f"/providers/Microsoft.KeyVault/vaults/{vault_name}"
        )
        if agent_identity_node is not None:
            for secret_name in agent_secret_names:
                secret_scope = f"{vault_scope}/secrets/{secret_name}"
                grant = KvGrantNode(
                    client=auth_client,
                    scope=secret_scope,
                    principal_id=None,  # resolved via set_principal_from_context
                    subscription_id=subscription_id,
                )
                grant.set_principal_from_context(
                    key=agent_identity_node.name,
                    field="principal_id",
                )
                graph.add(grant)
                graph.add_dependency(grant.name, agent_identity_node.name)
                graph.add_dependency(grant.name, vault_node.name)
                graph.add_dependency(grant.name, secret_sync.name)

        if workspace_identity_node is not None:
            for secret_name in workspace_secret_names:
                secret_scope = f"{vault_scope}/secrets/{secret_name}"
                grant = KvGrantNode(
                    client=auth_client,
                    scope=secret_scope,
                    principal_id=None,
                    subscription_id=subscription_id,
                )
                grant.set_principal_from_context(
                    key=workspace_identity_node.name,
                    field="principal_id",
                )
                graph.add(grant)
                graph.add_dependency(grant.name, workspace_identity_node.name)
                graph.add_dependency(grant.name, vault_node.name)
                graph.add_dependency(grant.name, secret_sync.name)

        return (
            vault_node,
            agent_identity_node.name if agent_identity_node else None,
            workspace_identity_node.name if workspace_identity_node else None,
            agent_secret_names,
            workspace_secret_names,
        )

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

    def apply(self, plan: DeployPlan, peer_routes: str | None = None) -> DeployResult:
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
                    peer_routes_json=peer_routes or "{}",
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

    # ------------------------------------------------------------------
    # Channel provisioning
    # ------------------------------------------------------------------

    def _channel_platform_config(self, channel: Channel) -> dict:
        """Merge provider config with channel's platform-level config."""
        if channel.platform:
            merged = dict(channel.platform.config)
            merged.update(channel.platform.provider.config)
            return merged
        return {}

    def _channel_rg_name(self, channel: Channel) -> str:
        cfg = self._channel_platform_config(channel)
        return cfg.get("resource_group", f"vystak-{channel.name}-rg")

    def _channel_acr_name(self, channel: Channel) -> str:
        cfg = self._channel_platform_config(channel)
        raw = cfg.get("registry", "")
        if raw:
            return raw.replace(".azurecr.io", "")
        rg = self._channel_rg_name(channel)
        digest = hashlib.md5(rg.encode()).hexdigest()[:8]
        return f"vystak{digest}"

    def _channel_env_name(self, channel: Channel) -> str:
        cfg = self._channel_platform_config(channel)
        if cfg.get("environment"):
            return cfg["environment"]
        rg = self._channel_rg_name(channel)
        return f"{rg}-env"

    def _channel_app_name(self, channel_name: str) -> str:
        return f"channel-{channel_name}"

    def get_channel_hash(self, channel: Channel) -> str | None:
        """Read the deployed channel hash from Container App tags."""
        try:
            cfg = self._channel_platform_config(channel)
            credential = get_credential()
            subscription_id = get_subscription_id(cfg)

            from azure.mgmt.appcontainers import ContainerAppsAPIClient

            aca_client = ContainerAppsAPIClient(credential, subscription_id)
            rg_name = self._channel_rg_name(channel)
            app_name = self._channel_app_name(channel.name)

            app = aca_client.container_apps.get(rg_name, app_name)
            if app.tags:
                return app.tags.get("vystak:channel-hash")
        except Exception:
            pass
        return None

    def plan_channel(self, channel: Channel, current_hash: str | None) -> DeployPlan:
        tree = hash_channel(channel)
        target_hash = tree.root

        if current_hash == target_hash:
            return DeployPlan(
                agent_name=channel.name,
                actions=[],
                current_hash=current_hash,
                target_hash=target_hash,
                changes={},
            )

        if current_hash is None:
            return DeployPlan(
                agent_name=channel.name,
                actions=["Create new channel deployment on Azure Container Apps"],
                current_hash=None,
                target_hash=target_hash,
                changes={"all": (None, target_hash)},
            )

        return DeployPlan(
            agent_name=channel.name,
            actions=["Update channel deployment on Azure Container Apps"],
            current_hash=current_hash,
            target_hash=target_hash,
            changes={"root": (current_hash, target_hash)},
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

            cfg = self._channel_platform_config(channel)
            credential = get_credential()
            subscription_id = get_subscription_id(cfg)
            location = get_location(cfg)

            from azure.mgmt.appcontainers import ContainerAppsAPIClient
            from azure.mgmt.containerregistry import ContainerRegistryManagementClient
            from azure.mgmt.loganalytics import LogAnalyticsManagementClient
            from azure.mgmt.resource import ResourceManagementClient

            resource_client = ResourceManagementClient(credential, subscription_id)
            la_client = LogAnalyticsManagementClient(credential, subscription_id)
            acr_client = ContainerRegistryManagementClient(credential, subscription_id)
            aca_client = ContainerAppsAPIClient(credential, subscription_id)
            docker_client = self._create_docker_client()

            rg_name = self._channel_rg_name(channel)
            acr_name = self._channel_acr_name(channel)
            env_name = self._channel_env_name(channel)
            tags = {
                "vystak:managed": "true",
                "vystak:channel": channel.name,
            }

            acr_existing = bool(cfg.get("registry"))
            env_existing = bool(cfg.get("environment"))

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
            graph.add(
                AzureChannelAppNode(
                    aca_client=aca_client,
                    docker_client=docker_client,
                    rg_name=rg_name,
                    channel=channel,
                    generated_code=code,
                    plan=plan,
                    platform_config=cfg,
                )
            )

            results = graph.execute()

            node_result = results.get(f"channel-app:{channel.name}")
            if node_result and node_result.success:
                url = node_result.info.get("url", "?")
                return DeployResult(
                    agent_name=channel.name,
                    success=True,
                    hash=plan.target_hash,
                    message=f"Deployed channel {channel.name} at {url}",
                )

            error = node_result.error if node_result else "Channel node not found"
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
        """Delete the channel's Container App using its own platform context.

        Critical: reads subscription/RG from channel.platform rather than from
        self._agent — the CLI doesn't set_agent during the channel lifecycle,
        and mixing the two previously led to silent fallback to the wrong RG.
        """
        cfg = self._channel_platform_config(channel)
        credential = get_credential()
        subscription_id = get_subscription_id(cfg)
        rg_name = self._channel_rg_name(channel)
        app_name = self._channel_app_name(channel.name)


        aca_client = ContainerAppsAPIClient(credential, subscription_id)
        poller = aca_client.container_apps.begin_delete(rg_name, app_name)
        poller.result()

    def channel_status(self, channel: Channel) -> AgentStatus:
        try:
            cfg = self._channel_platform_config(channel)
            credential = get_credential()
            subscription_id = get_subscription_id(cfg)

            from azure.mgmt.appcontainers import ContainerAppsAPIClient

            aca_client = ContainerAppsAPIClient(credential, subscription_id)
            rg_name = self._channel_rg_name(channel)
            app_name = self._channel_app_name(channel.name)

            app = aca_client.container_apps.get(rg_name, app_name)
            fqdn = (
                app.configuration.ingress.fqdn
                if app.configuration and app.configuration.ingress
                else None
            )
            hash_ = app.tags.get("vystak:channel-hash") if app.tags else None

            return AgentStatus(
                agent_name=channel.name,
                running=app.provisioning_state == "Succeeded",
                hash=hash_,
                info={
                    "fqdn": fqdn,
                    "url": f"https://{fqdn}" if fqdn else None,
                    "provisioning_state": app.provisioning_state,
                },
            )
        except Exception:
            return AgentStatus(agent_name=channel.name, running=False, hash=None)
