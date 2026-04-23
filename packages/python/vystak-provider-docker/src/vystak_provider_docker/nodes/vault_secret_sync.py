"""VaultSecretSyncNode — push-if-missing of .env values into Vault KV v2."""

from vystak.provisioning.node import Provisionable, ProvisionResult


class VaultSecretSyncNode(Provisionable):
    """Hashi-side analog of v1's SecretSyncNode. Same semantics:
       - If KV has the secret, skip (unless force).
       - If missing from both .env and KV, abort (unless allow_missing)."""

    def __init__(
        self,
        *,
        vault_client,
        declared_secrets: list[str],
        env_values: dict[str, str],
        force: bool = False,
        allow_missing: bool = False,
    ):
        self._vault = vault_client
        self._declared = list(declared_secrets)
        self._env = dict(env_values)
        self._force = force
        self._allow_missing = allow_missing

    @property
    def name(self) -> str:
        return "hashi-vault:secret-sync"

    @property
    def depends_on(self) -> list[str]:
        return ["hashi-vault:kv-setup"]

    def provision(self, context: dict) -> ProvisionResult:
        pushed: list[str] = []
        skipped: list[str] = []
        missing: list[str] = []

        for name in self._declared:
            existing = self._vault.kv_get(name)
            if existing is not None and not self._force:
                skipped.append(name)
                continue
            if name in self._env:
                self._vault.kv_put(name, self._env[name])
                pushed.append(name)
            else:
                missing.append(name)

        if missing and not self._allow_missing:
            raise RuntimeError(
                f"Secrets missing from both .env and vault: {', '.join(missing)}. "
                f"Set in .env, run 'vystak secrets set <name>=<value>', or pass --allow-missing."
            )

        return ProvisionResult(
            name=self.name,
            success=True,
            info={"pushed": pushed, "skipped": skipped, "missing": missing},
        )

    def destroy(self) -> None:
        pass  # values preserved by design
