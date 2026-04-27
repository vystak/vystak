"""KvGrantNode — assigns a Key Vault RBAC role to a principal."""

import time
import uuid
from typing import Any

from vystak.provisioning.health import HealthCheck, NoopHealthCheck
from vystak.provisioning.node import Provisionable, ProvisionResult

# Azure built-in roles
KV_SECRETS_USER_ROLE_ID = "4633458b-17de-408a-b874-0445c86b69e6"      # read secret values
KV_SECRETS_OFFICER_ROLE_ID = "b86a8fe4-44ce-4948-aee5-eccb2c155cd7"   # read + write secrets


class KvGrantNode(Provisionable):
    """Assigns a Key Vault RBAC role to a principal at a given scope.

    Defaults to ``Key Vault Secrets User`` (read-only) for backward compat
    with the existing per-secret agent grants. Set ``role_id`` to
    ``KV_SECRETS_OFFICER_ROLE_ID`` for the deployer's vault-scoped write
    grant that has to run before any ``set_secret`` call.

    Retries with backoff on RBAC-propagation transient failures (up to 60s).
    """

    def __init__(
        self,
        client: Any,
        scope: str,
        principal_id: str | None,
        subscription_id: str,
        retry_seconds: int = 60,
        role_id: str = KV_SECRETS_USER_ROLE_ID,
        principal_type: str = "ServicePrincipal",
    ):
        self._client = client
        self._scope = scope
        self._principal_id = principal_id
        self._subscription_id = subscription_id
        self._retry_seconds = retry_seconds
        self._role_id = role_id
        self._principal_type = principal_type
        # Deferred principal resolution — set via set_principal_from_context.
        # When non-None, provision() reads the principal_id out of the upstream
        # identity node's ProvisionResult.info at apply time. This lets the
        # graph wire a grant to an identity whose principal isn't known until
        # the identity node runs (newly created UAMIs).
        self._principal_context_key: str | None = None
        self._principal_context_field: str = "principal_id"

    def set_principal_from_context(
        self,
        *,
        key: str,
        field: str = "principal_id",
    ) -> None:
        """Resolve the grant's principal from another node's result at apply time.

        `key` is the upstream Provisionable's `name`; `field` is the key to
        read from its ProvisionResult.info (defaults to 'principal_id').
        """
        self._principal_context_key = key
        self._principal_context_field = field

    @property
    def name(self) -> str:
        tail = self._scope.rsplit("/", 1)[-1]
        suffix = self._principal_id or self._principal_context_key or "skipped"
        return f"kv-grant:{tail}:{suffix}"

    def provision(self, context: dict) -> ProvisionResult:
        # Deferred principal resolution: pull from upstream identity result
        if self._principal_context_key and self._principal_id is None:
            upstream = context.get(self._principal_context_key)
            if upstream is not None:
                self._principal_id = upstream.info.get(self._principal_context_field)
        if self._principal_id is None:
            return ProvisionResult(name=self.name, success=True, info={"skipped": True})

        from azure.core.exceptions import HttpResponseError
        from azure.mgmt.authorization.models import RoleAssignmentCreateParameters

        role_def_id = (
            f"/subscriptions/{self._subscription_id}/providers/Microsoft.Authorization/"
            f"roleDefinitions/{self._role_id}"
        )
        params = RoleAssignmentCreateParameters(
            role_definition_id=role_def_id,
            principal_id=self._principal_id,
            principal_type=self._principal_type,
        )

        ra_name = str(uuid.uuid4())
        deadline = time.time() + self._retry_seconds
        last_err: Exception | None = None
        while time.time() < deadline:
            try:
                self._client.role_assignments.create(
                    scope=self._scope,
                    role_assignment_name=ra_name,
                    parameters=params,
                )
                return ProvisionResult(
                    name=self.name,
                    success=True,
                    info={"scope": self._scope, "principal_id": self._principal_id},
                )
            except HttpResponseError as e:
                # 409 RoleAssignmentExists — another graph node (or a prior
                # deploy) already created this exact (scope, principal, role)
                # tuple. Treat as success (idempotent).
                if e.status_code == 409 or "RoleAssignmentExists" in str(e):
                    return ProvisionResult(
                        name=self.name,
                        success=True,
                        info={
                            "scope": self._scope,
                            "principal_id": self._principal_id,
                            "already_existed": True,
                        },
                    )
                # Treat 400-class transient errors around principal propagation as retryable
                if e.status_code in (400, 403, 404):
                    last_err = e
                    time.sleep(5)
                    continue
                raise
        if last_err is not None:
            raise last_err
        raise RuntimeError(f"KvGrantNode: timed out assigning role at {self._scope}")

    def health_check(self) -> HealthCheck:
        return NoopHealthCheck()

    def destroy(self) -> None:
        # Role assignments are tracked per deploy; deletion handled by
        # orchestrating provider via a separate cleanup step.
        pass
