"""Idempotent Azure Files share for workspace persistence: volume."""

from __future__ import annotations

from azure.core.exceptions import ResourceNotFoundError
from vystak.provisioning import Provisionable, ProvisionResult


class AzureFilesShareNode(Provisionable):
    """Create or look up an Azure Files share. Idempotent.

    Caller must ensure the storage account exists (the spec requires the
    user provides ``platform.config.storage_account``). The storage account
    is pre-checked via ``storage_accounts.get_properties`` before any share
    lookup/create; if it's missing, ``provision`` raises a ``ValueError``
    with an actionable message (including the ``az storage account create``
    command to fix it) instead of letting Azure fail deep inside
    ``file_shares.create`` with an opaque parent-resource error.

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
        enabled_protocols: str = "SMB",
    ) -> None:
        self._client = client
        self._rg_name = rg_name
        self._storage_account = storage_account
        self._share_name = share_name
        self._enabled_protocols = enabled_protocols

    @property
    def name(self) -> str:
        return f"files-share-{self._share_name}"

    def provision(self, context: dict) -> ProvisionResult:
        try:
            self._client.storage_accounts.get_properties(
                self._rg_name, self._storage_account
            )
        except ResourceNotFoundError:
            raise ValueError(
                f"Storage account '{self._storage_account}' not found in "
                f"resource group '{self._rg_name}'. Workspace volumes on "
                f"Azure require an existing storage account named in "
                f"platform.config.storage_account. Create it first:\n"
                f"  az storage account create -n {self._storage_account} "
                f"-g {self._rg_name} --sku Standard_LRS"
            ) from None

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
            body = (
                {"enabled_protocols": "NFS"}
                if self._enabled_protocols == "NFS"
                else {}
            )
            self._client.file_shares.create(
                self._rg_name,
                self._storage_account,
                self._share_name,
                body,
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
