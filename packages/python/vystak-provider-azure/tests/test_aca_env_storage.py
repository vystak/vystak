from unittest.mock import MagicMock

from azure.core.exceptions import ResourceNotFoundError
from vystak_provider_azure.nodes.aca_env_storage import ACAEnvStorageNode


def test_provision_creates_env_storage_when_missing():
    aca_client = MagicMock()
    aca_client.managed_environments_storages.get.side_effect = (
        ResourceNotFoundError("not found")
    )
    storage_client = MagicMock()
    storage_client.storage_accounts.list_keys.return_value.keys = [
        MagicMock(value="account-key-1"),
    ]

    node = ACAEnvStorageNode(
        aca_client=aca_client,
        storage_client=storage_client,
        rg_name="vystak-test",
        env_name="vystak-env",
        storage_name="vystak-assistant-workspace",
        storage_account="mystorage",
        share_name="vystak-assistant-workspace-data",
    )
    result = node.provision({})

    assert result.success is True
    aca_client.managed_environments_storages.create_or_update.assert_called_once()
    body = aca_client.managed_environments_storages.create_or_update.call_args.kwargs[
        "managed_environment_storage_envelope"
    ]
    assert body["properties"]["azureFile"]["accountName"] == "mystorage"
    assert body["properties"]["azureFile"]["shareName"] == (
        "vystak-assistant-workspace-data"
    )
    assert body["properties"]["azureFile"]["accessMode"] == "ReadWrite"
    assert result.info["storage_name"] == "vystak-assistant-workspace"


def test_provision_idempotent_when_env_storage_exists():
    aca_client = MagicMock()
    aca_client.managed_environments_storages.get.return_value = MagicMock()
    storage_client = MagicMock()

    node = ACAEnvStorageNode(
        aca_client=aca_client,
        storage_client=storage_client,
        rg_name="vystak-test",
        env_name="vystak-env",
        storage_name="vystak-assistant-workspace",
        storage_account="mystorage",
        share_name="vystak-assistant-workspace-data",
    )
    result = node.provision({})

    assert result.success is True
    aca_client.managed_environments_storages.create_or_update.assert_not_called()
