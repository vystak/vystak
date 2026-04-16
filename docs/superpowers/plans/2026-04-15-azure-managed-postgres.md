# Azure Managed Postgres Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Azure Database for PostgreSQL Flexible Server provisioning so agents deployed to Azure Container Apps can use Postgres-backed sessions and memory.

**Architecture:** A new `AzurePostgresNode` (Provisionable) creates a Flexible Server, firewall rule, and database. It returns a connection string in `ProvisionResult.info`. The Azure provider adds this node to the provision graph when agents reference managed Postgres services. ContainerAppNode and DockerAgentNode are updated to properly map both `SESSION_STORE_URL` and `MEMORY_STORE_URL` env vars from upstream service results.

**Tech Stack:** `azure-mgmt-rdbms` (PostgreSQL Flexible Server SDK), existing provisioning engine, existing secrets utility.

---

## File Structure

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `packages/python/agentstack-provider-azure/src/agentstack_provider_azure/nodes/postgres.py` | AzurePostgresNode — provisions Flexible Server + firewall + database |
| Modify | `packages/python/agentstack-provider-azure/src/agentstack_provider_azure/nodes/__init__.py` | Export AzurePostgresNode |
| Modify | `packages/python/agentstack-provider-azure/src/agentstack_provider_azure/provider.py` | Add Postgres nodes to provision graph |
| Modify | `packages/python/agentstack-provider-azure/pyproject.toml` | Add `azure-mgmt-rdbms` dependency |
| Modify | `packages/python/agentstack-provider-azure/src/agentstack_provider_azure/nodes/aca_app.py` | Wire `SESSION_STORE_URL` + `MEMORY_STORE_URL` from context |
| Modify | `packages/python/agentstack-provider-docker/src/agentstack_provider_docker/nodes/agent.py` | Wire `MEMORY_STORE_URL` (currently only sets `SESSION_STORE_URL`) |
| Create | `packages/python/agentstack-provider-azure/tests/test_postgres_node.py` | Unit tests for AzurePostgresNode |
| Modify | `packages/python/agentstack-provider-azure/tests/test_nodes.py` | Add ContainerAppNode tests for Postgres env var wiring |

---

### Task 1: Add `azure-mgmt-rdbms` dependency

**Files:**
- Modify: `packages/python/agentstack-provider-azure/pyproject.toml`

- [ ] **Step 1: Add the dependency**

In `packages/python/agentstack-provider-azure/pyproject.toml`, add `azure-mgmt-rdbms` to the dependencies list:

```toml
dependencies = [
    "agentstack>=0.1.0",
    "azure-identity>=1.15",
    "azure-mgmt-resource>=23.0",
    "azure-mgmt-containerregistry>=10.0",
    "azure-mgmt-appcontainers>=3.0",
    "azure-mgmt-loganalytics>=13.0",
    "azure-mgmt-rdbms>=10.2",
    "docker>=7.0",
]
```

- [ ] **Step 2: Sync dependencies**

Run:
```bash
cd ~/Developer/work/AgentsStack && uv sync
```
Expected: Resolves and installs `azure-mgmt-rdbms`. No errors.

- [ ] **Step 3: Verify import**

Run:
```bash
cd ~/Developer/work/AgentsStack && uv run python -c "from azure.mgmt.rdbms.postgresql_flexibleservers import PostgreSQLManagementClient; print('OK')"
```
Expected: Prints `OK`.

- [ ] **Step 4: Commit**

```bash
git add packages/python/agentstack-provider-azure/pyproject.toml uv.lock
git commit -m "feat(azure): add azure-mgmt-rdbms dependency for Postgres support"
```

---

### Task 2: Create AzurePostgresNode

**Files:**
- Create: `packages/python/agentstack-provider-azure/src/agentstack_provider_azure/nodes/postgres.py`
- Create: `packages/python/agentstack-provider-azure/tests/test_postgres_node.py`

