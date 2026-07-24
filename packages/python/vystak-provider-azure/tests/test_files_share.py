from unittest.mock import MagicMock

import pytest
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
    storage_client.file_shares.get.return_value = MagicMock()

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


def test_missing_storage_account_raises_actionable_error():
    storage_client = MagicMock()
    storage_client.storage_accounts.get_properties.side_effect = (
        ResourceNotFoundError("no account")
    )
    node = AzureFilesShareNode(
        client=storage_client,
        rg_name="rg",
        storage_account="missing",
        share_name="vystak-volume-team-code",
    )
    with pytest.raises(ValueError, match="Storage account 'missing' not found"):
        node.provision({})


def test_share_created_with_smb_by_default():
    storage_client = MagicMock()
    storage_client.file_shares.get.side_effect = ResourceNotFoundError("x")
    node = AzureFilesShareNode(
        client=storage_client,
        rg_name="rg",
        storage_account="acct",
        share_name="vystak-volume-team-code",
    )
    node.provision({})
    body = storage_client.file_shares.create.call_args.args[3]
    assert body == {}


def test_nfs_share_created_with_protocol():
    storage_client = MagicMock()
    storage_client.file_shares.get.side_effect = ResourceNotFoundError("x")
    node = AzureFilesShareNode(
        client=storage_client,
        rg_name="rg",
        storage_account="acct",
        share_name="vystak-volume-fast",
        enabled_protocols="NFS",
    )
    node.provision({})
    body = storage_client.file_shares.create.call_args.args[3]
    assert body == {"enabled_protocols": "NFS"}
