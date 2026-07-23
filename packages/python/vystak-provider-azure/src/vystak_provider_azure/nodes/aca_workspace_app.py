"""Workspace ACA app — standalone two-app pattern (port 22 internal TCP).

Mirrors the Docker workspace container but as a separate ACA app reachable
via internal DNS at <name>.internal.<env-default-domain>:22.
"""

from __future__ import annotations

from typing import Any

from vystak.provisioning import Provisionable, ProvisionResult

_SSH_ENV_MAP = {
    "host-key": "VYSTAK_SSH_HOST_KEY",
    "client-key-pub": "VYSTAK_SSH_AUTHORIZED_KEYS",
}


def _ssh_env_var_for_secret(secret_name: str) -> str | None:
    """Map a KV secret name → the env var the workspace shim consumes."""
    for kind, env in _SSH_ENV_MAP.items():
        if secret_name.endswith(f"-{kind}"):
            return env
    return None


def build_workspace_revision(
    *,
    agent_name: str,
    location: str,
    workspace_image: str,
    workspace_identity_resource_id: str,
    vault_uri: str,
    ssh_kv_secrets: list[str],
    user_secrets: list[str],
    acr_login_server: str,
    acr_password_secret_ref: str,
    acr_password_value: str,
    storage_name: str | None,
    share_subpath: str | None,
    persistence_mode: str,
) -> dict:
    """Construct the ACA revision body for a workspace app.

    persistence_mode: "volume" requires storage_name; "ephemeral" omits volumes.
    "bind" is rejected upstream by schema validator.
    """
    secrets_block: list[dict] = [
        {
            "name": s,
            "keyVaultUrl": f"{vault_uri}secrets/{s}",
            "identity": workspace_identity_resource_id,
        }
        for s in ssh_kv_secrets
    ]
    for s in user_secrets:
        secrets_block.append(
            {
                "name": s,
                "keyVaultUrl": f"{vault_uri}secrets/{s}",
                "identity": workspace_identity_resource_id,
            }
        )
    secrets_block.append(
        {"name": acr_password_secret_ref, "value": acr_password_value}
    )

    env: list[dict] = []
    for s in ssh_kv_secrets:
        env_var = _ssh_env_var_for_secret(s)
        if env_var is not None:
            env.append({"name": env_var, "secretRef": s})
    for s in user_secrets:
        env.append({"name": s, "secretRef": s})

    containers: list[dict[str, Any]] = [
        {
            "name": "workspace",
            "image": workspace_image,
            "env": env,
            "resources": {"cpu": 0.5, "memory": "1Gi"},
        }
    ]
    template: dict[str, Any] = {
        "containers": containers,
        "scale": {"minReplicas": 1, "maxReplicas": 1},
    }
    if persistence_mode == "volume":
        if storage_name is None or share_subpath is None:
            raise ValueError(
                "persistence='volume' requires storage_name and share_subpath"
            )
        template["volumes"] = [
            {
                "name": "workspace-data",
                "storageType": "AzureFile",
                "storageName": storage_name,
            }
        ]
        containers[0]["volumeMounts"] = [
            {"volumeName": "workspace-data", "mountPath": share_subpath}
        ]

    return {
        "location": location,
        "identity": {
            "type": "UserAssigned",
            "userAssignedIdentities": {workspace_identity_resource_id: {}},
        },
        "properties": {
            "configuration": {
                "secrets": secrets_block,
                "registries": [
                    {
                        "server": acr_login_server,
                        "username": acr_login_server.split(".")[0],
                        "passwordSecretRef": acr_password_secret_ref,
                    }
                ],
                "ingress": {
                    "external": False,
                    "transport": "tcp",
                    "targetPort": 22,
                    "exposedPort": 22,
                },
                "identitySettings": [
                    {
                        "identity": workspace_identity_resource_id,
                        "lifecycle": "None",
                    }
                ],
            },
            "template": template,
        },
    }


