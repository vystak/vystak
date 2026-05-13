"""Generate workspace SSH keypairs and stash them in Azure Key Vault.

Mirrors vystak_provider_docker.nodes.workspace_ssh_keygen on the Vault path,
but pushes to Azure Key Vault instead of HashiCorp Vault. The four secrets
are referenced by the agent and workspace ACA apps via secretRef.
"""

from __future__ import annotations

import pathlib
import tempfile

from vystak.provisioning import Provisionable, ProvisionResult

_KEY_KINDS = ("client-key", "client-key-pub", "host-key", "host-key-pub")


def _kv_secret_name(agent_name: str, kind: str) -> str:
    return f"vystak-workspace-ssh-{agent_name}-{kind}"


class AzureWorkspaceSshKeygenNode(Provisionable):
    """Generate SSH keypairs once per agent; push to Key Vault.

    Idempotent — if all four secrets already exist, no keygen runs.
    """

    def __init__(
        self,
        *,
        agent_name: str,
        secret_client,
        docker_client,
    ) -> None:
        self._agent_name = agent_name
        self._secret_client = secret_client
        self._docker = docker_client

    @property
    def name(self) -> str:
        return f"workspace-ssh-keygen-{self._agent_name}"

    def provision(self, context: dict) -> ProvisionResult:
        if self._all_keys_exist():
            return ProvisionResult(
                name=self.name, success=True, info={"regenerated": False}
            )

        with tempfile.TemporaryDirectory() as td:
            client_priv, client_pub, host_priv, host_pub = self._keygen_via_docker(td)

        values = {
            "client-key": client_priv,
            "client-key-pub": client_pub,
            "host-key": host_priv,
            "host-key-pub": host_pub,
        }
        for kind, value in values.items():
            self._secret_client.set_secret(
                _kv_secret_name(self._agent_name, kind), value
            )

        return ProvisionResult(
            name=self.name, success=True, info={"regenerated": True}
        )

    def _all_keys_exist(self) -> bool:
        for kind in _KEY_KINDS:
            try:
                self._secret_client.get_secret(_kv_secret_name(self._agent_name, kind))
            except Exception:
                return False
        return True

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
