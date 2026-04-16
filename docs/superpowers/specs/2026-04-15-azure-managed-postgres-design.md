# Azure Managed Postgres — Design Spec

## Goal

Add Azure Database for PostgreSQL Flexible Server provisioning to AgentStack so agents deployed on Azure Container Apps can use Postgres-backed sessions and long-term memory — the same way they do on Docker today.

## Context

On Docker, `DockerServiceNode` spins up a `postgres:16-alpine` container on `agentstack-net` and injects `SESSION_STORE_URL` / `MEMORY_STORE_URL` into agent containers. The LangChain adapter reads these env vars to initialize `AsyncPostgresSaver` (checkpointer) and `AsyncPostgresStore` (memory).

On Azure, there is no Postgres provisioning. Agents with `sessions: {type: postgres}` deploy but have no database. This spec adds an `AzurePostgresNode` to the provision graph that creates an Azure Flexible Server and wires the connection string through the same env var contract.

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Provisioning mode | Provision managed + bring-your-own | `connection_string_env` on Service skips provisioning |
| SKU | Default `Standard_B1ms`, configurable | Cheapest burstable tier (~$13/mo), override via `config.sku` |
| Postgres version | Default `16`, configurable | Matches Docker `postgres:16-alpine` |
| Network access | AllowAllAzureServicesAndResourcesWithinAzureIps | No VNet needed for MVP, blocks non-Azure traffic |
| Multi-agent sharing | Same object = shared server | Pulumi-style dedup — same Python `id()` or YAML name |
| Database name | `agentstack` | Matches Docker convention |
| Admin user | `agentstack` | Matches Docker convention |

## Architecture

### Provision Graph

Current:
```
ResourceGroup → LogAnalytics → ACA Environment ─→ ContainerApp
             → ACR ─────────────────────────────→ ContainerApp
```

With Postgres:
```
ResourceGroup → LogAnalytics → ACA Environment ─→ ContainerApp
             → ACR ─────────────────────────────→ ContainerApp
             → PostgresServer ──────────────────→ ContainerApp
```

`AzurePostgresNode` depends on `ResourceGroup`. `ContainerAppNode` depends on `AzurePostgresNode` when the agent references a managed Postgres service. Postgres, ACR, and LogAnalytics are independent siblings — parallelizable in the future.

### Dedup Rule

Same Postgres object = one Flexible Server. Different objects = separate servers.

```python
# One server — both agents share it
db = Postgres(name="main-db", provider=azure)
weather = Agent(sessions=db, ...)
assistant = Agent(sessions=db, memory=db, ...)

# Two servers — isolated
sessions_db = Postgres(name="sessions-db", provider=azure)
memory_db = Postgres(name="memory-db", provider=azure)
agent = Agent(sessions=sessions_db, memory=memory_db, ...)
```

In YAML, named services work the same:
```yaml
services:
  main-db:
    type: postgres
    provider: azure

agents:
  weather-agent:
    sessions: main-db
  assistant-agent:
    sessions: main-db   # same name → same server
    memory: main-db
```

The provider builds the graph by collecting unique Postgres service objects (by `id()` in Python, by name in YAML). Each unique object becomes one `AzurePostgresNode`.

## AzurePostgresNode

### Inputs

| Parameter | Source | Description |
|-----------|--------|-------------|
| `credential` | `get_credential()` | DefaultAzureCredential |
| `subscription_id` | config / env / az CLI | Azure subscription |
| `rg_name` | provider config | Resource group name |
| `server_name` | derived from service name + RG | Globally unique server name |
| `location` | provider config, default `eastus2` | Azure region |
| `admin_user` | `agentstack` | Admin username |
| `admin_password` | auto-generated, stored in secrets | Admin password |
| `tags` | standard AgentStack tags | `agentstack:managed`, `agentstack:service` |

### Config Overrides

Available via `config` dict on the Postgres service:

| Key | Default | Description |
|-----|---------|-------------|
| `sku` | `Standard_B1ms` | Compute tier (Burstable/GeneralPurpose/MemoryOptimized) |
| `version` | `16` | PostgreSQL version |
| `storage_gb` | `32` | Storage size in GB |
| `backup_retention_days` | `7` | Backup retention (1-35 days) |

### Server Name Derivation

Server names must be globally unique across Azure. Derived from RG name + service name:
```python
def _server_name(rg_name: str, service_name: str) -> str:
    # e.g., "my-agents-rg" + "main-db" → "my-agents-rg-main-db"
    # Truncated/sanitized to meet Azure naming constraints (3-63 chars, lowercase alphanumeric + hyphens)
    raw = f"{rg_name}-{service_name}"
    sanitized = re.sub(r"[^a-z0-9-]", "-", raw.lower())[:63]
    return sanitized
```

### Provision Steps

1. **Check if server exists** — `GET` on the server resource. If it exists and is healthy, reuse it (idempotent).
2. **Create Flexible Server** — if not exists:
   - SKU: `Standard_B1ms` (or config override)
   - Version: `16` (or config override)
   - Storage: 32 GB (or config override)
   - Auth: password-only (`PostgreSQLAuthenticationEnabled`)
   - High availability: disabled (MVP)
   - Backup retention: 7 days (or config override)
