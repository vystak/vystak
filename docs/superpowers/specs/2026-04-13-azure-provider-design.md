# Azure Container Apps Provider — Design Spec

## Overview

Build `agentstack-provider-azure` — a platform provider that deploys agents to Azure Container Apps. Given an agent definition with `provider: {type: azure}` and `platform: {type: container-apps}`, the provider provisions all necessary Azure infrastructure (Resource Group, ACR, Log Analytics, ACA Environment, Container App, Postgres, VNet, Key Vault), deploys the agent, and supports the full CLI lifecycle (`plan`, `apply`, `destroy`, `status`, `logs`).

The provider uses the core `ProvisionGraph` for dependency-ordered provisioning with health checks, and integrates with the existing schema types (`Service`, `Platform`, `Provider`).

## Authentication

**Strategy:** Try Azure CLI first, fall back to service principal.

1. Check if `az` CLI is authenticated (`az account show`)
2. If not, check for service principal env vars:
   - `AZURE_CLIENT_ID`
   - `AZURE_CLIENT_SECRET`
   - `AZURE_TENANT_ID`
   - `AZURE_SUBSCRIPTION_ID`
3. If neither, fail with a clear error message suggesting `az login`

Uses the `azure-identity` SDK's `DefaultAzureCredential` which handles both paths automatically.

## Azure Resources

The provider provisions 7 resource types, all tagged with `agentstack:managed=true` and `agentstack:agent=<name>` for tag-based cleanup.

### Resource Dependency Graph

```
Resource Group (root)
├── Log Analytics Workspace
│   └── Container App Environment
│       └── Container App (the agent)
├── Container Registry (ACR)
│   └── Container App (image pull)
├── Virtual Network
│   ├── Container App Environment (subnet)
│   └── PostgreSQL Flexible Server (subnet)
├── PostgreSQL Flexible Server
│   └── Container App (connection string)
└── Key Vault
    └── Container App (secrets)
```

### 1. Resource Group

- Created per workspace/agent if not specified
- Default name: `agentstack-{agent-name}-rg`
- User can specify an existing RG via `provider.config.resource_group`
- All other resources go in this RG

### 2. Log Analytics Workspace

- Required by ACA Environment for container logs
- SKU: PerGB2018
- Enables `agentstack logs` to work on Azure

### 3. Container App Environment

- One per workspace — all agents in the workspace share it
- Agents discover each other via internal DNS
- Connected to VNet subnet for private networking
- User can reference an existing environment via `platform.config.environment`

### 4. Azure Container Registry (ACR)

- Stores the built agent images
- SKU: Basic (cheapest)
- Admin user enabled for ACA image pull
- User can reference an existing ACR via `platform.config.registry`

### 5. Container App

- The agent itself
- Image pulled from ACR
- Ingress: external (default) or internal
- Scaling: min_replicas (default 0), max_replicas (default 5)
- CPU/memory: defaults 0.5 cpu, 1Gi
- Secrets injected from Key Vault or env vars
- Environment variables: SESSION_STORE_URL, secrets

### 6. Azure Database for PostgreSQL Flexible Server

- Provisioned when `sessions` or `memory` uses postgres with azure provider
- SKU: Standard_B1ms (burstable, cheapest)
- Version: 16
- Storage: 32GB default
- Connected to VNet for private access
- User can bring-your-own via `connection_string_env`

### 7. Virtual Network

- Private networking between ACA Environment and Postgres
- Two subnets: one for ACA, one for Postgres
- CIDR: 10.0.0.0/16 (ACA: 10.0.0.0/23, Postgres: 10.0.2.0/24)

### 8. Key Vault

- Stores secrets (ANTHROPIC_API_KEY, database passwords)
- Container App references secrets from Key Vault
- Agent env vars populated from Key Vault secrets

## Agent Definition Examples

### Minimal Azure deployment

```python
azure = ast.Provider(name="azure", type="azure", config={"location": "eastus2"})
anthropic = ast.Provider(name="anthropic", type="anthropic")

agent = ast.Agent(
    name="my-bot",
    model=ast.Model(name="claude", provider=anthropic, model_name="claude-sonnet-4-20250514"),
    platform=ast.Platform(name="aca", type="container-apps", provider=azure),
    channels=[ast.Channel(name="api", type=ast.ChannelType.API)],
    secrets=[ast.Secret(name="ANTHROPIC_API_KEY")],
)
```

### With postgres sessions + custom config

```python
azure = ast.Provider(
    name="azure", type="azure",
    config={
        "location": "eastus2",
        "resource_group": "my-agents-rg",
        "tags": {"team": "platform", "env": "prod"},
    },
)

agent = ast.Agent(
    name="my-bot",
    model=model,
    platform=ast.Platform(
        name="aca", type="container-apps", provider=azure,
        config={
            "cpu": 1.0,
            "memory": "2Gi",
            "min_replicas": 1,
            "max_replicas": 10,
            "ingress": "external",
        },
    ),
    sessions=ast.Postgres(provider=azure, config={"sku": "Standard_B1ms"}),
    secrets=[ast.Secret(name="ANTHROPIC_API_KEY")],
)
```