- [ ] **Step 1: Write the failing tests**

Create `packages/python/agentstack-provider-azure/tests/test_postgres_node.py`:

```python
"""Tests for AzurePostgresNode."""

import re
from unittest.mock import MagicMock, patch

import pytest

from agentstack.provisioning.health import NoopHealthCheck, TcpHealthCheck
from agentstack.provisioning.node import ProvisionResult

from agentstack_provider_azure.nodes.postgres import AzurePostgresNode


class TestAzurePostgresNode:
    def _make_node(self, server_name="test-rg-main-db", service_name="main-db", config=None):
        client = MagicMock()
        return AzurePostgresNode(
            client=client,
            rg_name="test-rg",
            server_name=server_name,
            service_name=service_name,
            location="eastus2",
            admin_password="test-secret-pw",
            config=config or {},
            tags={"agentstack:managed": "true"},
        )

    def test_name(self):
        node = self._make_node()
        assert node.name == "main-db"

    def test_depends_on(self):
        node = self._make_node()
        assert node.depends_on == ["resource-group"]

    def test_provision_creates_server(self):
        node = self._make_node()

        # Server does not exist — raises ResourceNotFoundError on GET
        from azure.core.exceptions import ResourceNotFoundError
        node._client.servers.get.side_effect = ResourceNotFoundError("not found")

        # Mock begin_create returns a poller whose result() gives a server object
        server_result = MagicMock()
        server_result.state = "Ready"
        server_result.fully_qualified_domain_name = "test-rg-main-db.postgres.database.azure.com"
        node._client.servers.begin_create.return_value.result.return_value = server_result

        # Mock firewall rule creation
        node._client.firewall_rules.begin_create_or_update.return_value.result.return_value = MagicMock()

        # Mock database creation
        node._client.databases.begin_create_or_update.return_value.result.return_value = MagicMock()

        result = node.provision({"resource-group": ProvisionResult(name="resource-group", success=True, info={"rg_name": "test-rg"})})

        assert result.success is True
        assert result.info["engine"] == "postgres"
        assert result.info["server_name"] == "test-rg-main-db"
        assert result.info["host"] == "test-rg-main-db.postgres.database.azure.com"
        assert "connection_string" in result.info
        assert "sslmode=require" in result.info["connection_string"]
        assert "agentstack:test-secret-pw@" in result.info["connection_string"]

        node._client.servers.begin_create.assert_called_once()
        node._client.firewall_rules.begin_create_or_update.assert_called_once()
        node._client.databases.begin_create_or_update.assert_called_once()

    def test_provision_reuses_existing_server(self):
        node = self._make_node()

        # Server exists
        existing = MagicMock()
        existing.state = "Ready"
        existing.fully_qualified_domain_name = "test-rg-main-db.postgres.database.azure.com"
        node._client.servers.get.return_value = existing

        # Database may or may not exist — create is idempotent
        node._client.databases.begin_create_or_update.return_value.result.return_value = MagicMock()

        result = node.provision({"resource-group": ProvisionResult(name="resource-group", success=True, info={"rg_name": "test-rg"})})

        assert result.success is True
        assert result.info["host"] == "test-rg-main-db.postgres.database.azure.com"
        # Should NOT create a new server
        node._client.servers.begin_create.assert_not_called()

    def test_provision_with_custom_config(self):
        node = self._make_node(config={
            "sku": "Standard_B2s",
            "version": "15",
            "storage_gb": 64,
            "backup_retention_days": 14,
        })

        from azure.core.exceptions import ResourceNotFoundError
        node._client.servers.get.side_effect = ResourceNotFoundError("not found")

        server_result = MagicMock()
        server_result.state = "Ready"
        server_result.fully_qualified_domain_name = "test-rg-main-db.postgres.database.azure.com"
        node._client.servers.begin_create.return_value.result.return_value = server_result
        node._client.firewall_rules.begin_create_or_update.return_value.result.return_value = MagicMock()
        node._client.databases.begin_create_or_update.return_value.result.return_value = MagicMock()

        result = node.provision({"resource-group": ProvisionResult(name="resource-group", success=True, info={"rg_name": "test-rg"})})
        assert result.success is True

        # Verify the create call used custom config
        call_args = node._client.servers.begin_create.call_args
        server_params = call_args[0][2]  # Third positional arg is the Server object
        assert server_params.sku.name == "Standard_B2s"
        assert server_params.version == "15"
        assert server_params.storage.storage_size_gb == 64
        assert server_params.backup.backup_retention_days == 14

    def test_provision_error(self):
        node = self._make_node()

        from azure.core.exceptions import ResourceNotFoundError
        node._client.servers.get.side_effect = ResourceNotFoundError("not found")
        node._client.servers.begin_create.side_effect = Exception("Azure API error")

        result = node.provision({"resource-group": ProvisionResult(name="resource-group", success=True, info={"rg_name": "test-rg"})})
        assert result.success is False
        assert "Azure API error" in result.error

    def test_health_check_with_host(self):
        node = self._make_node()
        node._host = "test-rg-main-db.postgres.database.azure.com"
        hc = node.health_check()
        assert isinstance(hc, TcpHealthCheck)

    def test_health_check_without_host(self):
        node = self._make_node()
        hc = node.health_check()
        assert isinstance(hc, NoopHealthCheck)
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
cd ~/Developer/work/AgentsStack && uv run pytest packages/python/agentstack-provider-azure/tests/test_postgres_node.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'agentstack_provider_azure.nodes.postgres'`

