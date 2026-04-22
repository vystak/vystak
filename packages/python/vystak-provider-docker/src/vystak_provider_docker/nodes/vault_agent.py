"""VaultAgentSidecarNode — one per principal. Vault Agent container that
authenticates via AppRole and templates secrets.env into a per-principal
shared volume."""

from pathlib import Path

import docker.errors
from vystak.provisioning.node import Provisionable, ProvisionResult

from vystak_provider_docker.templates import generate_agent_hcl


class VaultAgentSidecarNode(Provisionable):
    """Per-principal Vault Agent. Renders /shared/secrets.env continuously."""

    def __init__(
        self,
        *,
        client,
        principal_name: str,
        image: str,
        secret_names: list[str],
        vault_address: str,
    ):
        self._client = client
        self._principal_name = principal_name
        self._image = image
        self._secret_names = list(secret_names)
        self._vault_address = vault_address

    @property
    def container_name(self) -> str:
        return f"vystak-{self._principal_name}-vault-agent"

    @property
    def secrets_volume_name(self) -> str:
        return f"vystak-{self._principal_name}-secrets"

    @property
    def name(self) -> str:
        return f"vault-agent:{self._principal_name}"

    @property
    def depends_on(self) -> list[str]:
        return [
            f"approle-creds:{self._principal_name}",
            "hashi-vault:secret-sync",
        ]

    def provision(self, context: dict) -> ProvisionResult:
        network = context["network"].info["network"]
        approle_volume = context[f"approle-creds:{self._principal_name}"].info[
            "volume_name"
        ]

        # Ensure the secrets volume exists (main container will mount it too).
        # Newly-created named volumes are owned root:root. The Vault Agent
        # container runs as the 'vault' user (UID 100) and writes
        # secrets.env using atomic-rename semantics (write tmpfile, rename) —
        # which requires write access to the directory itself, not just to
        # the file perms set by `template.perms`. Pre-chown to UID 100 via
        # a throwaway alpine container so subsequent sidecar writes succeed.
        vol_existed = True
        try:
            self._client.volumes.get(self.secrets_volume_name)
        except docker.errors.NotFound:
            self._client.volumes.create(name=self.secrets_volume_name)
            vol_existed = False
        if not vol_existed:
            self._client.containers.run(
                image="alpine:3.19",
                command=["sh", "-c", "chown 100:100 /shared && chmod 755 /shared"],
                volumes={self.secrets_volume_name: {"bind": "/shared", "mode": "rw"}},
                remove=True,
            )

        # Write the agent config to a bind-mounted dir so Vault Agent can read it
        config_dir = Path(".vystak") / "vault-agents" / self._principal_name
        config_dir.mkdir(parents=True, exist_ok=True)
        agent_hcl = generate_agent_hcl(
            vault_address=self._vault_address, secret_names=self._secret_names
        )
        (config_dir / "agent.hcl").write_text(agent_hcl)

        # Stop existing sidecar
        try:
            existing = self._client.containers.get(self.container_name)
            existing.stop()
            existing.remove()
        except docker.errors.NotFound:
            pass

        self._client.containers.run(
            image=self._image,
            name=self.container_name,
            command=["vault", "agent", "-config=/vault/config/agent.hcl"],
            detach=True,
            network=network.name,
            volumes={
                approle_volume: {"bind": "/vault/approle", "mode": "ro"},
                self.secrets_volume_name: {"bind": "/shared", "mode": "rw"},
                str(config_dir.absolute()): {"bind": "/vault/config", "mode": "ro"},
            },
            cap_add=["IPC_LOCK"],
            labels={
                "vystak.vault-agent": self._principal_name,
            },
        )

        return ProvisionResult(
            name=self.name,
            success=True,
            info={
                "container_name": self.container_name,
                "secrets_volume_name": self.secrets_volume_name,
            },
        )

    def destroy(self) -> None:
        try:
            c = self._client.containers.get(self.container_name)
            c.stop()
            c.remove()
        except docker.errors.NotFound:
            pass
        try:
            vol = self._client.volumes.get(self.secrets_volume_name)
            vol.remove()
        except docker.errors.NotFound:
            pass
