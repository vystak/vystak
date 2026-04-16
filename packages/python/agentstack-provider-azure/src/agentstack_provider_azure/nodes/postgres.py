"""AzurePostgresNode — provisions Azure Database for PostgreSQL Flexible Server."""

from agentstack.provisioning.health import HealthCheck, NoopHealthCheck, TcpHealthCheck
from agentstack.provisioning.node import Provisionable, ProvisionResult

from azure.core.exceptions import ResourceNotFoundError
from azure.mgmt.rdbms.postgresql_flexibleservers.models import (
    Backup,
    Database,
    FirewallRule,
    Server,
    Sku,
    Storage,
)


class AzurePostgresNode(Provisionable):
    """Creates an Azure Database for PostgreSQL Flexible Server."""

    def __init__(
        self,
        client,
        rg_name: str,
        server_name: str,
        service_name: str,
        location: str,
        admin_password: str,
        config: dict | None = None,
        tags: dict | None = None,
    ):
        self._client = client
        self._rg_name = rg_name
        self._server_name = server_name
        self._service_name = service_name
        self._location = location
        self._admin_password = admin_password
        self._config = config or {}
        self._tags = tags or {}
        self._host: str | None = None

    @property
    def name(self) -> str:
        return self._service_name

    @property
    def depends_on(self) -> list[str]:
        return ["resource-group"]

    def provision(self, context: dict) -> ProvisionResult:
        try:
            sku_name = self._config.get("sku", "Standard_B1ms")
            version = self._config.get("version", "16")
            storage_gb = self._config.get("storage_gb", 32)
            backup_days = self._config.get("backup_retention_days", 7)

            # 1. Check if server already exists
            try:
                existing = self._client.servers.get(self._rg_name, self._server_name)
                self._host = existing.fully_qualified_domain_name
                self.emit("Postgres server exists", self._server_name)
            except ResourceNotFoundError:
                # 2. Create Flexible Server
                self.emit("Creating Postgres server", self._server_name)
                server = self._client.servers.begin_create(
                    self._rg_name,
                    self._server_name,
                    Server(
                        location=self._location,
                        sku=Sku(name=sku_name, tier=self._tier_from_sku(sku_name)),
                        administrator_login="agentstack",
                        administrator_login_password=self._admin_password,
                        version=version,
                        storage=Storage(storage_size_gb=storage_gb),
                        backup=Backup(backup_retention_days=backup_days),
                        tags=self._tags,
                    ),
                ).result()
                self._host = server.fully_qualified_domain_name

                # 3. Create firewall rule to allow Azure services
                self.emit("Configuring firewall", "AllowAzureServices")
                self._client.firewall_rules.begin_create_or_update(
                    self._rg_name,
                    self._server_name,
                    "AllowAzureServices",
                    FirewallRule(start_ip_address="0.0.0.0", end_ip_address="0.0.0.0"),
                ).result()

            # 4. Create database (idempotent)
            self.emit("Creating database", "agentstack")
            self._client.databases.begin_create(
                self._rg_name,
                self._server_name,
                "agentstack",
                Database(),
            ).result()

            connection_string = (
                f"postgresql://agentstack:{self._admin_password}"
                f"@{self._host}:5432/agentstack?sslmode=require"
            )

            self.emit("Postgres ready", self._host)

            return ProvisionResult(
                name=self.name,
                success=True,
                info={
                    "engine": "postgres",
                    "server_name": self._server_name,
                    "host": self._host,
                    "connection_string": connection_string,
                },
            )
        except Exception as e:
            return ProvisionResult(name=self.name, success=False, error=str(e))

    def health_check(self) -> HealthCheck:
        # NoopHealthCheck — Azure Flexible Server is ready when begin_create completes.
        # TcpHealthCheck would fail from local machine (firewall blocks non-Azure IPs).
        return NoopHealthCheck()

    @staticmethod
    def _tier_from_sku(sku_name: str) -> str:
        """Derive the SKU tier from the SKU name prefix."""
        lower = sku_name.lower()
        if lower.startswith("standard_b"):
            return "Burstable"
        if lower.startswith("standard_d"):
            return "GeneralPurpose"
        if lower.startswith("standard_e"):
            return "MemoryOptimized"
        return "Burstable"