- [ ] **Step 3: Implement AzurePostgresNode**

Create `packages/python/agentstack-provider-azure/src/agentstack_provider_azure/nodes/postgres.py`:

```python
"""AzurePostgresNode — provisions Azure Database for PostgreSQL Flexible Server."""

from agentstack.provisioning.health import HealthCheck, NoopHealthCheck, TcpHealthCheck
from agentstack.provisioning.node import Provisionable, ProvisionResult

from azure.core.exceptions import ResourceNotFoundError
from azure.mgmt.rdbms.postgresql_flexibleservers.models import (
    Backup,
    Database,
    FirewallRule,
    Server,
    ServerVersion,
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
                        version=ServerVersion(version),
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
            self._client.databases.begin_create_or_update(
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
        if self._host:
            return TcpHealthCheck(self._host, 5432)
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
cd ~/Developer/work/AgentsStack && uv run pytest packages/python/agentstack-provider-azure/tests/test_postgres_node.py -v
```
Expected: All 7 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/python/agentstack-provider-azure/src/agentstack_provider_azure/nodes/postgres.py packages/python/agentstack-provider-azure/tests/test_postgres_node.py
git commit -m "feat(azure): add AzurePostgresNode for Flexible Server provisioning"
```

---

### Task 3: Export AzurePostgresNode from nodes package

**Files:**
- Modify: `packages/python/agentstack-provider-azure/src/agentstack_provider_azure/nodes/__init__.py`

- [ ] **Step 1: Update the exports**

Replace the full contents of `packages/python/agentstack-provider-azure/src/agentstack_provider_azure/nodes/__init__.py` with:

```python
"""Azure provider node types for the provisioning graph."""

from agentstack_provider_azure.nodes.resource_group import ResourceGroupNode
from agentstack_provider_azure.nodes.log_analytics import LogAnalyticsNode
from agentstack_provider_azure.nodes.acr import ACRNode
from agentstack_provider_azure.nodes.aca_environment import ACAEnvironmentNode
from agentstack_provider_azure.nodes.aca_app import ContainerAppNode
from agentstack_provider_azure.nodes.postgres import AzurePostgresNode

