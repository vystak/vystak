from unittest.mock import MagicMock

from azure.core.exceptions import ResourceNotFoundError
from vystak_provider_azure.nodes.files_share import AzureFilesShareNode


def test_provision_creates_share_when_missing():
    storage_client = MagicMock()
    storage_client.file_shares.get.side_effect = ResourceNotFoundError("not found")

    node = AzureFilesShareNode(
        client=storage_client,
        rg_name="vystak-test",
        storage_account="mystorage",
        share_name="vystak-assistant-workspace-data",
    )
    result = node.provision({})

    assert result.success is True
    storage_client.file_shares.create.assert_called_once()
    assert result.info["share_name"] == "vystak-assistant-workspace-data"
    assert result.info["created"] is True


def test_provision_idempotent_when_share_exists():
    storage_client = MagicMock()
    existing = MagicMock(name="existing-share")
    storage_client.file_shares.get.return_value = existing

    node = AzureFilesShareNode(
        client=storage_client,
        rg_name="vystak-test",
        storage_account="mystorage",
        share_name="vystak-assistant-workspace-data",
    )
    result = node.provision({})

    assert result.success is True
    storage_client.file_shares.create.assert_not_called()
    assert result.info["created"] is False
