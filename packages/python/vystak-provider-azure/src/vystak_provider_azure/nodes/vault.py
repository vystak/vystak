"""KeyVaultNode — deploys an Azure Key Vault or verifies one exists."""

from azure.core.exceptions import ResourceNotFoundError
from vystak.provisioning.health import HealthCheck, NoopHealthCheck
from vystak.provisioning.node import Provisionable, ProvisionResult
from vystak.schema.common import VaultMode


class KeyVaultNode(Provisionable):
    """Creates or verifies an Azure Key Vault, using RBAC authorization model."""

    def __init__(
        self,
        client,
        rg_name: str,
        vault_name: str,
        location: str,
        mode: VaultMode,
        subscription_id: str,
        tenant_id: str,
        tags: dict | None = None,
    ):
        self._client = client
        self._rg_name = rg_name
        self._vault_name = vault_name
        self._location = location
        self._mode = mode
        self._subscription_id = subscription_id
        self._tenant_id = tenant_id
        self._tags = tags or {}

    @property
    def name(self) -> str:
        return f"keyvault:{self._vault_name}"

    def provision(self, context: dict) -> ProvisionResult:
        if self._mode is VaultMode.EXTERNAL:
            try:
                existing = self._client.vaults.get(self._rg_name, self._vault_name)
            except ResourceNotFoundError as e:
                raise RuntimeError(
                    f"External Vault '{self._vault_name}' not found in resource "
                    f"group '{self._rg_name}'. Create it first, or switch to "
                    f"mode='deploy'."
                ) from e
            return ProvisionResult(
                name=self.name,
                success=True,
                info={
                    "vault_uri": existing.properties.vault_uri,
                    "vault_name": self._vault_name,
                    "rg_name": self._rg_name,
                },
            )

        # DEPLOY mode
        from azure.mgmt.keyvault.models import (
            Sku,
            VaultCreateOrUpdateParameters,
            VaultProperties,
        )

        params = VaultCreateOrUpdateParameters(
            location=self._location,
            tags=self._tags,
            properties=VaultProperties(
                tenant_id=self._tenant_id,
                sku=Sku(name="standard", family="A"),
                enable_rbac_authorization=True,
                soft_delete_retention_in_days=7,
            ),
        )
        result = self._client.vaults.begin_create_or_update(
            self._rg_name, self._vault_name, params
        ).result()
        return ProvisionResult(
            name=self.name,
            success=True,
            info={
                "vault_uri": result.properties.vault_uri,
                "vault_name": self._vault_name,
                "rg_name": self._rg_name,
            },
        )

    def health_check(self) -> HealthCheck:
        return NoopHealthCheck()

    def destroy(self) -> None:
        # Destroy leaves the vault alone unless --delete-vault passed;
        # caller manages that via provider-level flag. This node never
        # self-destroys its vault in v1.
        pass
