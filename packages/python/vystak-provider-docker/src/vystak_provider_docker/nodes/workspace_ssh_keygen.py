"""WorkspaceSshKeygenNode — generates SSH keypairs.

Default path (vault_client is None): writes four files to
.vystak/ssh/<agent>/ with chmod 600 on private keys, 644 on public keys.
Agent and workspace containers bind-mount these directly.

Vault path (vault_client provided): pushes the four pieces to Vault under
_vystak/workspace-ssh/<agent>/*. Vault Agent sidecars render into per-
principal /shared volumes. No host file is written.
"""

import pathlib
import tempfile

from vystak.provisioning.node import Provisionable, ProvisionResult


class WorkspaceSshKeygenNode(Provisionable):
    """One per agent with a workspace. Runs after Vault KV setup on the
    Vault path, or after network setup on the default path."""

    def __init__(self, *, vault_client, docker_client, agent_name: str):
        self._vault = vault_client
        self._docker = docker_client
        self._agent_name = agent_name

    @property
    def name(self) -> str:
        return f"workspace-ssh-keygen:{self._agent_name}"

    @property
    def depends_on(self) -> list[str]:
        return (
            ["hashi-vault:kv-setup"]
            if self._vault is not None
            else ["network"]
        )

    def _vault_path(self, key: str) -> str:
        return f"_vystak/workspace-ssh/{self._agent_name}/{key}"

    def _host_ssh_dir(self) -> pathlib.Path:
        return pathlib.Path(".vystak") / "ssh" / self._agent_name

    def provision(self, context: dict) -> ProvisionResult:
        if self._vault is not None:
            return self._provision_vault()
        return self._provision_host()

    def _provision_vault(self) -> ProvisionResult:
        key_names = ["client-key", "host-key", "client-key-pub", "host-key-pub"]
        have = all(
            self._vault.kv_get(self._vault_path(k)) is not None for k in key_names
        )
        if have:
            return ProvisionResult(
                name=self.name, success=True, info={"regenerated": False}
            )

        with tempfile.TemporaryDirectory() as td:
            client_priv, client_pub, host_priv, host_pub = self._keygen_via_docker(td)

        self._vault.kv_put(self._vault_path("client-key"), client_priv)
        self._vault.kv_put(self._vault_path("host-key"), host_priv)
        self._vault.kv_put(self._vault_path("client-key-pub"), client_pub)
        self._vault.kv_put(self._vault_path("host-key-pub"), host_pub)

        return ProvisionResult(
            name=self.name, success=True, info={"regenerated": True}
        )

    def _provision_host(self) -> ProvisionResult:
        host_dir = self._host_ssh_dir()
        existing = [
            host_dir / "client-key",
            host_dir / "client-key.pub",
            host_dir / "host-key",
            host_dir / "host-key.pub",
        ]
        if all(p.exists() for p in existing):
            return ProvisionResult(
                name=self.name, success=True, info={"regenerated": False}
            )

        host_dir.mkdir(parents=True, exist_ok=True)

        with tempfile.TemporaryDirectory() as td:
            client_priv, client_pub, host_priv, host_pub = self._keygen_via_docker(td)

        (host_dir / "client-key").write_text(client_priv)
        (host_dir / "client-key").chmod(0o600)
        (host_dir / "host-key").write_text(host_priv)
        (host_dir / "host-key").chmod(0o600)
        (host_dir / "client-key.pub").write_text(client_pub + "\n")
        (host_dir / "client-key.pub").chmod(0o644)
        (host_dir / "host-key.pub").write_text(host_pub + "\n")
        (host_dir / "host-key.pub").chmod(0o644)

        return ProvisionResult(
            name=self.name, success=True, info={"regenerated": True}
        )

    def _keygen_via_docker(self, td: str) -> tuple[str, str, str, str]:
        """Generate both keypairs inside a throwaway alpine, return pieces."""
        script = (
            "apk add --no-cache openssh-keygen > /dev/null 2>&1 || "
            "apk add --no-cache openssh > /dev/null 2>&1;"
            "ssh-keygen -t ed25519 -N '' -f /out/client-key -q;"
            "ssh-keygen -t ed25519 -N '' -f /out/host-key -q;"
            "chmod 644 /out/*"
        )
        self._docker.containers.run(
            image="alpine:3.19",
            command=["sh", "-c", script],
            volumes={td: {"bind": "/out", "mode": "rw"}},
            remove=True,
        )
        out = pathlib.Path(td)
        return (
            (out / "client-key").read_text(),
            (out / "client-key.pub").read_text().strip(),
            (out / "host-key").read_text(),
            (out / "host-key.pub").read_text().strip(),
        )

    def destroy(self) -> None:
        """Keys preserved by default on both paths; explicit rotate-ssh removes."""
        pass