### Bring-your-own Postgres

```python
agent = ast.Agent(
    name="my-bot",
    model=model,
    platform=ast.Platform(name="aca", type="container-apps", provider=azure),
    sessions=ast.Postgres(connection_string_env="DATABASE_URL"),
    secrets=[ast.Secret(name="ANTHROPIC_API_KEY"), ast.Secret(name="DATABASE_URL")],
)
```

### YAML equivalent

```yaml
name: my-bot
model:
  name: claude
  provider: { name: anthropic, type: anthropic }
  model_name: claude-sonnet-4-20250514
platform:
  name: aca
  type: container-apps
  provider:
    name: azure
    type: azure
    config:
      location: eastus2
sessions:
  type: postgres
  provider:
    name: azure
    type: azure
channels:
  - name: api
    type: api
secrets:
  - name: ANTHROPIC_API_KEY
```

## Package Structure

```
packages/python/agentstack-provider-azure/
    pyproject.toml
    src/agentstack_provider_azure/
        __init__.py              # exports AzureProvider
        provider.py              # AzureProvider (PlatformProvider impl)
        auth.py                  # Azure authentication (DefaultAzureCredential)
        nodes/
            __init__.py
            resource_group.py    # AzureResourceGroupNode
            log_analytics.py     # AzureLogAnalyticsNode
            vnet.py              # AzureVNetNode
            acr.py               # AzureACRNode
            aca_environment.py   # AzureACAEnvironmentNode
            aca_app.py           # AzureContainerAppNode
            postgres.py          # AzurePostgresNode
            keyvault.py          # AzureKeyVaultNode
    tests/
        test_auth.py
        test_provider.py
        test_nodes.py
```

## Provision Graph for Azure

The provider builds this graph in `apply()`:

```python
graph = ProvisionGraph()

# Infrastructure layer
graph.add(AzureResourceGroupNode(cred, config))
graph.add(AzureLogAnalyticsNode(cred, config))
graph.add(AzureVNetNode(cred, config))
graph.add(AzureACRNode(cred, config))
graph.add(AzureKeyVaultNode(cred, config))

# Platform layer
graph.add(AzureACAEnvironmentNode(cred, config))

# Service layer (if managed postgres)
if agent.sessions and agent.sessions.is_managed:
    graph.add(AzurePostgresNode(cred, config, agent.sessions))
if agent.memory and agent.memory.is_managed:
    graph.add(AzurePostgresNode(cred, config, agent.memory))

# Application layer
graph.add(AzureContainerAppNode(cred, config, agent, code, plan))
```

