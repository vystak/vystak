"""ACRNode — creates or reuses an Azure Container Registry."""

from azure.mgmt.containerregistry.models import Registry, Sku
from vystak.provisioning.health import HealthCheck, NoopHealthCheck
from vystak.provisioning.node import Provisionable, ProvisionResult


class ACRNode(Provisionable):
    """Creates an ACR with admin enabled (Basic SKU), or reuses an existing one."""

    def __init__(
        self,
        client,
        rg_name: str,
        registry_name: str,
        location: str,
        existing: bool = False,
        tags: dict | None = None,
    ):
        self._client = client
        self._rg_name = rg_name
        self._registry_name = registry_name
        self._location = location
        self._existing = existing
        self._tags = tags or {}

    @property
    def name(self) -> str:
        return "acr"

    @property
    def depends_on(self) -> list[str]:
        return ["resource-group"]

    def provision(self, context: dict) -> ProvisionResult:
        try:
            if self._existing:
                registry = self._client.registries.get(self._rg_name, self._registry_name)
            else:
                registry = self._client.registries.begin_create(
                    self._rg_name,
                    self._registry_name,
                    Registry(
                        location=self._location,
                        sku=Sku(name="Basic"),
                        admin_user_enabled=True,
                        tags=self._tags,
                    ),
                ).result()

            creds = self._client.registries.list_credentials(self._rg_name, self._registry_name)

            return ProvisionResult(
                name=self.name,
                success=True,
                info={
                    "login_server": registry.login_server,
                    "username": creds.username,
                    "password": creds.passwords[0].value,
                    "registry_name": self._registry_name,
                },
            )
        except Exception as e:
            return ProvisionResult(name=self.name, success=False, error=str(e))

    def health_check(self) -> HealthCheck:
        return NoopHealthCheck()
