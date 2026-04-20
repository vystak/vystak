"""KvGrantNode — assigns 'Key Vault Secrets User' role on a KV secret."""

import time
import uuid
from typing import Any

from vystak.provisioning.health import HealthCheck, NoopHealthCheck
from vystak.provisioning.node import Provisionable, ProvisionResult

# Azure built-in role: Key Vault Secrets User (read-only access to secret values)
KV_SECRETS_USER_ROLE_ID = "4633458b-17de-408a-b874-0445c86b69e6"


class KvGrantNode(Provisionable):
    """Assigns Key Vault Secrets User role to a principal, scoped to one secret.

    Retries with backoff on RBAC-propagation transient failures (up to 60s).
    """

    def __init__(
        self,
        client: Any,
        scope: str,
        principal_id: str | None,
        subscription_id: str,
        retry_seconds: int = 60,
    ):
        self._client = client
        self._scope = scope
        self._principal_id = principal_id
        self._subscription_id = subscription_id
        self._retry_seconds = retry_seconds

    @property
    def name(self) -> str:
        tail = self._scope.rsplit("/", 1)[-1]
        return f"kv-grant:{tail}:{self._principal_id or 'skipped'}"

    def provision(self, context: dict) -> ProvisionResult:
        if self._principal_id is None:
            return ProvisionResult(name=self.name, success=True, info={"skipped": True})

        from azure.core.exceptions import HttpResponseError
        from azure.mgmt.authorization.models import RoleAssignmentCreateParameters

        role_def_id = (
            f"/subscriptions/{self._subscription_id}/providers/Microsoft.Authorization/"
            f"roleDefinitions/{KV_SECRETS_USER_ROLE_ID}"
        )
        params = RoleAssignmentCreateParameters(
            role_definition_id=role_def_id,
            principal_id=self._principal_id,
            principal_type="ServicePrincipal",
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
