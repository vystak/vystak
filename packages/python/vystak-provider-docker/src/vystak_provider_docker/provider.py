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
from vystak.provisioning.node import Provisionable, ProvisionResult
from vystak.schema.agent import Agent
from vystak.schema.channel import Channel


class _LateBoundUnsealNode(Provisionable):
    """Unseal node that reads the unseal keys from the init node's
    ProvisionResult at run time (they're only known after init()).

    Wraps ``VaultClient.unseal`` directly so we can avoid constructing the
    ``HashiVaultUnsealNode`` with placeholder keys.
    """

    def __init__(self, *, vault_client, init_node_name: str, key_threshold: int):
        self._vault = vault_client
        self._init_node_name = init_node_name
        self._threshold = key_threshold

    @property
    def name(self) -> str:
        return "hashi-vault:unseal"

    @property
    def depends_on(self) -> list[str]:
        return [self._init_node_name]

    def provision(self, context: dict) -> ProvisionResult:
        init_info = context[self._init_node_name].info
        keys = init_info["unseal_keys"][: self._threshold]
        if self._vault.is_sealed():
            self._vault.unseal(keys)
        return ProvisionResult(name=self.name, success=True, info={})

    def health_check(self) -> bool:
        return True

    def destroy(self) -> None:
        pass


