"""VaultKvSetupNode — enables KV v2 and AppRole auth after unseal."""

from vystak.provisioning.node import Provisionable, ProvisionResult


class VaultKvSetupNode(Provisionable):
    """Idempotently enables KV v2 at secret/ and AppRole auth at auth/approle/."""

    def __init__(self, *, vault_client, root_token: str | None = None):
        self._vault = vault_client
        self._root_token = root_token

    @property
    def name(self) -> str:
        return "hashi-vault:kv-setup"

    @property
    def depends_on(self) -> list[str]:
        return ["hashi-vault:unseal"]

    def provision(self, context: dict) -> ProvisionResult:
        if self._root_token:
            self._vault.set_token(self._root_token)
        self._vault.enable_kv_v2("secret")
        self._vault.enable_approle_auth()
        return ProvisionResult(name=self.name, success=True, info={})

    def destroy(self) -> None:
        pass
