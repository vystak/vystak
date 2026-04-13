# Azure Provider Phase 2a — Minimal Deploy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deploy a minimal agent (no postgres, no VNet) to Azure Container Apps with `agentstack apply`.

**Architecture:** New `agentstack-provider-azure` package with `AzureProvider` implementing `PlatformProvider`. Uses `ProvisionGraph` with Azure-specific node types. CLI updated with a provider factory to select Docker vs Azure based on agent definition.

**Tech Stack:** Python 3.11+, azure-identity, azure-mgmt-resource, azure-mgmt-containerregistry, azure-mgmt-appcontainers, azure-mgmt-loganalytics, docker SDK (local image build)

**Scope:** Resource Group → Log Analytics → ACR → ACA Environment → Container App. No VNet, no Postgres, no Key Vault (Phase 2b).

---

### Task 1: Scaffold the azure provider package

**Files:**
- Create: `packages/python/agentstack-provider-azure/pyproject.toml`
- Create: `packages/python/agentstack-provider-azure/src/agentstack_provider_azure/__init__.py`
- Create: `packages/python/agentstack-provider-azure/src/agentstack_provider_azure/auth.py`
- Create: `packages/python/agentstack-provider-azure/tests/__init__.py`
- Create: `packages/python/agentstack-provider-azure/tests/test_auth.py`
- Modify: `pyproject.toml` (root — add to workspace)

- [ ] **Step 1: Create pyproject.toml**

```toml
# packages/python/agentstack-provider-azure/pyproject.toml
[project]
name = "agentstack-provider-azure"
version = "0.1.0"
description = "AgentStack Azure Container Apps platform provider"
requires-python = ">=3.11"
license = "Apache-2.0"
dependencies = [
    "agentstack>=0.1.0",
    "azure-identity>=1.15",
    "azure-mgmt-resource>=23.0",
    "azure-mgmt-containerregistry>=10.0",
    "azure-mgmt-appcontainers>=3.0",
    "azure-mgmt-loganalytics>=13.0",
    "docker>=7.0",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/agentstack_provider_azure"]

[tool.uv.sources]
agentstack = { workspace = true }
```

- [ ] **Step 2: Create auth module with tests**

```python
# packages/python/agentstack-provider-azure/tests/__init__.py
```

```python
# packages/python/agentstack-provider-azure/tests/test_auth.py
from unittest.mock import MagicMock, patch

import pytest


class TestGetCredential:
    def test_returns_default_credential(self):
        from agentstack_provider_azure.auth import get_credential
        with patch("agentstack_provider_azure.auth.DefaultAzureCredential") as mock_cred:
            mock_cred.return_value = MagicMock()
            cred = get_credential()
            assert cred is not None
            mock_cred.assert_called_once()


class TestGetSubscriptionId:
    def test_from_config(self):
        from agentstack_provider_azure.auth import get_subscription_id
        sub_id = get_subscription_id(config={"subscription_id": "test-sub-123"})
        assert sub_id == "test-sub-123"

    def test_from_env(self):
        from agentstack_provider_azure.auth import get_subscription_id
        with patch.dict("os.environ", {"AZURE_SUBSCRIPTION_ID": "env-sub-456"}):
            sub_id = get_subscription_id(config={})
            assert sub_id == "env-sub-456"

    def test_from_cli(self):
        from agentstack_provider_azure.auth import get_subscription_id
        with patch("agentstack_provider_azure.auth.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout='{"id": "cli-sub-789"}',
            )
            with patch.dict("os.environ", {}, clear=True):
                sub_id = get_subscription_id(config={})
                assert sub_id == "cli-sub-789"

    def test_raises_when_not_found(self):
        from agentstack_provider_azure.auth import get_subscription_id
        with patch("agentstack_provider_azure.auth.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="")
            with patch.dict("os.environ", {}, clear=True):
                with pytest.raises(ValueError, match="subscription"):
                    get_subscription_id(config={})
```

```python
# packages/python/agentstack-provider-azure/src/agentstack_provider_azure/__init__.py
"""AgentStack Azure Container Apps provider."""

__version__ = "0.1.0"
```

```python
# packages/python/agentstack-provider-azure/src/agentstack_provider_azure/auth.py
"""Azure authentication — DefaultAzureCredential with CLI fallback."""

import json
import os
import subprocess

from azure.identity import DefaultAzureCredential


def get_credential() -> DefaultAzureCredential:
    """Get Azure credentials. Tries CLI auth first, falls back to service principal env vars."""
    return DefaultAzureCredential()


def get_subscription_id(config: dict) -> str:
    """Get Azure subscription ID from config, env, or CLI context."""
    # 1. Explicit config
    if config.get("subscription_id"):
        return config["subscription_id"]

    # 2. Environment variable
    env_sub = os.environ.get("AZURE_SUBSCRIPTION_ID")
    if env_sub:
        return env_sub

    # 3. az CLI context
    try:
        result = subprocess.run(
            ["az", "account", "show", "--output", "json"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            return data["id"]
    except (FileNotFoundError, json.JSONDecodeError, KeyError, subprocess.TimeoutExpired):
        pass

    raise ValueError(
        "Azure subscription ID not found. Set AZURE_SUBSCRIPTION_ID, "
        "add subscription_id to provider config, or run 'az login'."
    )


def get_location(config: dict) -> str:
    """Get Azure location from config or default."""
    return config.get("location", "eastus2")
```

- [ ] **Step 3: Add to workspace**

Edit root `pyproject.toml` — add `agentstack-provider-azure` to `[tool.uv]` dev-dependencies and `[tool.uv.sources]`:

Add to dev-dependencies:
```
"agentstack-provider-azure",
```

Add to sources:
```
agentstack-provider-azure = { workspace = true }
```

- [ ] **Step 4: Install and run tests**

Run:
```bash
cd ~/Developer/work/AgentsStack
uv sync
uv run pytest packages/python/agentstack-provider-azure/tests/ -v
```

Expected: All auth tests PASS

- [ ] **Step 5: Commit**