class ACAWorkspaceAppNode(Provisionable):
    """Build + push workspace image, then deploy workspace ACA app.

    Image build uses Docker SDK locally (reuses Docker provider's
    generate_workspace_dockerfile). Pushed to ACR. ACA app deployed via
    the management client.
    """

    def __init__(
        self,
        *,
        aca_client,
        docker_client,
        rg_name: str,
        env_name: str,
        agent,
        platform_config: dict,
        location: str,
        ssh_keygen_node_name: str,
        files_share_node_name: str | None,
        env_storage_node_name: str | None,
        acr_node_name: str,
        vault_node_name: str,
        workspace_identity_node_name: str,
    ) -> None:
        self._aca = aca_client
        self._docker = docker_client
        self._rg_name = rg_name
        self._env_name = env_name
        self._agent = agent
        self._platform_config = platform_config
        self._location = location
        self._ssh_keygen = ssh_keygen_node_name
        self._files_share = files_share_node_name
        self._env_storage = env_storage_node_name
        self._acr = acr_node_name
        self._vault = vault_node_name
        self._ws_identity = workspace_identity_node_name

    @property
    def name(self) -> str:
        return f"workspace-app-{self._agent.name}"

    @property
    def app_name(self) -> str:
        return f"vystak-{self._agent.name}-workspace"

    def provision(self, context: dict) -> ProvisionResult:
        # Resolve dependencies from context
        acr = context[self._acr].info
        vault = context[self._vault].info
        ws_identity = context[self._ws_identity].info

        # Build & push workspace image
        workspace_image = self._build_and_push_image(
            acr_login_server=acr["login_server"],
            acr_username=acr["login_server"].split(".")[0],
            acr_password=acr["admin_password"],
        )

        # Compose KV secret names
        ssh_kv_secrets = [
            f"vystak-workspace-ssh-{self._agent.name}-host-key",
            f"vystak-workspace-ssh-{self._agent.name}-client-key-pub",
        ]
        user_secrets = [s.name for s in (self._agent.workspace.secrets or [])]

        storage_name = (
            None
            if self._env_storage is None
            else context[self._env_storage].info["storage_name"]
        )
        share_subpath = (
            "/workspace" if self._agent.workspace.persistence == "volume" else None
        )

        body = build_workspace_revision(
            agent_name=self._agent.name,
            location=self._location,
            workspace_image=workspace_image,
            workspace_identity_resource_id=ws_identity["resource_id"],
            vault_uri=vault["vault_uri"],
            ssh_kv_secrets=ssh_kv_secrets,
            user_secrets=user_secrets,
            acr_login_server=acr["login_server"],
            acr_password_secret_ref="acr-password",
            acr_password_value=acr["admin_password"],
            storage_name=storage_name,
            share_subpath=share_subpath,
            persistence_mode=self._agent.workspace.persistence,
        )

        poller = self._aca.container_apps.begin_create_or_update(
            resource_group_name=self._rg_name,
            container_app_name=self.app_name,
            container_app_envelope=body,
        )
        result = poller.result()

        env_default_domain = context["aca-environment"].info[
            "default_domain"
        ]
        workspace_host = f"{self.app_name}.internal.{env_default_domain}"

        return ProvisionResult(
            name=self.name,
            success=True,
            info={
                "app_name": self.app_name,
                "workspace_host": workspace_host,
                "image": workspace_image,
                "fqdn": getattr(result, "configuration", None),
            },
        )

    def _build_and_push_image(
        self,
        *,
        acr_login_server: str,
        acr_username: str,
        acr_password: str,
    ) -> str:
        """Reuse Docker provider's dockerfile generator + workspace_rpc bundle.

        Builds locally via the Docker SDK, tags ``<acr>/vystak-<agent>-workspace:latest``,
        and pushes to ACR. Layer cache (local Docker) speeds up rebuilds when the
        Dockerfile + bundle are unchanged. A content-hash tagging strategy can be
        layered on later if ACR pull churn becomes painful.
        """
        import shutil
        from pathlib import Path

        from vystak_provider_docker.templates import generate_entrypoint_shim
        from vystak_provider_docker.workspace_image import (
            generate_workspace_dockerfile,
        )

        ws = self._agent.workspace
        build_dir = Path(".vystak") / f"{self._agent.name}-workspace-azure"
        build_dir.mkdir(parents=True, exist_ok=True)

        if ws.dockerfile:
            shutil.copy(Path(ws.dockerfile).resolve(), build_dir / "Dockerfile")
        else:
            df = generate_workspace_dockerfile(
                image=ws.image,
                provision=ws.provision,
                copy=ws.copy,
                tool_deps_manager=ws.tool_deps_manager,
                use_entrypoint_shim=True,
            )
            (build_dir / "Dockerfile").write_text(df)

        (build_dir / "entrypoint-shim.sh").write_text(generate_entrypoint_shim())

        import vystak_workspace_rpc

        rpc_src = Path(vystak_workspace_rpc.__file__).parent
        rpc_dst = build_dir / "vystak_workspace_rpc"
        if rpc_dst.exists():
            shutil.rmtree(rpc_dst)
        shutil.copytree(rpc_src, rpc_dst)
        from vystak_workspace_rpc.build_files import setup_py_path

        shutil.copy(setup_py_path(), build_dir / "setup.py")

        image_tag = (
            f"{acr_login_server}/vystak-{self._agent.name}-workspace:latest"
        )
        self._docker.login(
            registry=acr_login_server,
            username=acr_username,
            password=acr_password,
        )
        self._docker.images.build(path=str(build_dir), tag=image_tag, rm=True)
        for line in self._docker.images.push(image_tag, stream=True, decode=True):
            if line.get("error"):
                raise RuntimeError(f"Push failed: {line['error']}")
        return image_tag