__all__ = [
    "ResourceGroupNode",
    "LogAnalyticsNode",
    "ACRNode",
    "ACAEnvironmentNode",
    "ContainerAppNode",
    "AzurePostgresNode",
]
```

- [ ] **Step 2: Verify import works**

Run:
```bash
cd ~/Developer/work/AgentsStack && uv run python -c "from agentstack_provider_azure.nodes import AzurePostgresNode; print('OK')"
```
Expected: Prints `OK`.

- [ ] **Step 3: Commit**

```bash
git add packages/python/agentstack-provider-azure/src/agentstack_provider_azure/nodes/__init__.py
git commit -m "feat(azure): export AzurePostgresNode from nodes package"
```

---

### Task 4: Wire Postgres into the Azure provider's provision graph

**Files:**
- Modify: `packages/python/agentstack-provider-azure/src/agentstack_provider_azure/provider.py`

- [ ] **Step 1: Add import for AzurePostgresNode and secrets**

At the top of `packages/python/agentstack-provider-azure/src/agentstack_provider_azure/provider.py`, add to the imports from `agentstack_provider_azure.nodes`:

```python
from agentstack_provider_azure.nodes import (
    ACRNode,
    ACAEnvironmentNode,
    AzurePostgresNode,
    ContainerAppNode,
    LogAnalyticsNode,
    ResourceGroupNode,
)
```

Also add the secrets import at the top of the file:

```python
from agentstack_provider_docker.secrets import get_resource_password
```

- [ ] **Step 2: Add helper method `_postgres_server_name`**

Add this method to the `AzureProvider` class, after the `_tags` method (around line 100):

```python
    @staticmethod
    def _postgres_server_name(rg_name: str, service_name: str) -> str:
        """Derive a globally unique Postgres server name from RG + service name."""
        import re
        raw = f"{rg_name}-{service_name}"
        sanitized = re.sub(r"[^a-z0-9-]", "-", raw.lower())
        # Azure requires 3-63 chars, must start/end with letter or number
        sanitized = sanitized.strip("-")[:63]
        return sanitized
```

- [ ] **Step 3: Add Postgres nodes to the provision graph in `apply()`**

In the `apply()` method, after the line that adds the `ACAEnvironmentNode` and before the line that adds the `ContainerAppNode`, insert logic to collect unique managed Postgres services and add them to the graph:

```python
            # Collect unique managed Postgres services from agent
            postgres_services = {}
            for svc in [self._agent.sessions, self._agent.memory] + list(self._agent.services):
                if svc and svc.type == "postgres" and svc.is_managed:
                    if svc.name not in postgres_services:
                        postgres_services[svc.name] = svc

            secrets_path = Path(".agentstack") / "secrets.json"
            for svc_name, svc in postgres_services.items():
                server_name = self._postgres_server_name(rg_name, svc_name)
                password = get_resource_password(f"azure-postgres-{server_name}", secrets_path)
                graph.add(AzurePostgresNode(
                    client=postgres_client,
                    rg_name=rg_name,
                    server_name=server_name,
                    service_name=svc_name,
                    location=location,
                    admin_password=password,
                    config=svc.config,
                    tags=tags,
                ))
```

Also, create the `postgres_client` alongside the other Azure clients. Add this after the existing client creation block:

```python
            # Create Postgres client only if needed
            postgres_client = None
            if postgres_services:
                from azure.mgmt.rdbms.postgresql_flexibleservers import PostgreSQLManagementClient
                postgres_client = PostgreSQLManagementClient(credential, subscription_id)