class _LateBoundKvSetupNode(Provisionable):
    """Enables KV v2 + AppRole auth, after reading the root token from the
    init node's ProvisionResult at run time."""

    def __init__(self, *, vault_client, init_node_name: str):
        self._vault = vault_client
        self._init_node_name = init_node_name

    @property
    def name(self) -> str:
        return "hashi-vault:kv-setup"

    @property
    def depends_on(self) -> list[str]:
        return ["hashi-vault:unseal"]

    def provision(self, context: dict) -> ProvisionResult:
        init_info = context[self._init_node_name].info
        self._vault.set_token(init_info["root_token"])
        self._vault.enable_kv_v2("secret")
        self._vault.enable_approle_auth()
        return ProvisionResult(name=self.name, success=True, info={})

    def health_check(self) -> bool:
        return True

    def destroy(self) -> None:
        pass

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
        self._vault = None
        self._env_values: dict[str, str] = {}
        self._force_sync: bool = False
        self._allow_missing: bool = False

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

    def set_vault(self, vault) -> None:
        """Declare the secrets backing store for this deploy.

        Docker provider rejects Azure Key Vault deploys (use AzureProvider).
        For HashiCorp Vault (``type='vault'``), ``apply()`` builds a Vault
        subgraph (server → init → unseal → kv-setup → per-principal AppRole
        + secret sync + agent sidecar) that injects short-lived secrets into
        main containers via a shared ``/shared`` volume.
        """
        self._vault = vault

    def set_env_values(self, values: dict[str, str]) -> None:
        """Supply deployer-side secret values (typically from a .env file).

        ``VaultSecretSyncNode`` pushes values from this dict into the vault
        when the corresponding secret is absent (or when force=True). Values
        are only used during apply; they are never written to disk by vystak
        itself.
        """
        self._env_values = dict(values)

    def set_force_sync(self, flag: bool) -> None:
        """If True, ``VaultSecretSyncNode`` overwrites existing KV values."""
        self._force_sync = bool(flag)

    def set_allow_missing(self, flag: bool) -> None:
        """If True, ``VaultSecretSyncNode`` won't abort when a secret is absent."""
        self._allow_missing = bool(flag)

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

    def plan(self, agent: Agent, current_hash: str | None = None) -> DeployPlan:
        if getattr(self, "_vault", None):
            from vystak.schema.common import VaultType

            if self._vault.type is VaultType.KEY_VAULT:
                raise ValueError(
                    "DockerProvider does not support Azure Key Vault. "
                    "Use Vault(type='vault', provider=docker) for HashiCorp "
                    "Vault, or deploy to Azure for Key Vault support."
                )
            # type=VAULT is handled by the apply graph; no plan-time rejection.
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

    def _add_vault_nodes(self, graph) -> dict[str, str]:
        """Attach the HashiCorp Vault subgraph to ``graph``.

        Returns ``{principal_name → secrets_volume_name}`` so the caller can
        wire each main container's ``set_vault_context(...)`` and graph
        dependency to the appropriate ``VaultAgentSidecarNode``.

        Topological order (depends_on):

            network → server → init → unseal → kv-setup
              ├── secret-sync
              └── per-principal: approle → approle-creds → vault-agent
                                  (vault-agent also depends on secret-sync)
        """
        from vystak_provider_docker.nodes import (
            AppRoleCredentialsNode,
            AppRoleNode,
            HashiVaultInitNode,
            HashiVaultServerNode,
            VaultAgentSidecarNode,
            VaultSecretSyncNode,
        )
        from vystak_provider_docker.vault_client import VaultClient

        cfg = self._vault.config or {}
        image = cfg.get("image", "hashicorp/vault:1.17")
        port = cfg.get("port", 8200)
        host_port = cfg.get("host_port")
        key_shares = cfg.get("seal_key_shares", 5)
        key_threshold = cfg.get("seal_key_threshold", 3)
        vault_address = f"http://vystak-vault:{port}"
        init_path = Path(".vystak/vault/init.json")

        # Server
        server = HashiVaultServerNode(
            client=self._client, image=image, port=port, host_port=host_port
        )
        graph.add(server)

        # Vault HTTP client (token set by kv-setup after init)
        # For deploy mode the server is reachable on localhost via host_port
        # (or, failing that, we connect over the Docker network by address
        # from inside the same network — but the init/unseal/kv ops run from
        # the host, so we use localhost:host_port when host_port is set).
        client_url = (
            f"http://localhost:{host_port}" if host_port else vault_address
        )
        vault_client = VaultClient(client_url)

        # Init — persists .vystak/vault/init.json (600)
        init_node = HashiVaultInitNode(
            vault_client=vault_client,
            key_shares=key_shares,
            key_threshold=key_threshold,
            init_path=init_path,
        )
        graph.add(init_node)
        graph.add_dependency(init_node.name, server.name)

        # Unseal — reads keys from init result at run time
        unseal_node = _LateBoundUnsealNode(
            vault_client=vault_client,
            init_node_name=init_node.name,
            key_threshold=key_threshold,
        )
        graph.add(unseal_node)
        graph.add_dependency(unseal_node.name, init_node.name)

        # KV v2 + approle-auth enable — reads root token from init result
        kv_setup = _LateBoundKvSetupNode(
            vault_client=vault_client,
            init_node_name=init_node.name,
        )
        graph.add(kv_setup)
        graph.add_dependency(kv_setup.name, unseal_node.name)

        # Collect principals from the agent tree
        principals: dict[str, list[str]] = {}
        agent = self._agent
        if agent and agent.secrets:
            principals[f"{agent.name}-agent"] = [s.name for s in agent.secrets]
        if (
            agent
            and agent.workspace is not None
            and agent.workspace.secrets
        ):
            principals[f"{agent.name}-workspace"] = [
                s.name for s in agent.workspace.secrets
            ]

        # Secret sync — pushes declared secrets from .env if absent in KV
        all_declared: list[str] = []
        for names in principals.values():
            all_declared.extend(names)
        sync = VaultSecretSyncNode(
            vault_client=vault_client,
            declared_secrets=all_declared,
            env_values=getattr(self, "_env_values", {}) or {},
            force=bool(getattr(self, "_force_sync", False)),
            allow_missing=bool(getattr(self, "_allow_missing", False)),
        )
        graph.add(sync)
        graph.add_dependency(sync.name, kv_setup.name)

        # Per-principal: approle → approle-creds → vault-agent
        result_map: dict[str, str] = {}
        for principal_name, secret_names in principals.items():
            approle = AppRoleNode(
                vault_client=vault_client,
                principal_name=principal_name,
                secret_names=secret_names,
            )
            graph.add(approle)
            graph.add_dependency(approle.name, kv_setup.name)

            creds = AppRoleCredentialsNode(
                client=self._client, principal_name=principal_name
            )
            graph.add(creds)
            graph.add_dependency(creds.name, approle.name)

            sidecar = VaultAgentSidecarNode(
                client=self._client,
                principal_name=principal_name,
                image=image,
                secret_names=secret_names,
                vault_address=vault_address,
            )
            graph.add(sidecar)
            graph.add_dependency(sidecar.name, creds.name)
            graph.add_dependency(sidecar.name, sync.name)

            result_map[principal_name] = sidecar.secrets_volume_name

        return result_map

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
                NatsServerNode,
            )

            graph = ProvisionGraph()

            # Network
            graph.add(DockerNetworkNode(self._client))

            # Transport-plugin wiring: if NATS is configured, provision the
            # broker container and thread its URL into the agent env.
            extra_env: dict[str, str] = {}
            transport = (
                self._agent.platform.transport if self._agent and self._agent.platform else None
            )
            if transport and transport.type == "nats":
                graph.add(NatsServerNode(self._client))
                extra_env["VYSTAK_TRANSPORT_TYPE"] = "nats"
                extra_env["VYSTAK_NATS_URL"] = "nats://vystak-nats:4222"
                if transport.config and getattr(transport.config, "subject_prefix", None):
                    extra_env["VYSTAK_NATS_SUBJECT_PREFIX"] = transport.config.subject_prefix

            # Services (sessions, memory, services list)
            for svc in self._all_services():
                if svc.engine in ("postgres", "sqlite"):
                    node = DockerServiceNode(self._client, svc, SECRETS_PATH)
                    graph.add(node)

            # HashiCorp Vault subgraph — only when vault.type == 'vault'
            vault_volume_map: dict[str, str] = {}
            if self._vault is not None:
                from vystak.schema.common import VaultType

                if self._vault.type is VaultType.VAULT:
                    vault_volume_map = self._add_vault_nodes(graph)

            # Agent container
            agent_node = DockerAgentNode(
                self._client,
                self._agent,
                self._generated_code,
                plan,
                peer_routes_json=peer_routes if peer_routes is not None else "{}",
                extra_env=extra_env,
            )
            agent_principal = (
                f"{self._agent.name}-agent" if self._agent is not None else None
            )
            if agent_principal and agent_principal in vault_volume_map:
                agent_node.set_vault_context(
                    secrets_volume_name=vault_volume_map[agent_principal]
                )
            graph.add(agent_node)
            # Main container depends on its sidecar being up so /shared has
            # credentials rendered before the entrypoint shim tries to load.
            if agent_principal and agent_principal in vault_volume_map:
                graph.add_dependency(
                    agent_node.name, f"vault-agent:{agent_principal}"
                )

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
            import json

            code = plugin.generate_code(channel, resolved_routes)

            from vystak.provisioning import ProvisionGraph

            from vystak_provider_docker.nodes import (
                DockerChannelNode,
                DockerNetworkNode,
                NatsServerNode,
            )

            host_port = channel.config.get("port", 8080)

            graph = ProvisionGraph()
            graph.add(DockerNetworkNode(self._client))

            # Transport wiring for channels. The channel server bootstraps
            # its own Transport from env just like the agents do.
            channel_extra_env: dict[str, str] = {
                "VYSTAK_ROUTES_JSON": json.dumps(resolved_routes, separators=(",", ":")),
            }
            transport = channel.platform.transport if channel.platform else None
            if transport and transport.type == "nats":
                graph.add(NatsServerNode(self._client))
                channel_extra_env["VYSTAK_TRANSPORT_TYPE"] = "nats"
                channel_extra_env["VYSTAK_NATS_URL"] = "nats://vystak-nats:4222"
                if transport.config and getattr(transport.config, "subject_prefix", None):
                    channel_extra_env["VYSTAK_NATS_SUBJECT_PREFIX"] = (
                        transport.config.subject_prefix
                    )

            channel_node = DockerChannelNode(
                self._client,
                channel,
                code,
                plan.target_hash,
                host_port=host_port,
                extra_env=channel_extra_env,
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