```bash
git add packages/python/agentstack-provider-azure/ pyproject.toml
git commit -m "feat: scaffold agentstack-provider-azure package with auth module"
```

---

### Task 2: Implement Azure node types (ResourceGroup, LogAnalytics, ACR, ACA Environment)

**Files:**
- Create: `packages/python/agentstack-provider-azure/src/agentstack_provider_azure/nodes/__init__.py`
- Create: `packages/python/agentstack-provider-azure/src/agentstack_provider_azure/nodes/resource_group.py`
- Create: `packages/python/agentstack-provider-azure/src/agentstack_provider_azure/nodes/log_analytics.py`
- Create: `packages/python/agentstack-provider-azure/src/agentstack_provider_azure/nodes/acr.py`
- Create: `packages/python/agentstack-provider-azure/src/agentstack_provider_azure/nodes/aca_environment.py`
- Create: `packages/python/agentstack-provider-azure/tests/test_nodes.py`

- [ ] **Step 1: Write tests for infrastructure nodes**

```python
# packages/python/agentstack-provider-azure/tests/test_nodes.py
from unittest.mock import MagicMock, patch

import pytest

from agentstack.provisioning.health import NoopHealthCheck
from agentstack.provisioning.node import ProvisionResult


class TestAzureResourceGroupNode:
    def test_provision_creates_rg(self):
        from agentstack_provider_azure.nodes.resource_group import AzureResourceGroupNode

        mock_client = MagicMock()
        mock_client.resource_groups.check_existence.return_value = False
        mock_client.resource_groups.create_or_update.return_value = MagicMock(name="agentstack-bot-rg")

        node = AzureResourceGroupNode(
            resource_client=mock_client,
            rg_name="agentstack-bot-rg",
            location="eastus2",
            tags={"agentstack:managed": "true"},
        )
        assert node.name == "resource-group"
        assert node.depends_on == []

        result = node.provision(context={})
        assert result.success
        assert result.info["rg_name"] == "agentstack-bot-rg"
        mock_client.resource_groups.create_or_update.assert_called_once()

    def test_provision_reuses_existing(self):
        from agentstack_provider_azure.nodes.resource_group import AzureResourceGroupNode

        mock_client = MagicMock()
        mock_client.resource_groups.check_existence.return_value = True

        node = AzureResourceGroupNode(
            resource_client=mock_client,
            rg_name="existing-rg",
            location="eastus2",
            tags={},
        )
        result = node.provision(context={})
        assert result.success
        mock_client.resource_groups.create_or_update.assert_not_called()

    def test_health_check_noop(self):
        from agentstack_provider_azure.nodes.resource_group import AzureResourceGroupNode

        node = AzureResourceGroupNode(MagicMock(), "rg", "eastus2", {})
        assert isinstance(node.health_check(), NoopHealthCheck)


class TestAzureLogAnalyticsNode:
    def test_provision(self):
        from agentstack_provider_azure.nodes.log_analytics import AzureLogAnalyticsNode

        mock_client = MagicMock()
        workspace = MagicMock()
        workspace.customer_id = "workspace-customer-id"
        mock_client.workspaces.begin_create_or_update.return_value.result.return_value = workspace

        mock_keys = MagicMock()
        mock_keys.primary_shared_key = "shared-key-123"
        mock_client.shared_keys.get_shared_keys.return_value = mock_keys

        node = AzureLogAnalyticsNode(
            log_client=mock_client,
            rg_name="rg",
            location="eastus2",
            workspace_name="agentstack-logs",
        )
        assert node.name == "log-analytics"
        assert "resource-group" in node.depends_on

        result = node.provision(context={
            "resource-group": ProvisionResult(name="resource-group", success=True, info={"rg_name": "rg"}),
        })
        assert result.success
        assert result.info["customer_id"] == "workspace-customer-id"
        assert result.info["shared_key"] == "shared-key-123"


class TestAzureACRNode:
    def test_provision_creates_registry(self):
        from agentstack_provider_azure.nodes.acr import AzureACRNode

        mock_client = MagicMock()
        registry = MagicMock()
        registry.login_server = "myacr.azurecr.io"
        mock_client.registries.begin_create.return_value.result.return_value = registry

        creds = MagicMock()
        creds.username = "myacr"
        creds.passwords = [MagicMock(value="password123")]
        mock_client.registries.list_credentials.return_value = creds

        node = AzureACRNode(
            acr_client=mock_client,
            rg_name="rg",
            location="eastus2",
            registry_name="myacr",
        )
        assert node.name == "acr"
        assert "resource-group" in node.depends_on

        result = node.provision(context={
            "resource-group": ProvisionResult(name="resource-group", success=True, info={"rg_name": "rg"}),
        })
        assert result.success
        assert result.info["login_server"] == "myacr.azurecr.io"
        assert result.info["username"] == "myacr"

    def test_uses_existing_registry(self):
        from agentstack_provider_azure.nodes.acr import AzureACRNode

        mock_client = MagicMock()
        node = AzureACRNode(
            acr_client=mock_client,
            rg_name="rg",
            location="eastus2",
            registry_name="myacr",
            existing=True,
        )
        result = node.provision(context={
            "resource-group": ProvisionResult(name="resource-group", success=True, info={"rg_name": "rg"}),
        })
        assert result.success
        mock_client.registries.begin_create.assert_not_called()


class TestAzureACAEnvironmentNode:
    def test_provision(self):
        from agentstack_provider_azure.nodes.aca_environment import AzureACAEnvironmentNode

        mock_client = MagicMock()
        env = MagicMock()
        env.id = "/subscriptions/.../managedEnvironments/myenv"
        env.default_domain = "myenv.eastus2.azurecontainerapps.io"
        mock_client.managed_environments.begin_create_or_update.return_value.result.return_value = env

        node = AzureACAEnvironmentNode(
            aca_client=mock_client,
            rg_name="rg",
            location="eastus2",
            env_name="agentstack-env",
        )
        assert node.name == "aca-environment"
        assert "resource-group" in node.depends_on
        assert "log-analytics" in node.depends_on

        result = node.provision(context={
            "resource-group": ProvisionResult(name="resource-group", success=True, info={"rg_name": "rg"}),
            "log-analytics": ProvisionResult(name="log-analytics", success=True, info={
                "customer_id": "cid", "shared_key": "key",
            }),
        })
        assert result.success
        assert "environment_id" in result.info
```