Implicit dependencies (wired by each node's `depends_on`):
- Log Analytics → Resource Group
- VNet → Resource Group
- ACR → Resource Group
- Key Vault → Resource Group
- ACA Environment → Resource Group, Log Analytics, VNet
- Postgres → Resource Group, VNet
- Container App → ACA Environment, ACR, Key Vault, Postgres (if managed)

## Node Implementation Details

### AzureResourceGroupNode

```python
class AzureResourceGroupNode(Provisionable):
    name = "resource-group"
    depends_on = []  # root

    def provision(self, context):
        # Check if RG exists (user-specified or default)
        # If not, create it with tags
        # Return ProvisionResult with info={"rg_name": ...}

    def health_check(self):
        return NoopHealthCheck()  # RG creation is synchronous

    def destroy(self):
        # Don't delete RG — tag-based cleanup happens per-resource
        pass
```

### AzureACRNode

```python
class AzureACRNode(Provisionable):
    name = "acr"
    depends_on = ["resource-group"]

    def provision(self, context):
        # If user specified platform.config.registry, use existing
        # Otherwise create: agentstack{random}acr (must be globally unique)
        # Enable admin user
        # Return ProvisionResult with info={"login_server": ..., "username": ..., "password": ...}

    def health_check(self):
        return NoopHealthCheck()
```

### AzureACAEnvironmentNode

```python
class AzureACAEnvironmentNode(Provisionable):
    name = "aca-environment"
    depends_on = ["resource-group", "log-analytics", "vnet"]

    def provision(self, context):
        # If user specified platform.config.environment, use existing
        # Otherwise create with VNet integration and log analytics
        # Return ProvisionResult with info={"environment_id": ...}

    def health_check(self):
        return NoopHealthCheck()  # ARM waits for completion
```

### AzurePostgresNode

```python
class AzurePostgresNode(Provisionable):
    def __init__(self, cred, config, service):
        self._service = service

    @property
    def name(self):
        return self._service.name  # "sessions" or "memory"

    @property
    def depends_on(self):
        return ["resource-group", "vnet"]

    def provision(self, context):
        # Create Flexible Server with private access via VNet
        # Create database "agentstack"
        # Create firewall rules
        # Return ProvisionResult with info={"connection_string": ...}

    def health_check(self):
        # TCP check on postgres port (private IP)
        return TcpHealthCheck(host=self._private_ip, port=5432)
```

### AzureContainerAppNode

```python
class AzureContainerAppNode(Provisionable):
    name = "container-app"

    @property
    def depends_on(self):
        deps = ["aca-environment", "acr", "keyvault"]
        if self._agent.sessions and self._agent.sessions.is_managed:
            deps.append(self._agent.sessions.name)
        if self._agent.memory and self._agent.memory.is_managed:
            deps.append(self._agent.memory.name)
        return deps

    def provision(self, context):
        # 1. Build Docker image locally
        # 2. Push to ACR (from context)
        # 3. Store secrets in Key Vault (from context)
        # 4. Create/update Container App
        #    - Image from ACR
        #    - Env vars from Key Vault refs + connection strings from context
        #    - Ingress config from platform.config
        #    - Scaling config from platform.config
        # 5. Get FQDN
        # Return ProvisionResult with info={"url": f"https://{fqdn}", "fqdn": ...}

    def health_check(self):
        return HttpHealthCheck(url=f"https://{self._fqdn}/health")
```

## CLI Integration

The CLI currently hardcodes `DockerProvider`. It needs to select the provider based on `agent.platform.provider.type`:

```python
# In agentstack_cli/loader.py or a new provider_factory.py
def get_provider(agent: Agent) -> PlatformProvider:
    if agent.platform is None or agent.platform.provider.type == "docker":
        from agentstack_provider_docker import DockerProvider
        return DockerProvider()
    elif agent.platform.provider.type == "azure":
        from agentstack_provider_azure import AzureProvider
        return AzureProvider()
    else:
        raise ValueError(f"Unknown provider type: {agent.platform.provider.type}")
```

Update `plan.py`, `apply.py`, `destroy.py`, `status.py`, `logs.py` to use `get_provider(agent)` instead of `DockerProvider()`.

## Tag-Based Resource Management

All Azure resources get these tags:
```python
tags = {
    "agentstack:managed": "true",
    "agentstack:agent": agent.name,
    "agentstack:workspace": workspace_name,  # if applicable
    **user_tags,  # from provider.config.tags
}
```

`destroy` finds all resources with `agentstack:agent={name}` tag and deletes them. This is safer than deleting the entire Resource Group since the RG may contain non-AgentStack resources.

## `agentstack logs` on Azure

Uses Azure Monitor / Log Analytics to query container logs:
```python
def logs(self, agent_name: str) -> str:
    # Query Log Analytics workspace for container logs
    # Filter by container app name
    # Return recent log lines
```

## `agentstack status` on Azure

Queries Container App status:
```python
def status(self, agent_name: str) -> AgentStatus:
    # Get Container App details
    # Check provisioning state and running status
    # Return AgentStatus with info including FQDN, replicas, etc.
```

## Dependencies (pyproject.toml)

```toml
[project]
name = "agentstack-provider-azure"
dependencies = [
    "agentstack",
    "azure-identity>=1.15",
    "azure-mgmt-resource>=23.0",          # Resource Groups
    "azure-mgmt-containerregistry>=10.0",  # ACR
    "azure-mgmt-appcontainers>=3.0",       # ACA
    "azure-mgmt-rdbms>=12.0",             # PostgreSQL Flexible Server
    "azure-mgmt-network>=25.0",            # VNet
    "azure-mgmt-keyvault>=10.0",           # Key Vault
    "azure-mgmt-loganalytics>=13.0",       # Log Analytics
    "azure-keyvault-secrets>=4.8",         # Key Vault secrets client
    "docker>=7.0",                          # Local image build before push
]
```

## Phased Implementation

This is a large provider. Break into sub-phases:

### Phase 2a: Core + minimal deploy (no postgres, no VNet)
- AzureProvider skeleton
- Auth (DefaultAzureCredential)
- Resource Group, ACR, Log Analytics, ACA Environment, Container App
- CLI provider selection
- Deploy a minimal agent to ACA

### Phase 2b: Postgres + VNet
- VNet with subnets
- Azure Database for PostgreSQL
- Key Vault for secrets
- Private networking between ACA and Postgres
- Deploy sessions-postgres example to Azure

### Phase 2c: Full lifecycle
- `destroy` with tag-based cleanup
- `status` with Container App query
- `logs` with Log Analytics query
- `plan` with hash comparison

## Out of Scope

- Multi-region deployment
- Custom domains / SSL certificates
- Azure Functions as an alternative to ACA
- Managed identity (using service principal / CLI auth for now)
- CI/CD integration
- Cost estimation in `plan` output
