"""WorkspaceSshKeygenNode — generates SSH keypairs via throwaway alpine,
pushes the four pieces to Vault under _vystak/workspace-ssh/<agent>/*."""

import pathlib
import tempfile

from vystak.provisioning.node import Provisionable, ProvisionResult


class WorkspaceSshKeygenNode(Provisionable):
    """One per agent with a workspace. Runs after Vault KV setup."""

    def __init__(self, *, vault_client, docker_client, agent_name: str):
        self._vault = vault_client
        self._docker = docker_client
        self._agent_name = agent_name

    @property
    def name(self) -> str:
        return f"workspace-ssh-keygen:{self._agent_name}"

    @property
    def depends_on(self) -> list[str]:
        return ["hashi-vault:kv-setup"]

    def _vault_path(self, key: str) -> str:
        return f"_vystak/workspace-ssh/{self._agent_name}/{key}"

    def provision(self, context: dict) -> ProvisionResult:
        key_names = ["client-key", "host-key", "client-key-pub", "host-key-pub"]
        have = all(
            self._vault.kv_get(self._vault_path(k)) is not None for k in key_names
        )
        if have:
            return ProvisionResult(
                name=self.name, success=True, info={"regenerated": False}
            )

        # Generate both keypairs inside a throwaway alpine, write files to a
        # host tmpdir via bind mount, then read them back.
        with tempfile.TemporaryDirectory() as td:
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
            client_priv = (out / "client-key").read_text()
            client_pub = (out / "client-key.pub").read_text().strip()
            host_priv = (out / "host-key").read_text()
            host_pub = (out / "host-key.pub").read_text().strip()

        self._vault.kv_put(self._vault_path("client-key"), client_priv)
        self._vault.kv_put(self._vault_path("host-key"), host_priv)
        self._vault.kv_put(self._vault_path("client-key-pub"), client_pub)
        self._vault.kv_put(self._vault_path("host-key-pub"), host_pub)

        return ProvisionResult(
            name=self.name, success=True, info={"regenerated": True}
        )

    def destroy(self) -> None:
        # Keys preserved in Vault by default, same as user secrets.
        pass