- [ ] **Step 2: Implement the four infrastructure node types**

```python
# packages/python/agentstack-provider-azure/src/agentstack_provider_azure/nodes/__init__.py
"""Azure provider node types for the provision graph."""

from agentstack_provider_azure.nodes.aca_app import AzureContainerAppNode
from agentstack_provider_azure.nodes.aca_environment import AzureACAEnvironmentNode
from agentstack_provider_azure.nodes.acr import AzureACRNode
from agentstack_provider_azure.nodes.log_analytics import AzureLogAnalyticsNode
from agentstack_provider_azure.nodes.resource_group import AzureResourceGroupNode

__all__ = [
    "AzureACRNode", "AzureACAEnvironmentNode", "AzureContainerAppNode",
    "AzureLogAnalyticsNode", "AzureResourceGroupNode",
]
```

```python
# packages/python/agentstack-provider-azure/src/agentstack_provider_azure/nodes/resource_group.py
"""Azure Resource Group node."""

from azure.mgmt.resource.resources.models import ResourceGroup

from agentstack.provisioning.health import NoopHealthCheck
from agentstack.provisioning.node import Provisionable, ProvisionResult


class AzureResourceGroupNode(Provisionable):
    def __init__(self, resource_client, rg_name: str, location: str, tags: dict):
        self._client = resource_client
        self._rg_name = rg_name
        self._location = location
        self._tags = tags

    @property
    def name(self) -> str:
        return "resource-group"

    def provision(self, context: dict) -> ProvisionResult:
        if self._client.resource_groups.check_existence(self._rg_name):
            return ProvisionResult(
                name=self.name, success=True,
                info={"rg_name": self._rg_name, "created": False},
            )

        self._client.resource_groups.create_or_update(
            self._rg_name,
            ResourceGroup(location=self._location, tags=self._tags),
        )
        return ProvisionResult(
            name=self.name, success=True,
            info={"rg_name": self._rg_name, "created": True},
        )

    def health_check(self):
        return NoopHealthCheck()
```

```python
# packages/python/agentstack-provider-azure/src/agentstack_provider_azure/nodes/log_analytics.py
"""Azure Log Analytics Workspace node."""

from azure.mgmt.loganalytics.models import Workspace, WorkspaceSku

from agentstack.provisioning.health import NoopHealthCheck
from agentstack.provisioning.node import Provisionable, ProvisionResult


class AzureLogAnalyticsNode(Provisionable):
    def __init__(self, log_client, rg_name: str, location: str, workspace_name: str):
        self._client = log_client
        self._rg_name = rg_name
        self._location = location
        self._workspace_name = workspace_name

    @property
    def name(self) -> str:
        return "log-analytics"

    @property
    def depends_on(self) -> list[str]:
        return ["resource-group"]

    def provision(self, context: dict) -> ProvisionResult:
        workspace = self._client.workspaces.begin_create_or_update(
            self._rg_name,
            self._workspace_name,
            Workspace(
                location=self._location,
                sku=WorkspaceSku(name="PerGB2018"),
            ),
        ).result()

        keys = self._client.shared_keys.get_shared_keys(
            self._rg_name, self._workspace_name,
        )

        return ProvisionResult(
            name=self.name, success=True,
            info={
                "customer_id": workspace.customer_id,
                "shared_key": keys.primary_shared_key,
                "workspace_name": self._workspace_name,
            },
        )

    def health_check(self):
        return NoopHealthCheck()
```

```python
# packages/python/agentstack-provider-azure/src/agentstack_provider_azure/nodes/acr.py
"""Azure Container Registry node."""

from azure.mgmt.containerregistry.models import (
    Registry,
    RegistryUpdateParameters,
    Sku as AcrSku,
)

from agentstack.provisioning.health import NoopHealthCheck
from agentstack.provisioning.node import Provisionable, ProvisionResult


class AzureACRNode(Provisionable):
    def __init__(self, acr_client, rg_name: str, location: str,
                 registry_name: str, existing: bool = False):
        self._client = acr_client
        self._rg_name = rg_name
        self._location = location
        self._registry_name = registry_name
        self._existing = existing

    @property
    def name(self) -> str:
        return "acr"

    @property
    def depends_on(self) -> list[str]:
        return ["resource-group"]

    def provision(self, context: dict) -> ProvisionResult:
        login_server = f"{self._registry_name}.azurecr.io"

        if self._existing:
            # User referenced an existing ACR — just get credentials
            creds = self._client.registries.list_credentials(
                self._rg_name, self._registry_name,
            )
            return ProvisionResult(
                name=self.name, success=True,
                info={
                    "login_server": login_server,
                    "username": creds.username,
                    "password": creds.passwords[0].value,
                    "registry_name": self._registry_name,
                },
            )

        # Create new ACR
        self._client.registries.begin_create(
            self._rg_name,
            self._registry_name,
            Registry(
                location=self._location,
                sku=AcrSku(name="Basic"),
                admin_user_enabled=True,
            ),
        ).result()

        # Get credentials
        creds = self._client.registries.list_credentials(
            self._rg_name, self._registry_name,
        )

        return ProvisionResult(
            name=self.name, success=True,
            info={
                "login_server": login_server,
                "username": creds.username,
                "password": creds.passwords[0].value,
                "registry_name": self._registry_name,
            },
        )

    def health_check(self):
        return NoopHealthCheck()
```

