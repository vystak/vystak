"""Idempotent Azure Files share for workspace persistence: volume."""

from __future__ import annotations

from azure.core.exceptions import ResourceNotFoundError
from vystak.provisioning import Provisionable, ProvisionResult


class AzureFilesShareNode(Provisionable):
    """Create or look up an Azure Files share. Idempotent.

    The storage account itself must exist; we do not create it (the spec
    requires the user provides ``platform.config.storage_account``).
    """

    def __init__(
        self,
        *,
        client,
        rg_name: str,
        storage_account: str,
        share_name: str,
    ) -> None:
        self._client = client
        self._rg_name = rg_name
        self._storage_account = storage_account
        self._share_name = share_name

    @property
    def name(self) -> str:
        return f"files-share-{self._share_name}"

    def provision(self, context: dict) -> ProvisionResult:
        try:
            self._client.file_shares.get(
                self._rg_name, self._storage_account, self._share_name
            )
            return ProvisionResult(
                name=self.name,
                success=True,
                info={
                    "share_name": self._share_name,
                    "storage_account": self._storage_account,
                    "created": False,
                },
            )
        except ResourceNotFoundError:
            self._client.file_shares.create(
                self._rg_name,
                self._storage_account,
                self._share_name,
                {},
            )
            return ProvisionResult(
                name=self.name,
                success=True,
                info={
                    "share_name": self._share_name,
                    "storage_account": self._storage_account,
                    "created": True,
                },
            )
