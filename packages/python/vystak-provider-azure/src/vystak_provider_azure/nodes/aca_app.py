"""ContainerAppNode — builds, pushes, and deploys an agent as an Azure Container App."""

import os
import subprocess
from pathlib import Path

from azure.mgmt.appcontainers.models import (
    Configuration,
    Container,
    ContainerApp,
    ContainerResources,
    Ingress,
    RegistryCredentials,
    Scale,
    Secret,
    Template,
)
from vystak.providers.base import DeployPlan, GeneratedCode
from vystak.provisioning.health import HealthCheck, HttpHealthCheck, NoopHealthCheck
from vystak.provisioning.node import Provisionable, ProvisionResult
from vystak.schema.agent import Agent


def _kv_secret_name(raw: str) -> str:
    """Normalize a declared secret name to ACA's `[a-z0-9][a-z0-9-]*` shape."""
    return raw.lower().replace("_", "-")


def build_revision_default_path(
    *,
    agent,
    model_secrets: dict[str, str],
    workspace_secrets: dict[str, str],
    acr_login_server: str,
    acr_password_secret_ref: str,
    acr_password_value: str,
    agent_image: str,
    workspace_image: str | None,
    extra_env: list[dict] | None = None,
) -> dict:
    """Build the ACA revision body for the default (no-Vault) delivery path.

    Values from ``model_secrets`` land only in the agent container's env via
    per-container ``secretRef``. Values from ``workspace_secrets`` land only
    in the workspace container's env (when present). Values are inline in
    ``configuration.secrets[]`` — no UAMI, no ``lifecycle:None``.

    Mirror of ``build_revision_for_vault`` minus the UAMI/KV plumbing. The
    per-container isolation invariant is preserved: the agent container's
    env table never contains workspace-scoped secrets, and vice versa.

    Args:
        model_secrets: ``{declared_name → value}`` — resolved at apply time
            from ``os.environ`` / ``.env`` for the agent principal.
        workspace_secrets: same shape for the workspace principal.
    """
    # Cross-principal name collisions would silently deliver the agent's
    # value to the workspace container (both share the same secretRef into
    # the same inline pool), violating per-container isolation even when
    # the env scoping looks correct. Reject explicitly.
    model_keys = {_kv_secret_name(n) for n in model_secrets}
    workspace_keys = {_kv_secret_name(n) for n in workspace_secrets}
    collisions = model_keys & workspace_keys
    if collisions:
        raise ValueError(
            f"Secret name collision between agent and workspace principals "
            f"(normalized ACA names: {sorted(collisions)}). On the default "
            f"(inline-secret) path both principals resolve secretRef through "
            f"the same pool, so the workspace container would silently receive "
            f"the agent's value. Use distinct secret names per principal."
        )

    # Sidecar is emitted only when both image + workspace_secrets are present.
    # Drop workspace secrets from the pool when no sidecar will reference
    # them — no point transmitting values with no consumer.
    emit_workspace_sidecar = workspace_image is not None and bool(workspace_secrets)

    # Revision-level secrets pool: inline values, one per declared secret
    # across both principals. ACA secret names must match [a-z0-9][a-z0-9-]*.
    inline_secrets: list[dict] = []
    seen: set[str] = set()
    for name, value in model_secrets.items():
        safe = _kv_secret_name(name)
        if safe in seen:
            continue
        seen.add(safe)
        inline_secrets.append({"name": safe, "value": value})
    if emit_workspace_sidecar:
        for name, value in workspace_secrets.items():
            safe = _kv_secret_name(name)
            if safe in seen:
                continue
            seen.add(safe)
            inline_secrets.append({"name": safe, "value": value})
    inline_secrets.append(
        {"name": acr_password_secret_ref, "value": acr_password_value}
    )

    # Agent container: env references only model secrets
    agent_env: list[dict] = [
        {"name": name, "secretRef": _kv_secret_name(name)}
        for name in model_secrets
    ]
    if emit_workspace_sidecar:
        agent_env.append(
            {"name": "VYSTAK_WORKSPACE_RPC_URL", "value": "http://localhost:50051"}
        )
    if extra_env:
        agent_env.extend(extra_env)

    containers: list[dict] = [
        {
            "name": "agent",
            "image": agent_image,
            "env": agent_env,
        }
    ]

    # Workspace sidecar container — only when image + workspace secrets provided
    if emit_workspace_sidecar:
        ws_env: list[dict] = [
            {"name": name, "secretRef": _kv_secret_name(name)}
            for name in workspace_secrets
        ]
        ws_env.append({"name": "VYSTAK_WORKSPACE_RPC_PORT", "value": "50051"})
        containers.append(
            {
                "name": "workspace",
                "image": workspace_image,
                "env": ws_env,
                "resources": {"cpu": 0.5, "memory": "1Gi"},
            }
        )

    revision: dict = {
        "location": None,  # Caller fills from platform config
        "properties": {
            "configuration": {
                "secrets": inline_secrets,
                "registries": [
                    {
                        "server": acr_login_server,
                        "username": acr_login_server.split(".")[0],
                        "passwordSecretRef": acr_password_secret_ref,
                    }
                ],
                "ingress": {
                    "external": True,
                    "targetPort": 8000,
                    "transport": "auto",
                },
            },
            "template": {
                "containers": containers,
                "scale": {"minReplicas": 1, "maxReplicas": 10},
            },
        },
    }
    return revision