```python
# packages/python/agentstack-provider-azure/src/agentstack_provider_azure/nodes/aca_environment.py
"""Azure Container App Environment node."""

from azure.mgmt.appcontainers.models import (
    AppLogsConfiguration,
    LogAnalyticsConfiguration,
    ManagedEnvironment,
)

from agentstack.provisioning.health import NoopHealthCheck
from agentstack.provisioning.node import Provisionable, ProvisionResult


class AzureACAEnvironmentNode(Provisionable):
    def __init__(self, aca_client, rg_name: str, location: str,
                 env_name: str, existing: bool = False):
        self._client = aca_client
        self._rg_name = rg_name
        self._location = location
        self._env_name = env_name
        self._existing = existing

    @property
    def name(self) -> str:
        return "aca-environment"

    @property
    def depends_on(self) -> list[str]:
        return ["resource-group", "log-analytics"]

    def provision(self, context: dict) -> ProvisionResult:
        if self._existing:
            env = self._client.managed_environments.get(
                self._rg_name, self._env_name,
            )
            return ProvisionResult(
                name=self.name, success=True,
                info={
                    "environment_id": env.id,
                    "default_domain": env.default_domain,
                },
            )

        log_info = context.get("log-analytics", ProvisionResult(name="", success=False))

        env = self._client.managed_environments.begin_create_or_update(
            self._rg_name,
            self._env_name,
            ManagedEnvironment(
                location=self._location,
                app_logs_configuration=AppLogsConfiguration(
                    destination="log-analytics",
                    log_analytics_configuration=LogAnalyticsConfiguration(
                        customer_id=log_info.info.get("customer_id", ""),
                        shared_key=log_info.info.get("shared_key", ""),
                    ),
                ),
            ),
        ).result()

        return ProvisionResult(
            name=self.name, success=True,
            info={
                "environment_id": env.id,
                "default_domain": env.default_domain,
            },
        )

    def health_check(self):
        return NoopHealthCheck()
```

- [ ] **Step 3: Create stub for ContainerApp node**

```python
# packages/python/agentstack-provider-azure/src/agentstack_provider_azure/nodes/aca_app.py
"""Azure Container App node — stub, implemented in Task 3."""

from agentstack.provisioning.health import NoopHealthCheck
from agentstack.provisioning.node import Provisionable, ProvisionResult


class AzureContainerAppNode(Provisionable):
    def __init__(self, **kwargs):
        self._kwargs = kwargs

    @property
    def name(self) -> str:
        return "container-app"

    def provision(self, context: dict) -> ProvisionResult:
        raise NotImplementedError("Implemented in Task 3")

    def health_check(self):
        return NoopHealthCheck()
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest packages/python/agentstack-provider-azure/tests/ -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add packages/python/agentstack-provider-azure/src/agentstack_provider_azure/nodes/
git add packages/python/agentstack-provider-azure/tests/test_nodes.py
git commit -m "feat: add Azure infrastructure nodes (RG, LogAnalytics, ACR, ACA Environment)"
```

---

### Task 3: Implement AzureContainerAppNode

**Files:**
- Modify: `packages/python/agentstack-provider-azure/src/agentstack_provider_azure/nodes/aca_app.py`
- Modify: `packages/python/agentstack-provider-azure/tests/test_nodes.py`

- [ ] **Step 1: Write tests for ContainerApp node**

Add to `packages/python/agentstack-provider-azure/tests/test_nodes.py`:

```python
from agentstack.providers.base import DeployPlan, GeneratedCode
from agentstack.schema.agent import Agent
from agentstack.schema.model import Model
from agentstack.schema.provider import Provider


class TestAzureContainerAppNode:
    def test_provision(self):
        from agentstack_provider_azure.nodes.aca_app import AzureContainerAppNode

        mock_aca_client = MagicMock()
        mock_docker_client = MagicMock()
        mock_docker_client.images.build.return_value = (MagicMock(), [])

        app = MagicMock()
        app.configuration.ingress.fqdn = "mybot.eastus2.azurecontainerapps.io"
        mock_aca_client.container_apps.begin_create_or_update.return_value.result.return_value = app

        agent = Agent(
            name="test-bot",
            model=Model(name="claude", provider=Provider(name="anthropic", type="anthropic"),
                        model_name="claude-sonnet-4-20250514"),
        )
        code = GeneratedCode(
            files={"server.py": "# server", "requirements.txt": "fastapi\n"},
            entrypoint="server.py",
        )
        plan = DeployPlan(
            agent_name="test-bot", actions=["Create"],
            current_hash=None, target_hash="abc123", changes={},
        )

        node = AzureContainerAppNode(
            aca_client=mock_aca_client,
            docker_client=mock_docker_client,
            rg_name="rg",
            agent=agent,
            generated_code=code,
            plan=plan,
            platform_config={},
        )
        assert node.name == "container-app"
        assert "aca-environment" in node.depends_on
        assert "acr" in node.depends_on

        context = {
            "resource-group": ProvisionResult(name="resource-group", success=True, info={"rg_name": "rg"}),
            "acr": ProvisionResult(name="acr", success=True, info={
                "login_server": "myacr.azurecr.io",
                "username": "myacr",
                "password": "pass123",
                "registry_name": "myacr",
            }),
            "aca-environment": ProvisionResult(name="aca-environment", success=True, info={
                "environment_id": "/subscriptions/.../managedEnvironments/myenv",
            }),
        }

        result = node.provision(context=context)
        assert result.success
        assert "fqdn" in result.info
        mock_docker_client.images.build.assert_called_once()
```

- [ ] **Step 2: Implement AzureContainerAppNode**

