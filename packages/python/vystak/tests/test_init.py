def test_vault_exported_from_vystak():
    import vystak

    assert hasattr(vystak, "Vault")
    assert hasattr(vystak, "VaultType")
    assert hasattr(vystak, "VaultMode")


def test_vault_exported_from_vystak_schema():
    from vystak.schema import Vault, VaultMode, VaultType

    assert Vault is not None
    assert VaultType.KEY_VAULT.value == "key-vault"
    assert VaultMode.DEPLOY.value == "deploy"
