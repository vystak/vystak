"""SecretSyncNode — reads .env values and pushes to Key Vault at apply time."""

from typing import Any

from azure.core.exceptions import ResourceNotFoundError
from vystak.provisioning.health import HealthCheck, NoopHealthCheck
from vystak.provisioning.node import Provisionable, ProvisionResult

from vystak_provider_azure.nodes.aca_app import _kv_secret_name


class SecretSyncNode(Provisionable):
    """Pushes declared secrets into a KV client with push-if-missing semantics.

    Args:
        client: An azure.keyvault.secrets.SecretClient pointed at the vault.
        declared_secrets: List of secret names to sync.
        env_values: dict from .env file (or other source) — values to push.
        force: If True, overwrite existing KV values.
        allow_missing: If True, do not abort when a secret is missing from
            both KV and env_values; instead, report in the result.
    """

    def __init__(
        self,
        client: Any,
        declared_secrets: list[str],
        env_values: dict[str, str],
        force: bool = False,
        allow_missing: bool = False,
    ):
        self._client = client
        self._declared = list(declared_secrets)
        self._env = dict(env_values)
        self._force = force
        self._allow_missing = allow_missing

    @property
    def name(self) -> str:
        return "secret-sync"

    def provision(self, context: dict) -> ProvisionResult:
        pushed: list[str] = []
        skipped: list[str] = []
        missing: list[str] = []

        for name in self._declared:
            # Azure Key Vault secret names must match [a-zA-Z0-9-]+ (no
            # underscores). ACA secret-ref names additionally require
            # lowercase. _kv_secret_name normalizes to both — apply the
            # same transform here so the KV name and the ACA keyVaultUrl
            # reference match.
            kv_name = _kv_secret_name(name)
            existing_value = self._get_existing(kv_name)
            if existing_value is not None and not self._force:
                skipped.append(name)
                continue
            if name in self._env:
                self._client.set_secret(kv_name, self._env[name])
                pushed.append(name)
            else:
                missing.append(name)

        if missing and not self._allow_missing:
            raise RuntimeError(
                f"Secrets missing from both .env and vault: {', '.join(missing)}. "
                f"Set them in .env, run 'vystak secrets set <name>=<value>', or "
                f"pass --allow-missing."
            )

        return ProvisionResult(
            name=self.name,
            success=True,
            info={"pushed": pushed, "skipped": skipped, "missing": missing},
        )

    def _get_existing(self, name: str) -> str | None:
        """Lookup an existing secret. Caller passes the KV-form name (hyphens)."""
        try:
            return self._client.get_secret(name).value
        except ResourceNotFoundError:
            return None

    def health_check(self) -> HealthCheck:
        return NoopHealthCheck()

    def destroy(self) -> None:
        # Destroy leaves secret values in KV.
        pass
