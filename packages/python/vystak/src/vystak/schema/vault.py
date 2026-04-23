"""Vault model — a secrets backing store (Azure Key Vault in v1)."""

from typing import Self

from pydantic import model_validator

from vystak.schema.common import NamedModel, VaultMode, VaultType
from vystak.schema.provider import Provider


class Vault(NamedModel):
    """A secrets backing store — deployed by vystak or linked as external.

    Declared once per deployment. Every `Secret` in the declaration's
    agent tree materializes through this vault at apply time.
    """

    type: VaultType = VaultType.KEY_VAULT
    provider: Provider
    mode: VaultMode = VaultMode.DEPLOY
    config: dict = {}

    @model_validator(mode="after")
    def _validate(self) -> Self:
        if self.mode is VaultMode.EXTERNAL and not self.config:
            raise ValueError(
                f"Vault '{self.name}' has mode='external' but requires config "
                f"identifying the existing store "
                f"(e.g. config={{'vault_name': 'my-vault'}})."
            )
        return self