```python
# packages/python/agentstack-provider-azure/src/agentstack_provider_azure/nodes/aca_app.py
"""Azure Container App node — builds image, pushes to ACR, creates Container App."""

import os
from pathlib import Path

from azure.mgmt.appcontainers.models import (
    Configuration,
    Container,
    ContainerApp,
    ContainerResources,
    Ingress,
    RegistryCredentials,
    Scale,
    Secret as AcaSecret,
    Template,
)

from agentstack.providers.base import DeployPlan, GeneratedCode
from agentstack.provisioning.health import HttpHealthCheck, NoopHealthCheck
from agentstack.provisioning.node import Provisionable, ProvisionResult
from agentstack.schema.agent import Agent


class AzureContainerAppNode(Provisionable):
    def __init__(self, aca_client, docker_client, rg_name: str,
                 agent: Agent, generated_code: GeneratedCode,
                 plan: DeployPlan, platform_config: dict):
        self._aca_client = aca_client
        self._docker_client = docker_client
        self._rg_name = rg_name
        self._agent = agent
        self._generated_code = generated_code
        self._plan = plan
        self._config = platform_config
        self._fqdn = None

    @property
    def name(self) -> str:
        return "container-app"

    @property
    def depends_on(self) -> list[str]:
        return ["aca-environment", "acr"]

    def provision(self, context: dict) -> ProvisionResult:
        acr_info = context["acr"].info
        env_info = context["aca-environment"].info

        login_server = acr_info["login_server"]
        image_tag = f"{login_server}/{self._agent.name}:latest"

        # 1. Build Docker image locally
        build_dir = Path(".agentstack") / self._agent.name
        build_dir.mkdir(parents=True, exist_ok=True)
        for filename, content in self._generated_code.files.items():
            file_path = build_dir / filename
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content)

        # Dockerfile
        mcp_installs = ""
        needs_node = False
        if self._agent.mcp_servers:
            install_cmds = []
            for mcp in self._agent.mcp_servers:
                if mcp.install:
                    install_cmds.append(f"RUN {mcp.install}")
                for field in (mcp.install or "", mcp.command or ""):
                    if "npm" in field or "npx" in field:
                        needs_node = True
            if install_cmds:
                mcp_installs = "\n".join(install_cmds) + "\n"

        node_install = ""
        if needs_node:
            node_install = (
                "RUN apt-get update && apt-get install -y nodejs npm "
                "&& rm -rf /var/lib/apt/lists/*\n"
            )

        dockerfile = (
            "FROM python:3.11-slim\n"
            "WORKDIR /app\n"
            f"{node_install}"
            f"{mcp_installs}"
            "COPY requirements.txt .\n"
            "RUN pip install --no-cache-dir -r requirements.txt\n"
            "COPY . .\n"
            f'CMD ["python", "{self._generated_code.entrypoint}"]\n'
        )
        (build_dir / "Dockerfile").write_text(dockerfile)

        self._docker_client.images.build(path=str(build_dir), tag=image_tag)

        # 2. Push to ACR
        self._docker_client.login(
            registry=login_server,
            username=acr_info["username"],
            password=acr_info["password"],
        )
        self._docker_client.images.push(image_tag)

        # 3. Collect secrets and env vars
        secrets = []
        env_vars = []
        for secret in self._agent.secrets:
            value = os.environ.get(secret.name, "")
            secret_name = secret.name.lower().replace("_", "-")
            secrets.append(AcaSecret(name=secret_name, value=value))
            env_vars.append({"name": secret.name, "secretRef": secret_name})

        # Add registry password as a secret
        secrets.append(AcaSecret(name="acr-password", value=acr_info["password"]))

        # 4. Create Container App
        cpu = self._config.get("cpu", 0.5)
        memory = self._config.get("memory", "1Gi")
        min_replicas = self._config.get("min_replicas", 0)
        max_replicas = self._config.get("max_replicas", 5)
        ingress_type = self._config.get("ingress", "external")

        app = self._aca_client.container_apps.begin_create_or_update(
            self._rg_name,
            self._agent.name,
            ContainerApp(
                location=self._config.get("location", "eastus2"),
                managed_environment_id=env_info["environment_id"],
                configuration=Configuration(
                    ingress=Ingress(
                        external=(ingress_type == "external"),
                        target_port=8000,
                    ),
                    secrets=secrets,
                    registries=[
                        RegistryCredentials(
                            server=login_server,
                            username=acr_info["username"],
                            password_secret_ref="acr-password",
                        ),
                    ],
                ),
                template=Template(
                    containers=[
                        Container(
                            name=self._agent.name,
                            image=image_tag,
                            resources=ContainerResources(
                                cpu=cpu,
                                memory=memory,
                            ),
                            env=env_vars,
                        ),
                    ],
                    scale=Scale(
                        min_replicas=min_replicas,
                        max_replicas=max_replicas,
                    ),
                ),
            ),
        ).result()

        self._fqdn = app.configuration.ingress.fqdn

        return ProvisionResult(
            name=self.name, success=True,
            info={
                "fqdn": self._fqdn,
                "url": f"https://{self._fqdn}",
                "app_name": self._agent.name,
            },
        )

    def health_check(self):
        if self._fqdn:
            return HttpHealthCheck(url=f"https://{self._fqdn}/health")
        return NoopHealthCheck()

    def destroy(self):
        try:
            self._aca_client.container_apps.begin_delete(
                self._rg_name, self._agent.name,
            ).result()
        except Exception:
            pass
```

- [ ] **Step 3: Run tests**

Run: `uv run pytest packages/python/agentstack-provider-azure/tests/ -v`
Expected: All tests PASS

- [ ] **Step 4: Commit**

```bash
git add packages/python/agentstack-provider-azure/src/agentstack_provider_azure/nodes/aca_app.py
git add packages/python/agentstack-provider-azure/tests/test_nodes.py
git commit -m "feat: implement AzureContainerAppNode — builds, pushes, and deploys to ACA"
```

---

### Task 4: Implement AzureProvider

**Files:**
- Create: `packages/python/agentstack-provider-azure/src/agentstack_provider_azure/provider.py`
- Create: `packages/python/agentstack-provider-azure/tests/test_provider.py`
- Modify: `packages/python/agentstack-provider-azure/src/agentstack_provider_azure/__init__.py`

- [ ] **Step 1: Write provider tests**

