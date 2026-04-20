"""AppRoleNode — creates/updates a policy + AppRole for one principal."""

from vystak.provisioning.node import Provisionable, ProvisionResult

from vystak_provider_docker.templates import generate_policy_hcl


class AppRoleNode(Provisionable):
    """One per principal. Writes <principal>-policy, upserts the AppRole,
    returns (role_id, secret_id) in its ProvisionResult.info."""

    def __init__(
        self,
        *,
        vault_client,
        principal_name: str,
        secret_names: list[str],
        token_ttl: str = "1h",
        token_max_ttl: str = "24h",
    ):
        self._vault = vault_client
        self._principal_name = principal_name
        self._secret_names = list(secret_names)
        self._token_ttl = token_ttl
        self._token_max_ttl = token_max_ttl

    @property
    def policy_name(self) -> str:
        return f"{self._principal_name}-policy"

    @property
    def name(self) -> str:
        return f"approle:{self._principal_name}"

    @property
    def depends_on(self) -> list[str]:
        return ["hashi-vault:kv-setup"]

    def provision(self, context: dict) -> ProvisionResult:
        # Write policy
        policy_hcl = generate_policy_hcl(secret_names=self._secret_names)
        self._vault.write_policy(name=self.policy_name, hcl=policy_hcl)

        # Upsert AppRole bound to the policy
        role_id, secret_id = self._vault.upsert_approle(
            role_name=self._principal_name,
            policies=[self.policy_name],
            token_ttl=self._token_ttl,
            token_max_ttl=self._token_max_ttl,
        )

        return ProvisionResult(
            name=self.name,
            success=True,
            info={
                "policy_name": self.policy_name,
                "role_name": self._principal_name,
                "role_id": role_id,
                "secret_id": secret_id,
                "secret_names": self._secret_names,
            },
        )

    def destroy(self) -> None:
        self._vault.delete_approle(self._principal_name)
        self._vault.delete_policy(self.policy_name)
