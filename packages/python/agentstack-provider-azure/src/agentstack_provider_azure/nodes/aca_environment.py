"""ACAEnvironmentNode — creates or reuses an Azure Container Apps Managed Environment."""

from agentstack.provisioning.health import HealthCheck, NoopHealthCheck
from agentstack.provisioning.node import Provisionable, ProvisionResult

from azure.mgmt.appcontainers.models import (
    AppLogsConfiguration,
    LogAnalyticsConfiguration,
    ManagedEnvironment,
)


class ACAEnvironmentNode(Provisionable):
    """Creates an ACA Managed Environment with Log Analytics, or reuses an existing one."""

    def __init__(
        self,
        client,
        rg_name: str,
        env_name: str,
        location: str,
        existing: bool = False,
    ):
        self._client = client
        self._rg_name = rg_name
        self._env_name = env_name
        self._location = location
        self._existing = existing

    @property
    def name(self) -> str:
        return "aca-environment"

    @property
    def depends_on(self) -> list[str]:
        return ["resource-group", "log-analytics"]

    def provision(self, context: dict) -> ProvisionResult:
        try:
            if self._existing:
                env = self._client.managed_environments.get(
                    self._rg_name, self._env_name
                )
            else:
                la_info = context["log-analytics"].info
                env = self._client.managed_environments.begin_create_or_update(
                    self._rg_name,
                    self._env_name,
                    ManagedEnvironment(
                        location=self._location,
                        app_logs_configuration=AppLogsConfiguration(
                            destination="log-analytics",
                            log_analytics_configuration=LogAnalyticsConfiguration(
                                customer_id=la_info["customer_id"],
                                shared_key=la_info["shared_key"],
                            ),
                        ),
                    ),
                ).result()

            return ProvisionResult(
                name=self.name,
                success=True,
                info={
                    "environment_id": env.id,
                    "default_domain": env.default_domain,
                },
            )
        except Exception as e:
            return ProvisionResult(name=self.name, success=False, error=str(e))

    def health_check(self) -> HealthCheck:
        return NoopHealthCheck()