```python
# packages/python/agentstack-provider-azure/tests/test_provider.py
from unittest.mock import MagicMock, patch

import pytest

from agentstack.providers.base import DeployPlan, GeneratedCode
from agentstack.provisioning.node import ProvisionResult
from agentstack.schema.agent import Agent
from agentstack.schema.common import ChannelType
from agentstack.schema.channel import Channel
from agentstack.schema.model import Model
from agentstack.schema.platform import Platform
from agentstack.schema.provider import Provider
from agentstack.schema.secret import Secret


@pytest.fixture()
def azure_agent():
    azure = Provider(name="azure", type="azure", config={"location": "eastus2"})
    return Agent(
        name="test-bot",
        model=Model(
            name="claude",
            provider=Provider(name="anthropic", type="anthropic"),
            model_name="claude-sonnet-4-20250514",
        ),
        platform=Platform(name="aca", type="container-apps", provider=azure),
        channels=[Channel(name="api", type=ChannelType.API)],
        secrets=[Secret(name="ANTHROPIC_API_KEY")],
    )


@pytest.fixture()
def sample_code():
    return GeneratedCode(
        files={"server.py": "# server", "requirements.txt": "fastapi\n"},
        entrypoint="server.py",
    )


class TestAzureProvider:
    @patch("agentstack_provider_azure.provider.ProvisionGraph")
    @patch("agentstack_provider_azure.provider.get_credential")
    @patch("agentstack_provider_azure.provider.get_subscription_id")
    def test_apply_builds_graph(self, mock_sub, mock_cred, mock_graph_cls, azure_agent, sample_code):
        from agentstack_provider_azure.provider import AzureProvider

        mock_sub.return_value = "test-sub"
        mock_cred.return_value = MagicMock()

        mock_graph = MagicMock()
        mock_graph.execute.return_value = {
            "container-app": ProvisionResult(
                name="container-app", success=True,
                info={"url": "https://test-bot.eastus2.azurecontainerapps.io", "fqdn": "test-bot.eastus2.azurecontainerapps.io"},
            ),
        }
        mock_graph_cls.return_value = mock_graph

        provider = AzureProvider()
        provider.set_agent(azure_agent)
        provider.set_generated_code(sample_code)

        plan = DeployPlan(
            agent_name="test-bot", actions=["Create"],
            current_hash=None, target_hash="abc123", changes={},
        )
        result = provider.apply(plan)

        assert result.success
        assert "azurecontainerapps.io" in result.message
        # Should have added 5 nodes: RG, LogAnalytics, ACR, ACAEnv, ContainerApp
        assert mock_graph.add.call_count == 5
        mock_graph.execute.assert_called_once()
```

- [ ] **Step 2: Implement AzureProvider**

```python
# packages/python/agentstack-provider-azure/src/agentstack_provider_azure/provider.py
"""Azure Container Apps platform provider."""

import hashlib

import docker
import docker.errors

from agentstack.hash import hash_agent
from agentstack.provisioning import ProvisionGraph
from agentstack.providers.base import (
    AgentStatus,
    DeployPlan,
    DeployResult,
    GeneratedCode,
    PlatformProvider,
)
from agentstack.schema.agent import Agent

from agentstack_provider_azure.auth import get_credential, get_location, get_subscription_id
from agentstack_provider_azure.nodes import (
    AzureACRNode,
    AzureACAEnvironmentNode,
    AzureContainerAppNode,
    AzureLogAnalyticsNode,
    AzureResourceGroupNode,
)


class AzureProvider(PlatformProvider):
    """Deploys and manages agents on Azure Container Apps."""

    def __init__(self):
        self._generated_code: GeneratedCode | None = None
        self._agent: Agent | None = None

    def set_generated_code(self, code: GeneratedCode) -> None:
        self._generated_code = code

    def set_agent(self, agent: Agent) -> None:
        self._agent = agent

    def _get_config(self) -> dict:
        """Get merged config from provider and platform."""
        config = {}
        if self._agent and self._agent.platform:
            config.update(self._agent.platform.provider.config)
            config.update(self._agent.platform.config)
        return config

    def _make_rg_name(self, agent_name: str, config: dict) -> str:
        if config.get("resource_group"):
            return config["resource_group"]
        return f"agentstack-{agent_name}-rg"

    def _make_acr_name(self, agent_name: str, config: dict) -> str:
        if config.get("registry"):
            # Extract registry name from "myacr.azurecr.io"
            return config["registry"].replace(".azurecr.io", "")
        # ACR names must be globally unique, alphanumeric only
        suffix = hashlib.md5(agent_name.encode()).hexdigest()[:8]
        return f"agentstack{suffix}"

    def _make_env_name(self, agent_name: str, config: dict) -> str:
        if config.get("environment"):
            return config["environment"]
        return f"agentstack-{agent_name}-env"

    def _make_tags(self, agent_name: str, config: dict) -> dict:
        tags = {
            "agentstack:managed": "true",
            "agentstack:agent": agent_name,
        }
        tags.update(config.get("tags", {}))
        return tags

    def get_hash(self, agent_name: str) -> str | None:
        # Phase 2a: no remote hash storage yet
        return None

    def plan(self, agent: Agent, current_hash: str | None) -> DeployPlan:
        tree = hash_agent(agent)
        target_hash = tree.root
        # Phase 2a: always create (no remote hash comparison yet)
        return DeployPlan(
            agent_name=agent.name,
            actions=["Deploy to Azure Container Apps"],
            current_hash=current_hash,
            target_hash=target_hash,
            changes={"all": (current_hash, target_hash)},
        )

    def apply(self, plan: DeployPlan) -> DeployResult:
        if not self._generated_code:
            return DeployResult(
                agent_name=plan.agent_name,
                success=False,
                hash=plan.target_hash,
                message="No generated code set. Call set_generated_code() first.",
            )

        try:
            config = self._get_config()
            credential = get_credential()
            subscription_id = get_subscription_id(config)
            location = get_location(config)
            rg_name = self._make_rg_name(plan.agent_name, config)
            acr_name = self._make_acr_name(plan.agent_name, config)
            env_name = self._make_env_name(plan.agent_name, config)
            tags = self._make_tags(plan.agent_name, config)

            # Create Azure management clients
            from azure.mgmt.appcontainers import ContainerAppsAPIClient
            from azure.mgmt.containerregistry import ContainerRegistryManagementClient
            from azure.mgmt.loganalytics import LogAnalyticsManagementClient
            from azure.mgmt.resource import ResourceManagementClient

            resource_client = ResourceManagementClient(credential, subscription_id)
            log_client = LogAnalyticsManagementClient(credential, subscription_id)
            acr_client = ContainerRegistryManagementClient(credential, subscription_id)
            aca_client = ContainerAppsAPIClient(credential, subscription_id)

            # Docker client for local build
            try:
                docker_client = docker.from_env()
            except docker.errors.DockerException:
                from pathlib import Path
                desktop_socket = Path.home() / ".docker" / "run" / "docker.sock"
                if desktop_socket.exists():
                    docker_client = docker.DockerClient(base_url=f"unix://{desktop_socket}")
                else:
                    raise

            # Build provision graph
            graph = ProvisionGraph()

            graph.add(AzureResourceGroupNode(
                resource_client=resource_client,
                rg_name=rg_name,
                location=location,
                tags=tags,
            ))

            graph.add(AzureLogAnalyticsNode(
                log_client=log_client,
                rg_name=rg_name,
                location=location,
                workspace_name=f"agentstack-{plan.agent_name}-logs",
            ))

            graph.add(AzureACRNode(
                acr_client=acr_client,
                rg_name=rg_name,
                location=location,
                registry_name=acr_name,
                existing=bool(config.get("registry")),
            ))

            graph.add(AzureACAEnvironmentNode(
                aca_client=aca_client,
                rg_name=rg_name,
                location=location,
                env_name=env_name,
                existing=bool(config.get("environment")),
            ))

            graph.add(AzureContainerAppNode(
                aca_client=aca_client,
                docker_client=docker_client,
                rg_name=rg_name,
                agent=self._agent,
                generated_code=self._generated_code,
                plan=plan,
                platform_config={**config, "location": location},
            ))

            results = graph.execute()

            app_result = results.get("container-app")
            if app_result and app_result.success:
                url = app_result.info.get("url", "?")
                return DeployResult(
                    agent_name=plan.agent_name,
                    success=True,
                    hash=plan.target_hash,
                    message=f"Deployed {plan.agent_name} at {url}",
                )

            return DeployResult(
                agent_name=plan.agent_name,
                success=False,
                hash=plan.target_hash,
                message="Container app not found in provision results",
            )

        except Exception as e:
            return DeployResult(
                agent_name=plan.agent_name,
                success=False,
                hash=plan.target_hash,
                message=f"Azure deployment failed: {e}",
            )

    def destroy(self, agent_name: str, include_resources: bool = False) -> None:
        # Phase 2a: tag-based destroy not yet implemented
        config = self._get_config()
        credential = get_credential()
        subscription_id = get_subscription_id(config)
        rg_name = self._make_rg_name(agent_name, config)

        from azure.mgmt.appcontainers import ContainerAppsAPIClient
        aca_client = ContainerAppsAPIClient(credential, subscription_id)

        try:
            aca_client.container_apps.begin_delete(rg_name, agent_name).result()
        except Exception:
            pass

    def status(self, agent_name: str) -> AgentStatus:
        # Phase 2a: basic status check
        config = self._get_config()
        credential = get_credential()
        subscription_id = get_subscription_id(config)
        rg_name = self._make_rg_name(agent_name, config)

        from azure.mgmt.appcontainers import ContainerAppsAPIClient
        aca_client = ContainerAppsAPIClient(credential, subscription_id)

        try:
            app = aca_client.container_apps.get(rg_name, agent_name)
            fqdn = app.configuration.ingress.fqdn if app.configuration and app.configuration.ingress else None
            return AgentStatus(
                agent_name=agent_name,
                running=app.provisioning_state == "Succeeded",
                hash=None,
                info={
                    "provider": "azure",
                    "fqdn": fqdn,
                    "url": f"https://{fqdn}" if fqdn else None,
                    "provisioning_state": app.provisioning_state,
                },
            )
        except Exception:
            return AgentStatus(agent_name=agent_name, running=False, hash=None)
```

