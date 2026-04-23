from unittest.mock import MagicMock

import pytest
from vystak.schema.common import VaultMode
from vystak_provider_azure.nodes.vault import KeyVaultNode


def _fake_kv_client() -> MagicMock:
    client = MagicMock()
    client.vaults.begin_create_or_update.return_value.result.return_value = MagicMock(
        properties=MagicMock(vault_uri="https://my-vault.vault.azure.net/")
    )
    client.vaults.get.return_value = MagicMock(
        properties=MagicMock(vault_uri="https://my-vault.vault.azure.net/")
    )
    return client


def test_deploy_creates_vault():
    client = _fake_kv_client()
    node = KeyVaultNode(
        client=client,
        rg_name="rg",
        vault_name="my-vault",
        location="eastus2",
        mode=VaultMode.DEPLOY,
        subscription_id="sub-1",
        tenant_id="tenant-1",
    )
    result = node.provision(context={})
    assert result.info["vault_uri"] == "https://my-vault.vault.azure.net/"
    client.vaults.begin_create_or_update.assert_called_once()


def test_external_mode_verifies_existing():
    client = _fake_kv_client()
    node = KeyVaultNode(
        client=client,
        rg_name="rg",
        vault_name="existing",
        location="eastus2",
        mode=VaultMode.EXTERNAL,
        subscription_id="sub-1",
        tenant_id="tenant-1",
    )
    result = node.provision(context={})
    client.vaults.get.assert_called_once_with("rg", "existing")
    client.vaults.begin_create_or_update.assert_not_called()
    assert result.info["vault_uri"].endswith(".vault.azure.net/")


def test_external_mode_missing_raises():
    from azure.core.exceptions import ResourceNotFoundError

    client = MagicMock()
    client.vaults.get.side_effect = ResourceNotFoundError("not found")
    node = KeyVaultNode(
        client=client,
        rg_name="rg",
        vault_name="missing",
        location="eastus2",
        mode=VaultMode.EXTERNAL,
        subscription_id="sub-1",
        tenant_id="tenant-1",
    )
    with pytest.raises(RuntimeError, match="External Vault 'missing' not found"):
        node.provision(context={})