def build_revision_for_vault(
    *,
    agent,
    vault_uri: str,
    agent_identity_resource_id: str,
    agent_identity_client_id: str | None,
    workspace_identity_resource_id: str | None,
    workspace_identity_client_id: str | None,
    model_secrets: list[str],
    workspace_secrets: list[str],
    acr_login_server: str,
    acr_password_secret_ref: str,
    acr_password_value: str,
    agent_image: str,
    workspace_image: str | None,
    extra_env: list[dict] | None = None,
) -> dict:
    """Build the ACA revision body for a vault-backed agent (optional workspace sidecar).

    Uses per-container env[].secretRef and identitySettings[].lifecycle: None
    so neither container can acquire a token for any UAMI from its own
    process. Workspace secrets are wired into the workspace container's env
    only; model secrets into the agent container's env only.
    """
    # Collect user-assigned identity resource IDs
    user_assigned_identities: dict = {
        agent_identity_resource_id: {},
    }
    if workspace_identity_resource_id:
        user_assigned_identities[workspace_identity_resource_id] = {}

    # Sidecar is emitted only when both image + workspace_secrets are present.
    # Drop workspace KV refs from the block when no sidecar will reference
    # them — no point transmitting refs with no consumer.
    emit_workspace_sidecar = (
        workspace_image is not None and bool(workspace_secrets)
    )

    # Build KV-backed secrets list: one entry per secret, referencing the
    # owning UAMI. ACA secret names must match [a-z0-9][a-z0-9-]*.
    kv_secrets_block: list[dict] = []
    for s in model_secrets:
        kv_secrets_block.append(
            {
                "name": _kv_secret_name(s),
                "keyVaultUrl": f"{vault_uri}secrets/{_kv_secret_name(s)}",
                "identity": agent_identity_resource_id,
            }
        )
    if emit_workspace_sidecar:
        for s in workspace_secrets:
            kv_secrets_block.append(
                {
                    "name": _kv_secret_name(s),
                    "keyVaultUrl": f"{vault_uri}secrets/{_kv_secret_name(s)}",
                    "identity": workspace_identity_resource_id,
                }
            )
    kv_secrets_block.append(
        {"name": acr_password_secret_ref, "value": acr_password_value}
    )

    # Identity settings — all UAMIs are lifecycle: None (unreachable from code)
    identity_settings: list[dict] = [
        {"identity": agent_identity_resource_id, "lifecycle": "None"},
    ]
    if workspace_identity_resource_id:
        identity_settings.append(
            {"identity": workspace_identity_resource_id, "lifecycle": "None"}
        )

    # Agent container: env wired for model secrets only
    agent_env: list[dict] = [
        {"name": s, "secretRef": _kv_secret_name(s)} for s in model_secrets
    ]
    if emit_workspace_sidecar:
        # Match the default-path helper — only inject the RPC URL when a
        # sidecar will actually exist to respond on localhost:50051.
        # Previously gated on workspace_identity_resource_id alone, which
        # could inject a URL pointing at a non-existent service when a
        # caller provided the UAMI but no workspace_image/secrets.
        agent_env.append(
            {"name": "VYSTAK_WORKSPACE_RPC_URL", "value": "http://localhost:50051"}
        )
    if extra_env:
        agent_env.extend(extra_env)

    containers: list[dict] = [
        {
            "name": "agent",
            "image": agent_image,
            "env": agent_env,
        }
    ]

    if emit_workspace_sidecar:
        ws_env: list[dict] = [
            {"name": s, "secretRef": _kv_secret_name(s)} for s in workspace_secrets
        ]
        ws_env.append({"name": "VYSTAK_WORKSPACE_RPC_PORT", "value": "50051"})
        containers.append(
            {
                "name": "workspace",
                "image": workspace_image,
                "env": ws_env,
                "resources": {"cpu": 0.5, "memory": "1Gi"},
            }
        )

    revision: dict = {
        "location": None,  # Caller fills from platform config
        "identity": {
            "type": "UserAssigned",
            "userAssignedIdentities": user_assigned_identities,
        },
        "properties": {
            "configuration": {
                "identitySettings": identity_settings,
                "secrets": kv_secrets_block,
                "registries": [
                    {
                        "server": acr_login_server,
                        "username": acr_login_server.split(".")[0],
                        "passwordSecretRef": acr_password_secret_ref,
                    }
                ],
                "ingress": {
                    "external": True,
                    "targetPort": 8000,
                    "transport": "auto",
                },
            },
            "template": {
                "containers": containers,
                "scale": {"minReplicas": 1, "maxReplicas": 10},
            },
        },
    }
    return revision