- [ ] **Step 3: Update __init__.py**

```python
# packages/python/agentstack-provider-azure/src/agentstack_provider_azure/__init__.py
"""AgentStack Azure Container Apps provider."""

__version__ = "0.1.0"

from agentstack_provider_azure.provider import AzureProvider

__all__ = ["AzureProvider", "__version__"]
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest packages/python/agentstack-provider-azure/tests/ -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add packages/python/agentstack-provider-azure/src/agentstack_provider_azure/provider.py
git add packages/python/agentstack-provider-azure/src/agentstack_provider_azure/__init__.py
git add packages/python/agentstack-provider-azure/tests/test_provider.py
git commit -m "feat: implement AzureProvider with ProvisionGraph"
```

---

### Task 5: Add CLI provider factory

**Files:**
- Create: `packages/python/agentstack-cli/src/agentstack_cli/provider_factory.py`
- Modify: `packages/python/agentstack-cli/src/agentstack_cli/commands/plan.py`
- Modify: `packages/python/agentstack-cli/src/agentstack_cli/commands/apply.py`
- Modify: `packages/python/agentstack-cli/src/agentstack_cli/commands/destroy.py`
- Modify: `packages/python/agentstack-cli/src/agentstack_cli/commands/status.py`
- Modify: `packages/python/agentstack-cli/src/agentstack_cli/commands/logs.py`
- Create: `packages/python/agentstack-cli/tests/test_provider_factory.py`

- [ ] **Step 1: Write tests for provider factory**

