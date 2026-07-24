"""Register an Azure Files share as ACA Environment storage.

Multiple Container Apps in the same Environment can mount the share via
volumeMounts; the storage entry is what ties them to the share + account key.
"""

from __future__ import annotations

from azure.core.exceptions import ResourceNotFoundError
from vystak.provisioning import Provisionable, ProvisionResult


class ACAEnvStorageNode(Provisionable):
    def __init__(
        self,
        *,
        aca_client,
        storage_client,
        rg_name: str,
        env_name: str,
        storage_name: str,
        storage_account: str,
        share_name: str,
        protocol: str = "SMB",
    ) -> None:
        self._aca = aca_client
        self._storage = storage_client
        self._rg_name = rg_name
        self._env_name = env_name
        self._storage_name = storage_name
        self._storage_account = storage_account
        self._share_name = share_name
        self._protocol = protocol

    @property
    def name(self) -> str:
        return f"aca-env-storage-{self._storage_name}"

    def provision(self, context: dict) -> ProvisionResult:
        try:
            self._aca.managed_environments_storages.get(
                self._rg_name, self._env_name, self._storage_name
            )
            return ProvisionResult(
                name=self.name,
                success=True,
                info={"storage_name": self._storage_name, "created": False},
            )
        except ResourceNotFoundError:
            if self._protocol == "NFS":
                envelope = {
                    "properties": {
                        "nfsAzureFile": {
                            "server": (
                                f"{self._storage_account}.file.core.windows.net"
                            ),
                            "shareName": (
                                f"/{self._storage_account}/{self._share_name}"
                            ),
                            "accessMode": "ReadWrite",
                        }
                    }
                }
            else:
                keys = self._storage.storage_accounts.list_keys(
                    self._rg_name, self._storage_account
                )
                account_key = keys.keys[0].value
                envelope = {
                    "properties": {
                        "azureFile": {
                            "accountName": self._storage_account,
                            "accountKey": account_key,
                            "shareName": self._share_name,
                            "accessMode": "ReadWrite",
                        }
                    }
                }
            self._aca.managed_environments_storages.create_or_update(
                resource_group_name=self._rg_name,
                environment_name=self._env_name,
                storage_name=self._storage_name,
                managed_environment_storage_envelope=envelope,
            )
            return ProvisionResult(
                name=self.name,
                success=True,
                info={"storage_name": self._storage_name, "created": True},
            )
