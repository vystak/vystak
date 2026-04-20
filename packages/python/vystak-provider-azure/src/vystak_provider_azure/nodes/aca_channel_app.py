"""AzureChannelAppNode — builds, pushes, and deploys a channel as an Azure Container App."""

import hashlib
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
from vystak.schema.channel import Channel


def _channel_app_name(channel_name: str) -> str:
    """Azure container app name for a channel; prefixed to avoid collision with agents."""
    return f"channel-{channel_name}"


class AzureChannelAppNode(Provisionable):
    """Builds a channel image, pushes to ACR, and creates an Azure Container App."""

    def __init__(
        self,
        aca_client,
        docker_client,
        rg_name: str,
        channel: Channel,
        generated_code: GeneratedCode,
        plan: DeployPlan,
        platform_config: dict,
    ):
        self._aca_client = aca_client
        self._docker_client = docker_client
        self._rg_name = rg_name
        self._channel = channel
        self._generated_code = generated_code
        self._plan = plan
        self._platform_config = platform_config
        self._fqdn: str | None = None

        # Vault-backed deploy context (set via set_vault_context). When
        # _vault_key is None, provision() takes the env-passthrough path.
        self._vault_key: str | None = None
        self._identity_key: str | None = None
        self._vault_secrets: list[str] = []

    def set_vault_context(
        self,
        *,
        vault_key: str,
        identity_key: str,
        secrets: list[str],
    ) -> None:
        """Switch this channel node into vault-backed mode.

        When set, provision() routes revision construction through the
        build_revision_for_vault helper so channel secrets are wired as
        per-container `secretRef` entries against a `lifecycle: None` UAMI.
        """
        self._vault_key = vault_key
        self._identity_key = identity_key
        self._vault_secrets = list(secrets)

    def _build_body(self, context: dict, acr_info: dict) -> dict:
        """Build the ACA revision body when in vault-backed mode.

        Channels have exactly one container and one UAMI. The body is
        shaped like build_revision_for_vault's output but sized for a
        single container — all declared secrets belong to the channel
        itself, no sidecar.
        """
        assert self._vault_key is not None, (
            "_build_body called without vault context; use legacy path"
        )
        vault_info = context[self._vault_key].info
        id_info = context[self._identity_key].info
        vault_uri = vault_info["vault_uri"]
        identity_resource_id = id_info["resource_id"]

        from vystak_provider_azure.nodes.aca_app import _kv_secret_name

        app_name = _channel_app_name(self._channel.name)
        login_server = acr_info["login_server"]
        acr_password_value = acr_info["password"]
        acr_password_secret_ref = "acr-password"
        image_tag = (
            acr_info.get("image")
            or f"{login_server}/{app_name}:{self._plan.target_hash}"
        )
        channel_port = int(self._channel.config.get("port", 8080))

        kv_secrets_block: list[dict] = [
            {
                "name": _kv_secret_name(s),
                "keyVaultUrl": f"{vault_uri}secrets/{s}",
                "identity": identity_resource_id,
            }
            for s in self._vault_secrets
        ]
        kv_secrets_block.append(
            {"name": acr_password_secret_ref, "value": acr_password_value}
        )

        identity_settings: list[dict] = [
            {"identity": identity_resource_id, "lifecycle": "None"},
        ]

        channel_env: list[dict] = [
            {"name": s, "secretRef": _kv_secret_name(s)} for s in self._vault_secrets
        ]
        channel_env.append({"name": "PORT", "value": str(channel_port)})

        containers: list[dict] = [
            {
                "name": app_name,
                "image": image_tag,
                "env": channel_env,
            }
        ]

        return {
            "location": None,  # Caller fills from platform config
            "identity": {
                "type": "UserAssigned",
                "userAssignedIdentities": {identity_resource_id: {}},
            },
            "properties": {
                "configuration": {
                    "identitySettings": identity_settings,
                    "secrets": kv_secrets_block,
                    "registries": [
                        {
                            "server": login_server,
                            "username": login_server.split(".")[0],
                            "passwordSecretRef": acr_password_secret_ref,
                        }
                    ],
                    "ingress": {
                        "external": True,
                        "targetPort": channel_port,
                        "transport": "auto",
                    },
                },
                "template": {
                    "containers": containers,
                    "scale": {"minReplicas": 1, "maxReplicas": 1},
                },
            },
        }

    @property
    def name(self) -> str:
        return f"channel-app:{self._channel.name}"

    @property
    def depends_on(self) -> list[str]:
        return ["aca-environment", "acr"]

    def provision(self, context: dict) -> ProvisionResult:
        try:
            acr_info = context["acr"].info
            env_info = context["aca-environment"].info

            login_server = acr_info["login_server"]
            acr_username = acr_info["username"]
            acr_password = acr_info["password"]

            app_name = _channel_app_name(self._channel.name)

            # ----------------------------------------------------------
            # 1. Write build files and Dockerfile
            # ----------------------------------------------------------
            build_dir = Path(".vystak") / "channels" / self._channel.name
            build_dir.mkdir(parents=True, exist_ok=True)
            for filename, content in self._generated_code.files.items():
                file_path = build_dir / filename
                file_path.parent.mkdir(parents=True, exist_ok=True)
                file_path.write_text(content)

            # The channel's own Dockerfile (shipped in generated_code) is Docker-local
            # friendly (no --platform). Azure needs linux/amd64 explicitly, so rewrite
            # the FROM line in the emitted Dockerfile to enforce it.
            dockerfile = build_dir / "Dockerfile"
            content = dockerfile.read_text()
            content = content.replace(
                "FROM python:3.11-slim",
                "FROM --platform=linux/amd64 python:3.11-slim",
                1,
            )
            dockerfile.write_text(content)

            # ----------------------------------------------------------
            # 2. Build and push Docker image to ACR
            # ----------------------------------------------------------
            # Include a hash of the plugin's generated code in the image tag so
            # ACA sees a new revision when the plugin's server template changes
            # even if the Channel's own hash (config/routes) stays the same.
            items = sorted(self._generated_code.files.items())
            code_digest = hashlib.sha256(
                "\n".join(f"{name}:{content}" for name, content in items).encode()
            ).hexdigest()[:12]
            image_tag = (
                f"{login_server}/channel-{self._channel.name}"
                f":{self._plan.target_hash[:16]}-{code_digest}"
            )

            self.emit("Building channel image", "linux/amd64")
            subprocess.run(
                ["docker", "login", login_server, "--username", acr_username, "--password-stdin"],
                input=acr_password,
                text=True,
                check=True,
                capture_output=True,
            )
            result = subprocess.run(
                [
                    "docker",
                    "buildx",
                    "build",
                    "--platform",
                    "linux/amd64",
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
            for secret in self._channel.secrets:
                secret_name = secret.name
                value = os.environ.get(secret_name)
                if value:
                    safe_name = secret_name.lower().replace("_", "-")
                    aca_secrets.append(Secret(name=safe_name, value=value))
                    env_vars.append(
                        {
                            "name": secret_name,
                            "secretRef": safe_name,
                        }
                    )

            # Channel.config may define a container PORT (defaults to 8080)
            channel_port = int(self._channel.config.get("port", 8080))
            env_vars.append({"name": "PORT", "value": str(channel_port)})

            # ----------------------------------------------------------
            # 4. Create Container App
            # ----------------------------------------------------------
            self.emit("Creating Channel App", app_name)
            cfg = self._platform_config

            app = self._aca_client.container_apps.begin_create_or_update(
                self._rg_name,
                app_name,
                ContainerApp(
                    location=cfg.get("location", "eastus2"),
                    tags={
                        "vystak:managed": "true",
                        "vystak:channel": self._channel.name,
                        "vystak:channel-type": self._channel.type.value,
                        "vystak:channel-hash": self._plan.target_hash,
                    },
                    managed_environment_id=env_info["environment_id"],
                    configuration=Configuration(
                        ingress=Ingress(
                            external=cfg.get("ingress_external", True),
                            target_port=channel_port,
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
                                name=app_name,
                                image=image_tag,
                                resources=ContainerResources(
                                    cpu=float(cfg.get("channel_cpu", 0.25)),
                                    memory=cfg.get("channel_memory", "0.5Gi"),
                                ),
                                env=env_vars or None,
                            ),
                        ],
                        scale=Scale(
                            min_replicas=cfg.get("channel_min_replicas", 1),
                            max_replicas=cfg.get("channel_max_replicas", 1),
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
                    "app_name": app_name,
                },
            )
        except Exception as e:
            return ProvisionResult(name=self.name, success=False, error=str(e))

    def health_check(self) -> HealthCheck:
        if self._fqdn:
            return HttpHealthCheck(f"https://{self._fqdn}/health")
        return NoopHealthCheck()