```python
# packages/python/agentstack-cli/tests/test_provider_factory.py
from unittest.mock import MagicMock

import pytest

from agentstack.schema.agent import Agent
from agentstack.schema.common import ChannelType
from agentstack.schema.channel import Channel
from agentstack.schema.model import Model
from agentstack.schema.platform import Platform
from agentstack.schema.provider import Provider

from agentstack_cli.provider_factory import get_provider


@pytest.fixture()
def model():
    return Model(
        name="claude",
        provider=Provider(name="anthropic", type="anthropic"),
        model_name="claude-sonnet-4-20250514",
    )


class TestProviderFactory:
    def test_docker_provider_default(self, model):
        agent = Agent(name="bot", model=model)
        provider = get_provider(agent)
        from agentstack_provider_docker import DockerProvider
        assert isinstance(provider, DockerProvider)

    def test_docker_provider_explicit(self, model):
        docker = Provider(name="docker", type="docker")
        agent = Agent(
            name="bot", model=model,
            platform=Platform(name="docker", type="docker", provider=docker),
        )
        provider = get_provider(agent)
        from agentstack_provider_docker import DockerProvider
        assert isinstance(provider, DockerProvider)

    def test_azure_provider(self, model):
        azure = Provider(name="azure", type="azure")
        agent = Agent(
            name="bot", model=model,
            platform=Platform(name="aca", type="container-apps", provider=azure),
        )
        provider = get_provider(agent)
        from agentstack_provider_azure import AzureProvider
        assert isinstance(provider, AzureProvider)

    def test_unknown_provider_raises(self, model):
        unknown = Provider(name="unknown", type="gcp")
        agent = Agent(
            name="bot", model=model,
            platform=Platform(name="cr", type="cloud-run", provider=unknown),
        )
        with pytest.raises(ValueError, match="Unknown provider type"):
            get_provider(agent)
```

- [ ] **Step 2: Implement provider factory**

```python
# packages/python/agentstack-cli/src/agentstack_cli/provider_factory.py
"""Provider factory — selects the right platform provider based on agent definition."""

from agentstack.providers.base import PlatformProvider
from agentstack.schema.agent import Agent


def get_provider(agent: Agent) -> PlatformProvider:
    """Get the appropriate platform provider for the agent."""
    if agent.platform is None or agent.platform.provider.type == "docker":
        from agentstack_provider_docker import DockerProvider
        return DockerProvider()

    if agent.platform.provider.type == "azure":
        from agentstack_provider_azure import AzureProvider
        return AzureProvider()

    raise ValueError(
        f"Unknown provider type: '{agent.platform.provider.type}'. "
        f"Supported: docker, azure"
    )
```

- [ ] **Step 3: Update CLI commands to use factory**

Replace `from agentstack_provider_docker import DockerProvider` and `provider = DockerProvider()` in each command with:

**plan.py** — replace lines 6-7 and line 33-34:
```python
# Remove: from agentstack_provider_docker import DockerProvider
# Add: from agentstack_cli.provider_factory import get_provider
# Replace: provider = DockerProvider() → provider = get_provider(agent)
```

**apply.py** — replace line 7 and line 34:
```python
# Remove: from agentstack_provider_docker import DockerProvider
# Add: from agentstack_cli.provider_factory import get_provider
# Replace: provider = DockerProvider() → provider = get_provider(agent)
```

**destroy.py** — replace line 6 and line 27:
```python
# Remove: from agentstack_provider_docker import DockerProvider
# Add: from agentstack_cli.provider_factory import get_provider
# Replace: provider = DockerProvider() → provider = get_provider(agent)
# Note: destroy needs the agent loaded to determine provider, so load it even for --name
```

**status.py** — replace line 6 and line 19:
```python
# Remove: from agentstack_provider_docker import DockerProvider
# Add: from agentstack_cli.provider_factory import get_provider
# Replace: provider = DockerProvider() → provider = get_provider(agent)
# Note: status needs the agent to pick provider
```

**logs.py** — replace line 6 and line 21:
```python
# Remove: from agentstack_provider_docker import DockerProvider
# Add: from agentstack_cli.provider_factory import get_provider
# Note: logs uses provider._get_container() which is Docker-specific.
# For now, keep Docker-specific for logs. The Azure provider will need its own logs impl.
# Replace: provider = DockerProvider() → provider = get_provider(agent) where agent is loaded
```

- [ ] **Step 4: Run all CLI tests**

Run: `uv run pytest packages/python/agentstack-cli/tests/ -v`
Expected: All tests PASS

- [ ] **Step 5: Run full test suite**

Run: `uv run pytest packages/python/ -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add packages/python/agentstack-cli/src/agentstack_cli/provider_factory.py
git add packages/python/agentstack-cli/src/agentstack_cli/commands/
git add packages/python/agentstack-cli/tests/test_provider_factory.py
git commit -m "feat: add provider factory — CLI selects Docker vs Azure based on agent definition"
```

---

### Task 6: Create Azure example and verify end-to-end

**Files:**
- Create: `examples/azure-minimal/agentstack.yaml`

- [ ] **Step 1: Create example YAML**

```yaml
# examples/azure-minimal/agentstack.yaml
name: azure-bot
instructions: |
  You are a minimal agent deployed to Azure Container Apps.
  Just chat and be helpful.
model:
  name: minimax
  provider:
    name: anthropic
    type: anthropic
  model_name: MiniMax-M2.7
  parameters:
    temperature: 0.7
    anthropic_api_url: https://api.minimax.io/anthropic
platform:
  name: aca
  type: container-apps
  provider:
    name: azure
    type: azure
    config:
      location: eastus2
channels:
  - name: api
    type: api
secrets:
  - name: ANTHROPIC_API_KEY
```

- [ ] **Step 2: Verify YAML loads and selects Azure provider**

Run:
```bash
uv run python -c "
from agentstack import load_agent
from agentstack_cli.provider_factory import get_provider
a = load_agent('examples/azure-minimal/agentstack.yaml')
p = get_provider(a)
print(f'{a.name}: provider={type(p).__name__}, platform={a.platform.type}')
"
```

Expected: `azure-bot: provider=AzureProvider, platform=container-apps`

- [ ] **Step 3: Test plan command (dry run)**

Run:
```bash
cd examples/azure-minimal
ANTHROPIC_API_KEY="***REMOVED***" uv run agentstack plan
```

Expected: Shows plan output with "Deploy to Azure Container Apps" action. May fail on Azure auth if not logged in — that's OK for now, the important thing is it selects the right provider.

- [ ] **Step 4: Commit**

```bash
cd ~/Developer/work/AgentsStack
git add examples/azure-minimal/
git commit -m "feat: add azure-minimal example for Azure Container Apps deployment"
```

- [ ] **Step 5: Run full test suite one final time**

Run: `uv run pytest packages/python/ -v`
Expected: All tests PASS
