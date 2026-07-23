"""Idempotent Azure Files share for workspace persistence: volume."""

from __future__ import annotations

from azure.core.exceptions import ResourceNotFoundError
from vystak.provisioning import Provisionable, ProvisionResult


class AzureFilesShareNode(Provisionable):
    """Create or look up an Azure Files share. Idempotent.

    Caller must ensure the storage account exists (the spec requires the
    user provides ``platform.config.storage_account``). If the account is
    missing, ``file_shares.get`` raises ``ResourceNotFoundError`` and we
    proceed to ``create``, which will then fail with a parent-resource
    error from Azure — not a friendly message, but fail-fast.

    Destroy is intentionally a no-op (inherited from ``Provisionable``):
    workspace data on the share survives provider destroy unless the user
    passes ``--delete-workspace-data``.
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
            # Empty body — Azure defaults share_quota from the storage account
            # (typically 5 TiB SMB). Override here if a specific quota is needed.
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
