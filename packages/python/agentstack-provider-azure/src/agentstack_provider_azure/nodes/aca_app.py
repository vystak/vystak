"""ContainerAppNode — builds, pushes, and deploys an agent as an Azure Container App."""

import os
import subprocess
from pathlib import Path

from agentstack.provisioning.health import HealthCheck, HttpHealthCheck, NoopHealthCheck
from agentstack.provisioning.node import Provisionable, ProvisionResult
from agentstack.providers.base import DeployPlan, GeneratedCode
from agentstack.schema.agent import Agent

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
    ):
        self._aca_client = aca_client
        self._docker_client = docker_client
        self._rg_name = rg_name
        self._agent = agent
        self._generated_code = generated_code
        self._plan = plan
        self._platform_config = platform_config
        self._fqdn: str | None = None

    @property
    def name(self) -> str:
        return "container-app"

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

            # ----------------------------------------------------------
            # 1. Write build files and Dockerfile
            # ----------------------------------------------------------
            build_dir = Path(".agentstack") / self._agent.name
            build_dir.mkdir(parents=True, exist_ok=True)
            for filename, content in self._generated_code.files.items():
                file_path = build_dir / filename
                file_path.parent.mkdir(parents=True, exist_ok=True)
                file_path.write_text(content)

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

            # Use docker buildx for cross-platform build + push in one step
            subprocess.run(
                ["docker", "login", login_server,
                 "--username", acr_username, "--password-stdin"],
                input=acr_password, text=True, check=True,
                capture_output=True,
            )
            result = subprocess.run(
                ["docker", "buildx", "build",
                 "--platform", "linux/amd64",
                 "--tag", image_tag,
                 "--push",
                 str(build_dir)],
                capture_output=True, text=True,
            )
            if result.returncode != 0:
                raise RuntimeError(f"Docker buildx failed: {result.stderr}")

            # ----------------------------------------------------------
            # 3. Collect secrets from environment
            # ----------------------------------------------------------
            aca_secrets: list[Secret] = [
                Secret(name="acr-password", value=acr_password),
            ]
            env_vars = []
            for secret in self._agent.secrets:
                secret_name = secret.name
                value = os.environ.get(secret_name)
                if value:
                    safe_name = secret_name.lower().replace("_", "-")
                    aca_secrets.append(Secret(name=safe_name, value=value))
                    env_vars.append({
                        "name": secret_name,
                        "secretRef": safe_name,
                    })

            # Inject extra env vars (gateway URL, peer URLs, etc.)
            for key, value in self._platform_config.get("env", {}).items():
                env_vars.append({"name": key, "value": value})

            # ----------------------------------------------------------
            # 4. Create Container App
            # ----------------------------------------------------------
            cfg = self._platform_config
            port = cfg.get("port", 8000)

            app = self._aca_client.container_apps.begin_create_or_update(
                self._rg_name,
                self._agent.name,
                ContainerApp(
                    location=cfg.get("location", "eastus2"),
                    tags={
                        "agentstack:managed": "true",
                        "agentstack:agent": self._agent.name,
                        "agentstack:hash": self._plan.target_hash,
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
