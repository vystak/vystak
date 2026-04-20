import pytest
from pydantic import ValidationError as PydanticValidationError

from vystak.schema.common import VaultMode, VaultType
from vystak.schema.provider import Provider
from vystak.schema.vault import Vault


def _azure_provider() -> Provider:
    return Provider(name="azure", type="azure", config={"location": "eastus2"})


def test_vault_default_type_is_key_vault():
    v = Vault(name="v", provider=_azure_provider())
    assert v.type is VaultType.KEY_VAULT
    assert v.mode is VaultMode.DEPLOY


def test_vault_with_explicit_mode_and_config():
    v = Vault(
        name="v",
        provider=_azure_provider(),
        mode=VaultMode.EXTERNAL,
        config={"vault_name": "existing-vault"},
    )
    assert v.mode is VaultMode.EXTERNAL
    assert v.config == {"vault_name": "existing-vault"}


def test_vault_external_without_config_raises():
    with pytest.raises(PydanticValidationError) as excinfo:
        Vault(name="v", provider=_azure_provider(), mode=VaultMode.EXTERNAL)
    assert "requires config identifying the existing" in str(excinfo.value)


def test_vault_requires_provider():
    with pytest.raises(PydanticValidationError):
        Vault(name="v")  # type: ignore[call-arg]