3. **Wait for server ready** — poll until `state == "Ready"` (can take 3-5 minutes)
4. **Create firewall rule** — `AllowAllAzureServicesAndResourcesWithinAzureIps` (start: `0.0.0.0`, end: `0.0.0.0`)
5. **Create database** — `agentstack` database on the server (if not exists)
6. **Return connection string** in `ProvisionResult.info`:
   ```python
   {
       "engine": "postgres",
       "server_name": "my-agents-rg-main-db",
       "host": "my-agents-rg-main-db.postgres.database.azure.com",
       "connection_string": "postgresql://agentstack:{pwd}@{host}:5432/agentstack?sslmode=require",
   }
   ```

### Health Check

`TcpHealthCheck(host, 5432)` — verifies the server is accepting connections after provisioning.

### Emit Events

Progress events via `self.emit()`:
- `"Creating Postgres server"` — before `begin_create`
- `"Waiting for server ready"` — during polling
- `"Configuring firewall"` — before firewall rule
- `"Creating database"` — before database creation
- `"Postgres ready"` — after connection string confirmed

## Connection String Flow

Unchanged from Docker. The contract is:

1. **Provisioning** → `ProvisionResult.info["connection_string"]` = `postgresql://...`
2. **ContainerAppNode** reads upstream results from context → sets env vars:
   - `SESSION_STORE_URL` if the service is referenced by `agent.sessions`
   - `MEMORY_STORE_URL` if the service is referenced by `agent.memory`
3. **Generated agent code** reads `os.environ["SESSION_STORE_URL"]` → `AsyncPostgresSaver.from_conn_string()`
4. **Generated agent code** reads `os.environ["MEMORY_STORE_URL"]` → `AsyncPostgresStore.from_conn_string()`

### ContainerAppNode Changes

Currently `ContainerAppNode` only sets `SESSION_STORE_URL`. It needs to also handle `MEMORY_STORE_URL` by checking which service each agent field references:

```python
if agent.sessions and agent.sessions.name in context:
    env["SESSION_STORE_URL"] = context[agent.sessions.name].info["connection_string"]
if agent.memory and agent.memory.name in context:
    env["MEMORY_STORE_URL"] = context[agent.memory.name].info["connection_string"]
```

This same fix applies to `DockerAgentNode` which currently only sets `SESSION_STORE_URL`.

## Bring-Your-Own

If a Postgres service has `connection_string_env` set, no `AzurePostgresNode` is created. The env var is passed through directly to the ContainerApp:

```python
# In provider.py, when building the graph:
if service.is_managed:
    graph.add(AzurePostgresNode(...))  # provision it
else:
    # connection_string_env is already in the agent's env — just pass it through
    pass
```

```yaml
sessions:
  type: postgres
  connection_string_env: DATABASE_URL  # existing server, no provisioning
```

## Provider Changes

### `provider.py` — apply()

Before building `ContainerAppNode`, scan `agent.sessions`, `agent.memory`, and `agent.services` for managed Postgres services. For each unique service (by object identity / name), add one `AzurePostgresNode` to the graph.

```python
# Collect unique managed Postgres services
seen_services = {}
for agent in agents:
    for svc in [agent.sessions, agent.memory] + agent.services:
        if svc and svc.type == "postgres" and svc.is_managed:
            if svc.name not in seen_services:
                seen_services[svc.name] = svc

for svc in seen_services.values():
    graph.add(AzurePostgresNode(
        client=postgres_client,
        rg_name=rg_name,
        server_name=_server_name(rg_name, svc.name),
        location=location,
        admin_password=get_or_create_password(svc.name),
        config=svc.config,
        tags=tags,
    ))
```

### `pyproject.toml`

Add dependency: `azure-mgmt-rdbms>=10.2.0`

## Secrets Management

Admin password auto-generated on first deploy, stored in `.agentstack/secrets.json` (same as Docker). Key format: `azure-postgres-{server_name}`.

On subsequent deploys, the stored password is reused. If the server already exists, the password from secrets is used to construct the connection string without re-provisioning.

## Destroy

Already partially handled — `provider.py` destroy method has:
- `microsoft.dbforpostgresql/flexibleservers` in type order (priority 5)
- API version `2023-12-01-preview` in the version map

Tag-based cleanup will find and delete the server. No additional destroy code needed.

## Testing

- **Unit tests**: mock `azure.mgmt.rdbms` client, verify node creates server + firewall + database, returns correct connection string
- **Integration test**: deploy an agent with `sessions: postgres` to Azure, verify the server is created, agent can persist sessions
- **Bring-your-own test**: verify no server is created when `connection_string_env` is set

## Files

| Action | File | Description |
|--------|------|-------------|
| Create | `agentstack-provider-azure/src/.../nodes/postgres.py` | AzurePostgresNode |
| Modify | `agentstack-provider-azure/src/.../nodes/__init__.py` | Export new node |
| Modify | `agentstack-provider-azure/src/.../provider.py` | Add Postgres to graph |
| Modify | `agentstack-provider-azure/pyproject.toml` | Add `azure-mgmt-rdbms` |
| Modify | `agentstack-provider-azure/src/.../nodes/aca_app.py` | Set `MEMORY_STORE_URL` |
| Modify | `agentstack-provider-docker/src/.../nodes/agent.py` | Set `MEMORY_STORE_URL` |
| Create | `agentstack-provider-azure/tests/test_postgres_node.py` | Unit tests |

## Out of Scope

- VNet / private endpoint networking (Phase 2b)
- Key Vault for secret storage (Phase 2b)
- Managed Identity for auth (Phase 2b)
- Azure AD auth for Postgres (Phase 2b)
- Connection pooling (PgBouncer)
- Read replicas
- Automatic failover / high availability
