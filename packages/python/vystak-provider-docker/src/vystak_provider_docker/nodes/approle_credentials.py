"""AppRoleCredentialsNode — writes role_id + secret_id files into a
named Docker volume so the Vault Agent sidecar can read them.

We write via a throwaway alpine container because Docker volumes
aren't directly writable from the host without knowing their
filesystem path.
"""

import shlex

import docker.errors
from vystak.provisioning.node import Provisionable, ProvisionResult


class AppRoleCredentialsNode(Provisionable):
    """One per principal. Depends on AppRoleNode having produced the creds."""

    def __init__(self, *, client, principal_name: str):
        self._client = client
        self._principal_name = principal_name

    @property
    def volume_name(self) -> str:
        return f"vystak-{self._principal_name}-approle"

    @property
    def name(self) -> str:
        return f"approle-creds:{self._principal_name}"

    @property
    def depends_on(self) -> list[str]:
        return [f"approle:{self._principal_name}"]

    def provision(self, context: dict) -> ProvisionResult:
        approle_info = context[f"approle:{self._principal_name}"].info
        role_id = approle_info["role_id"]
        secret_id = approle_info["secret_id"]

        # Ensure the volume exists
        try:
            self._client.volumes.get(self.volume_name)
        except docker.errors.NotFound:
            self._client.volumes.create(name=self.volume_name)

        # Write the two credential files via a throwaway container. Use
        # printf to avoid quoting issues with arbitrary credential content.
        # chmod 444 (world-readable): the files are written by root (alpine
        # default) but the Vault Agent sidecar runs as UID 100 ('vault' user)
        # and needs to read them. Volume isolation — the mount only exists
        # in the one sidecar container — is the security boundary.
        script = (
            f"printf %s {shlex.quote(role_id)} > /target/role_id && "
            f"chmod 444 /target/role_id && "
            f"printf %s {shlex.quote(secret_id)} > /target/secret_id && "
            f"chmod 444 /target/secret_id"
        )
        self._client.containers.run(
            image="alpine:3.19",
            command=["sh", "-c", script],
            volumes={self.volume_name: {"bind": "/target", "mode": "rw"}},
            remove=True,
        )

        return ProvisionResult(
            name=self.name,
            success=True,
            info={"volume_name": self.volume_name},
        )

    def destroy(self) -> None:
        try:
            vol = self._client.volumes.get(self.volume_name)
            vol.remove()
        except docker.errors.NotFound:
            pass