class ContainerAppNode(Provisionable):
    """Builds a Docker image, pushes to ACR, and creates an Azure Container App."""

    def __init__(
        self,
        aca_client,
        docker_client,
        rg_name: str,
        agent: Agent,
        generated_code: GeneratedCode,
        plan: DeployPlan,
        platform_config: dict,
        peer_routes_json: str = "{}",
        env_values: dict[str, str] | None = None,
    ):
        self._aca_client = aca_client
        self._docker_client = docker_client
        self._rg_name = rg_name
        self._agent = agent
        self._generated_code = generated_code
        self._plan = plan
        self._platform_config = platform_config
        self._peer_routes_json = peer_routes_json
        # Fallback for secret values when os.environ doesn't have them —
        # CLI threads .env contents in here so agents work without
        # exporting every secret to the apply shell.
        self._env_values = dict(env_values or {})
        self._fqdn: str | None = None

        # Vault-backed deploy context (set via set_vault_context). When
        # _vault_key is None, provision() takes the env-passthrough path.
        self._vault_key: str | None = None
        self._agent_identity_key: str | None = None
        self._workspace_identity_key: str | None = None
        self._vault_model_secrets: list[str] = []
        self._vault_workspace_secrets: list[str] = []
        self._workspace_image: str | None = None

    def set_vault_context(
        self,
        *,
        vault_key: str,
        agent_identity_key: str,
        workspace_identity_key: str | None,
        model_secrets: list[str],
        workspace_secrets: list[str],
        workspace_image: str | None = None,
    ) -> None:
        """Switch this node into vault-backed mode.

        When set, provision() routes revision construction through
        build_revision_for_vault (per-container secretRef + lifecycle:None
        UAMIs). When unset, provision() uses the legacy env-passthrough path
        that reads secret values from os.environ at apply time.
        """
        self._vault_key = vault_key
        self._agent_identity_key = agent_identity_key
        self._workspace_identity_key = workspace_identity_key
        self._vault_model_secrets = list(model_secrets)
        self._vault_workspace_secrets = list(workspace_secrets)
        self._workspace_image = workspace_image

    def _build_body(self, context: dict, acr_info: dict) -> dict:
        """Build the ACA revision body when in vault-backed mode.

        Returns a dict compatible with build_revision_for_vault. Callers
        should only invoke this when _vault_key is set.
        """
        assert self._vault_key is not None, (
            "_build_body called without vault context; use legacy path"
        )
        vault_info = context[self._vault_key].info
        agent_id_info = context[self._agent_identity_key].info
        ws_id_info: dict = {}
        if self._workspace_identity_key is not None:
            ws_id_info = context[self._workspace_identity_key].info

        login_server = acr_info["login_server"]
        agent_image = (
            acr_info.get("image")
            or f"{login_server}/{self._agent.name}:{self._plan.target_hash}"
        )
        # Derive a default workspace image when the caller declared a
        # workspace identity but didn't pre-specify the image tag. The
        # workspace sidecar only materializes when both the image and
        # workspace_secrets are present in build_revision_for_vault.
        workspace_image = self._workspace_image
        if (
            workspace_image is None
            and self._workspace_identity_key is not None
            and self._vault_workspace_secrets
        ):
            workspace_image = (
                f"{login_server}/{self._agent.name}-workspace:{self._plan.target_hash}"
            )

        return build_revision_for_vault(
            agent=self._agent,
            vault_uri=vault_info["vault_uri"],
            agent_identity_resource_id=agent_id_info["resource_id"],
            agent_identity_client_id=agent_id_info.get("client_id"),
            workspace_identity_resource_id=ws_id_info.get("resource_id"),
            workspace_identity_client_id=ws_id_info.get("client_id"),
            model_secrets=self._vault_model_secrets,
            workspace_secrets=self._vault_workspace_secrets,
            acr_login_server=login_server,
            acr_password_secret_ref="acr-password",
            acr_password_value=acr_info["password"],
            agent_image=agent_image,
            workspace_image=workspace_image,
        )

    @property
    def name(self) -> str:
        return "container-app"

    @property
    def depends_on(self) -> list[str]:
        deps = ["aca-environment", "acr"]
        if (
            hasattr(self._agent, "sessions")
            and self._agent.sessions
            and self._agent.sessions.is_managed
        ):
            deps.append(self._agent.sessions.name)
        if (
            hasattr(self._agent, "memory")
            and self._agent.memory
            and self._agent.memory.is_managed
            and self._agent.memory.name not in deps
        ):
            deps.append(self._agent.memory.name)
        return deps

    def provision(self, context: dict) -> ProvisionResult:
        try:
            acr_info = context["acr"].info
            env_info = context["aca-environment"].info

            login_server = acr_info["login_server"]
            acr_username = acr_info["username"]
            acr_password = acr_info["password"]

            # ----------------------------------------------------------
            # 1. Write build files and Dockerfile
            # ----------------------------------------------------------
            build_dir = Path(".vystak") / self._agent.name
            build_dir.mkdir(parents=True, exist_ok=True)
            for filename, content in self._generated_code.files.items():
                file_path = build_dir / filename
                file_path.parent.mkdir(parents=True, exist_ok=True)
                file_path.write_text(content)

            # Bundle OpenAI-compatible schema types for deployment
            import vystak.schema.openai as _openai_schema

            _openai_src = Path(_openai_schema.__file__)
            if _openai_src.exists():
                (build_dir / "openai_types.py").write_text(_openai_src.read_text())

            # Bundle unpublished vystak + transport sources onto the container's
            # PYTHONPATH (via COPY . . in the Dockerfile). Mirrors what the
            # docker provider does — without this, containers fail at import
            # with "No module named 'vystak'".
            import shutil as _shutil

            import vystak
            import vystak_transport_http
            import vystak_transport_nats

            for _mod in (vystak, vystak_transport_http, vystak_transport_nats):
                _src = Path(_mod.__file__).parent
                _dst = build_dir / _src.name
                if _dst.exists():
                    _shutil.rmtree(_dst)
                _shutil.copytree(_src, _dst)

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
                "FROM --platform=linux/amd64 python:3.11-slim\n"
                "WORKDIR /app\n"
                f"{node_install}"
                f"{mcp_installs}"
                "COPY requirements.txt .\n"
                "RUN pip install --no-cache-dir -r requirements.txt\n"
                "COPY . .\n"
                f'CMD ["python", "{self._generated_code.entrypoint}"]\n'
            )
            (build_dir / "Dockerfile").write_text(dockerfile_content)

            # ----------------------------------------------------------
            # 2. Build and push Docker image to ACR
            # ----------------------------------------------------------
            image_tag = f"{login_server}/{self._agent.name}:{self._plan.target_hash}"

            self.emit("Building image", "linux/amd64")
            subprocess.run(
                ["docker", "login", login_server, "--username", acr_username, "--password-stdin"],
                input=acr_password,
                text=True,
                check=True,
                capture_output=True,
            )
            # Per-agent cache image: layers from prior builds (vystak source
            # bundling, pip install, etc.) are restored from registry. First
            # build seeds the cache; subsequent builds with the same Dockerfile
            # base + requirements skip straight to the changed layers. ``mode=max``
            # exports intermediate layers, not just the final-stage ones.
            cache_ref = f"{login_server}/{self._agent.name}:buildcache"
            result = subprocess.run(
                [
                    "docker",
                    "buildx",
                    "build",
                    "--platform",
                    "linux/amd64",
                    "--cache-from",
                    f"type=registry,ref={cache_ref}",
                    "--cache-to",
                    f"type=registry,ref={cache_ref},mode=max",
                    "--tag",
                    image_tag,
                    "--push",
                    str(build_dir),
                ],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                raise RuntimeError(f"Docker buildx failed: {result.stderr}")
            self.emit("Pushed to ACR", login_server)

            # ----------------------------------------------------------
            # 3. Collect secrets from environment
            # ----------------------------------------------------------
            aca_secrets: list[Secret] = [
                Secret(name="acr-password", value=acr_password),
            ]
            env_vars = []
            for secret in self._agent.secrets:
                secret_name = secret.name
                value = os.environ.get(secret_name) or self._env_values.get(secret_name)
                if value:
                    safe_name = secret_name.lower().replace("_", "-")
                    aca_secrets.append(Secret(name=safe_name, value=value))
                    env_vars.append(
                        {
                            "name": secret_name,
                            "secretRef": safe_name,
                        }
                    )

            # Inject extra env vars (gateway URL, peer URLs, etc.)
            for key, value in self._platform_config.get("env", {}).items():
                env_vars.append({"name": key, "value": value})

            # Inject transport bootstrap vars so the server picks up the right transport type
            env_vars.append(
                {"name": "VYSTAK_TRANSPORT_TYPE", "value": self._agent.platform.transport.type}
            )
            env_vars.append({"name": "VYSTAK_ROUTES_JSON", "value": self._peer_routes_json})

            # Inject database connection strings from upstream Postgres nodes
            if hasattr(self._agent, "sessions") and self._agent.sessions:
                svc = self._agent.sessions
                if svc.connection_string_env:
                    # Bring-your-own: pass the env var name through
                    env_vars.append(
                        {"name": "SESSION_STORE_URL", "value": f"${{{svc.connection_string_env}}}"}
                    )
                else:
                    pg_result = context.get(svc.name)
                    if pg_result and pg_result.info.get("connection_string"):
                        safe = "session-store-url"
                        aca_secrets.append(
                            Secret(name=safe, value=pg_result.info["connection_string"])
                        )
                        env_vars.append({"name": "SESSION_STORE_URL", "secretRef": safe})

            if hasattr(self._agent, "memory") and self._agent.memory:
                svc = self._agent.memory
                if svc.connection_string_env:
                    env_vars.append(
                        {"name": "MEMORY_STORE_URL", "value": f"${{{svc.connection_string_env}}}"}
                    )
                else:
                    pg_result = context.get(svc.name)
                    if pg_result and pg_result.info.get("connection_string"):
                        safe = "memory-store-url"
                        aca_secrets.append(
                            Secret(name=safe, value=pg_result.info["connection_string"])
                        )
                        env_vars.append({"name": "MEMORY_STORE_URL", "secretRef": safe})

            # ----------------------------------------------------------
            # 4. Create Container App
            # ----------------------------------------------------------
            self.emit("Creating Container App", self._agent.name)
            cfg = self._platform_config
            port = cfg.get("port", 8000)

            app = self._aca_client.container_apps.begin_create_or_update(
                self._rg_name,
                self._agent.name,
                ContainerApp(
                    location=cfg.get("location", "eastus2"),
                    tags={
                        "vystak:managed": "true",
                        "vystak:agent": self._agent.name,
                        "vystak:hash": self._plan.target_hash,
                    },
                    managed_environment_id=env_info["environment_id"],
                    configuration=Configuration(
                        ingress=Ingress(
                            external=cfg.get("ingress_external", True),
                            target_port=port,
                        ),
                        secrets=aca_secrets,
                        registries=[
                            RegistryCredentials(
                                server=login_server,
                                username=acr_username,
                                password_secret_ref="acr-password",
                            ),
                        ],
                    ),
                    template=Template(
                        containers=[
                            Container(
                                name=self._agent.name,
                                image=image_tag,
                                resources=ContainerResources(
                                    cpu=float(cfg.get("cpu", 0.5)),
                                    memory=cfg.get("memory", "1Gi"),
                                ),
                                env=env_vars or None,
                            ),
                        ],
                        scale=Scale(
                            min_replicas=cfg.get("min_replicas", 0),
                            max_replicas=cfg.get("max_replicas", 3),
                        ),
                    ),
                ),
            ).result()

            self._fqdn = app.configuration.ingress.fqdn
            url = f"https://{self._fqdn}"

            return ProvisionResult(
                name=self.name,
                success=True,
                info={
                    "fqdn": self._fqdn,
                    "url": url,
                    "app_name": self._agent.name,
                },
            )
        except Exception as e:
            return ProvisionResult(name=self.name, success=False, error=str(e))

    def health_check(self) -> HealthCheck:
        if self._fqdn:
            return HttpHealthCheck(f"https://{self._fqdn}/health")
        return NoopHealthCheck()
