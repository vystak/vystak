"""ResourceGroupNode — ensures an Azure Resource Group exists."""

from vystak.provisioning.health import HealthCheck, NoopHealthCheck
from vystak.provisioning.node import Provisionable, ProvisionResult

from azure.mgmt.resource.resources.models import ResourceGroup


class ResourceGroupNode(Provisionable):
    """Creates or verifies an Azure Resource Group."""

    def __init__(self, client, rg_name: str, location: str, tags: dict | None = None):
        self._client = client
        self._rg_name = rg_name
        self._location = location
        self._tags = tags or {}

    @property
    def name(self) -> str:
        return "resource-group"

    def provision(self, context: dict) -> ProvisionResult:
        try:
            exists = self._client.resource_groups.check_existence(self._rg_name)
            if not exists:
                self.emit("Creating", self._rg_name)
                self._client.resource_groups.create_or_update(
                    self._rg_name,
                    ResourceGroup(location=self._location, tags=self._tags),
                )
            return ProvisionResult(
                name=self.name,
                success=True,
                info={"rg_name": self._rg_name, "created": not exists, "detail": "created" if not exists else "exists"},
            )
        except Exception as e:
            return ProvisionResult(name=self.name, success=False, error=str(e))

    def health_check(self) -> HealthCheck:
        return NoopHealthCheck()
