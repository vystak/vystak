"""LogAnalyticsNode — creates a Log Analytics workspace for ACA logging."""

from agentstack.provisioning.health import HealthCheck, NoopHealthCheck
from agentstack.provisioning.node import Provisionable, ProvisionResult

from azure.mgmt.loganalytics.models import Workspace, WorkspaceSku


class LogAnalyticsNode(Provisionable):
    """Creates a Log Analytics workspace and retrieves shared keys."""

    def __init__(self, client, rg_name: str, workspace_name: str, location: str, tags: dict | None = None):
        self._client = client
        self._rg_name = rg_name
        self._workspace_name = workspace_name
        self._location = location
        self._tags = tags or {}

    @property
    def name(self) -> str:
        return "log-analytics"

    @property
    def depends_on(self) -> list[str]:
        return ["resource-group"]

    def provision(self, context: dict) -> ProvisionResult:
        try:
            workspace = self._client.workspaces.begin_create_or_update(
                self._rg_name,
                self._workspace_name,
                Workspace(
                    location=self._location,
                    sku=WorkspaceSku(name="PerGB2018"),
                    tags=self._tags,
                ),
            ).result()

            keys = self._client.shared_keys.get_shared_keys(
                self._rg_name,
                self._workspace_name,
            )

            return ProvisionResult(
                name=self.name,
                success=True,
                info={
                    "customer_id": workspace.customer_id,
                    "shared_key": keys.primary_shared_key,
                    "workspace_name": self._workspace_name,
                },
            )
        except Exception as e:
            return ProvisionResult(name=self.name, success=False, error=str(e))

    def health_check(self) -> HealthCheck:
        return NoopHealthCheck()