```

Note: Move the `postgres_services` collection **before** the client creation, so we know whether to create the postgres client. The final order in `apply()` should be:

1. Get config, credential, subscription_id, location
2. Create resource/la/acr/aca clients
3. Collect `postgres_services` from agent
4. Create `postgres_client` if needed
5. Add nodes to graph (RG, LA, ACR, ACA Env, Postgres nodes, ContainerApp)

- [ ] **Step 4: Run existing tests to ensure nothing breaks**

Run:
```bash
cd ~/Developer/work/AgentsStack && uv run pytest packages/python/agentstack-provider-azure/tests/ -v
```
Expected: All existing tests pass. The provider tests use mocked agents without sessions/memory, so the new code path won't execute.

- [ ] **Step 5: Commit**

```bash
git add packages/python/agentstack-provider-azure/src/agentstack_provider_azure/provider.py
git commit -m "feat(azure): wire AzurePostgresNode into provision graph"
```

---

### Task 5: Wire connection strings in ContainerAppNode (Azure)

**Files:**
- Modify: `packages/python/agentstack-provider-azure/src/agentstack_provider_azure/nodes/aca_app.py`
- Modify: `packages/python/agentstack-provider-azure/tests/test_nodes.py`

- [ ] **Step 1: Write the failing test**

Add to the `TestContainerAppNode` class in `packages/python/agentstack-provider-azure/tests/test_nodes.py`:

```python
    @patch.dict(os.environ, {"API_KEY": "key-val", "DB_PASS": "db-val"})
    @patch("agentstack_provider_azure.nodes.aca_app.subprocess.run")
    def test_provision_with_postgres_env_vars(self, mock_subprocess, tmp_path):
        node = self._make_node()

        # Give the agent sessions and memory fields
        sessions_svc = MagicMock()
        sessions_svc.name = "sessions-db"
        sessions_svc.connection_string_env = None
        memory_svc = MagicMock()
        memory_svc.name = "memory-db"
        memory_svc.connection_string_env = None
        node._agent.sessions = sessions_svc
        node._agent.memory = memory_svc
        node._agent.services = []

        mock_subprocess.return_value = MagicMock(returncode=0, stderr="")

        app_result = MagicMock()
        app_result.configuration.ingress.fqdn = "my-agent.eastus.azurecontainerapps.io"
        node._aca_client.container_apps.begin_create_or_update.return_value.result.return_value = app_result

        context = {
            "aca-environment": ProvisionResult(
                name="aca-environment", success=True,
                info={"environment_id": "/sub/env-id", "default_domain": "test.io"},
            ),
            "acr": ProvisionResult(
                name="acr", success=True,
                info={"login_server": "testreg.azurecr.io", "username": "testreg", "password": "secret-pass", "registry_name": "testreg"},
            ),
            "sessions-db": ProvisionResult(
                name="sessions-db", success=True,
                info={"engine": "postgres", "connection_string": "postgresql://agentstack:pw@host:5432/agentstack?sslmode=require"},
            ),
            "memory-db": ProvisionResult(
                name="memory-db", success=True,
                info={"engine": "postgres", "connection_string": "postgresql://agentstack:pw2@host2:5432/agentstack?sslmode=require"},
            ),
        }

        with patch("agentstack_provider_azure.nodes.aca_app.Path") as mock_path_cls:
            mock_build_dir = MagicMock()
            mock_path_cls.return_value.__truediv__ = lambda self, other: mock_build_dir
            mock_build_dir.__truediv__ = lambda self, other: MagicMock()
            mock_build_dir.mkdir = MagicMock()
            mock_build_dir.__str__ = lambda self: "/tmp/fake-build"
            result = node.provision(context)

        assert result.success is True

        # Verify the ContainerApp was created with the correct env vars
        create_call = node._aca_client.container_apps.begin_create_or_update
        call_args = create_call.call_args
        container_app = call_args[0][2]  # Third positional arg
        env_list = container_app.template.containers[0].env

        env_dict = {}
        for e in env_list:
            if hasattr(e, "get"):
                env_dict[e.get("name", e.get("Name"))] = e.get("value", e.get("secretRef"))
            elif isinstance(e, dict):
                env_dict[e["name"]] = e.get("value", e.get("secretRef"))

        assert "SESSION_STORE_URL" in env_dict or any(
            (e.get("name") if isinstance(e, dict) else getattr(e, "name", None)) == "SESSION_STORE_URL"
            for e in env_list
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
cd ~/Developer/work/AgentsStack && uv run pytest packages/python/agentstack-provider-azure/tests/test_nodes.py::TestContainerAppNode::test_provision_with_postgres_env_vars -v
```
Expected: FAIL — `SESSION_STORE_URL` not found in env vars.

- [ ] **Step 3: Update ContainerAppNode to wire connection strings**

In `packages/python/agentstack-provider-azure/src/agentstack_provider_azure/nodes/aca_app.py`, add `agent` attribute access for sessions/memory. In the `provision()` method, after the section that injects secrets env vars (around line 145, after the `for key, value in self._platform_config.get("env", {}).items():` loop), add:

```python
            # Inject database connection strings from upstream Postgres nodes
            if hasattr(self._agent, "sessions") and self._agent.sessions:
                svc = self._agent.sessions
                if svc.connection_string_env:
                    # Bring-your-own: pass the env var name through
                    env_vars.append({"name": "SESSION_STORE_URL", "value": f"${{{svc.connection_string_env}}}"})
                else:
                    pg_result = context.get(svc.name)
                    if pg_result and pg_result.info.get("connection_string"):
                        safe = "session-store-url"
                        aca_secrets.append(Secret(name=safe, value=pg_result.info["connection_string"]))
                        env_vars.append({"name": "SESSION_STORE_URL", "secretRef": safe})

            if hasattr(self._agent, "memory") and self._agent.memory:
                svc = self._agent.memory
                if svc.connection_string_env:
                    env_vars.append({"name": "MEMORY_STORE_URL", "value": f"${{{svc.connection_string_env}}}"})
                else:
                    pg_result = context.get(svc.name)
                    if pg_result and pg_result.info.get("connection_string"):
                        safe = "memory-store-url"
                        aca_secrets.append(Secret(name=safe, value=pg_result.info["connection_string"]))
                        env_vars.append({"name": "MEMORY_STORE_URL", "secretRef": safe})
```

- [ ] **Step 4: Update ContainerAppNode.depends_on to include Postgres nodes**

In the same file, update the `depends_on` property to include Postgres service dependencies:

```python
    @property
    def depends_on(self) -> list[str]:
        deps = ["aca-environment", "acr"]
        if hasattr(self._agent, "sessions") and self._agent.sessions and self._agent.sessions.is_managed:
            deps.append(self._agent.sessions.name)
        if hasattr(self._agent, "memory") and self._agent.memory and self._agent.memory.is_managed:
            if self._agent.memory.name not in deps:
                deps.append(self._agent.memory.name)
        return deps
```

- [ ] **Step 5: Run all Azure tests**

Run:
```bash
cd ~/Developer/work/AgentsStack && uv run pytest packages/python/agentstack-provider-azure/tests/ -v
```
Expected: All tests pass including the new Postgres env var test.

- [ ] **Step 6: Commit**

```bash
git add packages/python/agentstack-provider-azure/src/agentstack_provider_azure/nodes/aca_app.py packages/python/agentstack-provider-azure/tests/test_nodes.py
git commit -m "feat(azure): wire SESSION_STORE_URL and MEMORY_STORE_URL in ContainerAppNode"
```

---

### Task 6: Fix DockerAgentNode to set MEMORY_STORE_URL

**Files:**
- Modify: `packages/python/agentstack-provider-docker/src/agentstack_provider_docker/nodes/agent.py`

- [ ] **Step 1: Write the failing test**

Find the Docker agent node test file. Add a test for MEMORY_STORE_URL. Create or modify `packages/python/agentstack-provider-docker/tests/test_agent_node.py` (or the existing test file that tests DockerAgentNode). Add:

```python
def test_provision_sets_memory_store_url(self):
    """MEMORY_STORE_URL should be set from the memory service's connection string."""
    # Setup: agent with separate sessions and memory services
    agent = MagicMock()
    agent.name = "test-agent"
    agent.port = 8000
    sessions_svc = MagicMock()
    sessions_svc.name = "sessions"
    memory_svc = MagicMock()
    memory_svc.name = "memory"
    agent.sessions = sessions_svc
    agent.memory = memory_svc
    agent.services = []
    agent.secrets = []
    agent.mcp_servers = []

    # ... (construct node, mock client, provision with context containing both services)
    # Assert that env dict contains both SESSION_STORE_URL and MEMORY_STORE_URL
```

- [ ] **Step 2: Update the connection string injection in DockerAgentNode**

In `packages/python/agentstack-provider-docker/src/agentstack_provider_docker/nodes/agent.py`, replace the current connection string injection block (around lines 118-124):

```python
            # Connection strings from context
            for dep_name in self.depends_on:
                if dep_name == "network":
                    continue
                dep_result = context.get(dep_name)
                if dep_result and dep_result.info.get("connection_string"):
                    env["SESSION_STORE_URL"] = dep_result.info["connection_string"]
```

With:

```python
            # Connection strings from upstream services
            if self._agent.sessions:
                dep_result = context.get(self._agent.sessions.name)
                if dep_result and dep_result.info.get("connection_string"):
                    env["SESSION_STORE_URL"] = dep_result.info["connection_string"]

            if self._agent.memory:
                dep_result = context.get(self._agent.memory.name)
                if dep_result and dep_result.info.get("connection_string"):
                    env["MEMORY_STORE_URL"] = dep_result.info["connection_string"]
```

- [ ] **Step 3: Run Docker provider tests**

Run:
```bash
cd ~/Developer/work/AgentsStack && uv run pytest packages/python/agentstack-provider-docker/tests/ -v
```
Expected: All tests pass.

- [ ] **Step 4: Commit**

```bash
git add packages/python/agentstack-provider-docker/src/agentstack_provider_docker/nodes/agent.py
git commit -m "fix(docker): set both SESSION_STORE_URL and MEMORY_STORE_URL from service context"
```

---

### Task 7: Integration test — deploy agent with Postgres to Azure

**Files:**
- No new files — manual verification

This task is a manual integration test to verify the full flow works end-to-end.

- [ ] **Step 1: Create a test agent definition**

Use the existing `examples/azure-multi-agent/` setup or create a temporary test:

```python
from agentstack import Agent, Provider, Platform, Postgres

azure = Provider(type="azure", config={
    "resource_group": "agentstack-postgres-test-rg",
    "location": "eastus2",
})

aca = Platform(type="container-apps", provider=azure)
db = Postgres(name="test-db", provider=azure)

agent = Agent(
    name="postgres-test-agent",
    platform=aca,
    sessions=db,
    model={"provider": "anthropic", "name": "claude-sonnet-4-20250514"},
    secrets=[{"name": "ANTHROPIC_API_KEY"}],
)
```

- [ ] **Step 2: Deploy**

Run:
```bash
agentstack apply examples/postgres-test/agentstack.py --force
```
Expected: 
- ResourceGroup created
- LogAnalytics created
- ACR created
- ACA Environment created
- **Postgres server created** (takes ~3-5 min)
- **Firewall rule configured**
- **Database created**
- Container App deployed with `SESSION_STORE_URL` set

- [ ] **Step 3: Verify agent works with sessions**

Run:
```bash
agentstack-chat --url <agent-url>
```
Send a message, then send another — verify the agent remembers the conversation (session persistence via Postgres).

- [ ] **Step 4: Verify idempotent redeploy**

Run:
```bash
agentstack apply examples/postgres-test/agentstack.py
```
Expected: Skips deploy (hash unchanged). If `--force`, redeploy reuses existing Postgres server.

- [ ] **Step 5: Clean up**

Run:
```bash
agentstack destroy examples/postgres-test/agentstack.py --include-resources
```
Expected: Deletes Container App, then Postgres Flexible Server, then other resources.
