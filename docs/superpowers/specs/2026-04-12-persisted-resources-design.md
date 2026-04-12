# Persisted Resources — Design Spec

## Overview

Add full resource provisioning to AgentStack. When an agent defines a `SessionStore` resource, the Docker provider provisions the backing infrastructure (Postgres container or SQLite volume), the adapter generates the appropriate checkpointer code, and sessions persist across container restarts and redeployments.

## Decisions

| Decision | Choice |
|----------|--------|
| Resource types | SessionStore with Postgres and SQLite engines |
| Provisioning | Docker provider creates/manages resource containers |
| Container naming | `agentstack-resource-{resource.name}` |
| Resource sharing | By resource name — same name = same container |
| Networking | Docker network `agentstack-net`, all containers attached |
| Connection security | Generated password stored in `.agentstack/secrets.json` (gitignored) |
| Data persistence | Docker volumes (`agentstack-data-{name}`), survive container removal |
| Destroy behavior | Agent only by default; `--include-resources` removes resource containers but keeps volumes |

## Resource Provisioning Flow

When `agentstack apply` runs:

1. Ensure Docker network `agentstack-net` exists
2. For each resource in `agent.resources`:
   - Check if backing container/volume exists
   - Provision if needed (start Postgres container, create volume)
   - Wait for readiness
   - Store/retrieve credentials from `.agentstack/secrets.json`
3. Generate code — adapter picks checkpointer based on resource type/engine
4. Build Docker image
5. Deploy agent container on `agentstack-net` with connection env vars

## SessionStore: Postgres Engine

**Provisioning:**
- Image: `postgres:16-alpine`
- Container name: `agentstack-resource-{resource.name}`
- Volume: `agentstack-data-{resource.name}` mounted at `/var/lib/postgresql/data`
- Network: `agentstack-net`
- Environment: `POSTGRES_DB=agentstack`, `POSTGRES_USER=agentstack`, `POSTGRES_PASSWORD={generated}`
- Labels: `agentstack.resource={name}`, `agentstack.engine=postgres`
- Wait for Postgres to be ready before deploying agent

**Connection string:** `postgresql://agentstack:{password}@agentstack-resource-{name}:5432/agentstack`

Injected into agent container as `SESSION_STORE_URL` env var.

**Generated agent code:**
```python
import os
from langgraph.checkpoint.postgres import PostgresSaver
memory = PostgresSaver.from_conn_string(os.environ["SESSION_STORE_URL"])
agent = create_react_agent(model, tools, checkpointer=memory, ...)
```

**Additional requirement in generated requirements.txt:** `langgraph-checkpoint-postgres`

## SessionStore: SQLite Engine

**Provisioning:**
- No separate container
- Volume: `agentstack-data-{resource.name}` mounted into agent container at `/data`

**Generated agent code:**
```python
from langgraph.checkpoint.sqlite import SqliteSaver
memory = SqliteSaver.from_conn_string("/data/sessions.db")
agent = create_react_agent(model, tools, checkpointer=memory, ...)
```

**Additional requirement in generated requirements.txt:** `langgraph-checkpoint-sqlite`

## No SessionStore (default)

Current behavior unchanged:
```python
from langgraph.checkpoint.memory import MemorySaver
memory = MemorySaver()
```

## Secrets Management

**`.agentstack/secrets.json`** stores generated credentials:

```json
{
  "resources": {
    "sessions": {
      "password": "generated-random-password"
    }
  }
}
```

- Created on first provision
- Read on subsequent deploys
- Gitignored (`.agentstack/` already in `.gitignore`)
- Provider generates a secure random password on first provision
- If the file exists and has a password for the resource, reuse it

## Docker Network

**`agentstack-net`:**
- Created by the Docker provider if it doesn't exist
- All agent containers and resource containers attach to it
- Containers reach each other by name (e.g., `agentstack-resource-sessions`)
- Not removed on `destroy` (shared infrastructure)

## Destroy Behavior

```
agentstack destroy                      → remove agent container only
agentstack destroy --include-resources   → remove agent + resource containers, keep volumes
```

Volumes are never removed by AgentStack. Data is only lost if the user explicitly runs `docker volume rm`.

## File Changes

### packages/python/agentstack-provider-docker/

**Split `provider.py` into:**

```
src/agentstack_provider_docker/
├── __init__.py               # re-export DockerProvider
├── provider.py               # DockerProvider orchestration
├── network.py                # ensure_network()
└── resources.py              # provision_resource(), destroy_resource(), get_connection_info()
```

**`network.py`:**
- `ensure_network(client, name="agentstack-net")` — create network if not exists, return it

**`resources.py`:**
- `provision_resource(client, resource, secrets_path)` — provision backing container/volume for a resource
- `destroy_resource(client, resource_name)` — stop and remove resource container (keep volume)
- `get_connection_info(client, resource, secrets_path)` — return connection string for a provisioned resource
- `_generate_password()` — generate a secure random password
- `_load_secrets(secrets_path)` / `_save_secrets(secrets_path, data)` — read/write `.agentstack/secrets.json`

**`provider.py` changes:**
- `apply()` — provision resources before building image, attach to network, inject `SESSION_STORE_URL`
- `destroy()` — add `include_resources` parameter
- Agent container runs on `agentstack-net`
- SQLite resources mount volume into agent container

### packages/python/agentstack-adapter-langchain/

**`templates.py` changes:**
- `generate_agent_py()` — inspect `agent.resources` for SessionStore, generate appropriate checkpointer
- `generate_requirements_txt()` — add `langgraph-checkpoint-postgres` or `langgraph-checkpoint-sqlite` when needed

### packages/python/agentstack-cli/

**`commands/destroy.py`:**
- Add `--include-resources` flag
- Pass to provider

### Examples

**`examples/hello-agent/agentstack.yaml`:**
- Add `resources` section with SessionStore(engine="postgres")

## Testing Strategy

### test_network.py
- `test_create_network` — creates network when it doesn't exist
- `test_reuse_network` — returns existing network
- All tests mock Docker SDK

### test_resources.py
- `test_provision_postgres` — starts Postgres container with correct config, volume, network
- `test_provision_postgres_existing` — reuses existing container
- `test_provision_sqlite_volume` — creates volume only
- `test_destroy_resource` — stops and removes container, keeps volume
- `test_generate_password` — returns a random string
- `test_secrets_roundtrip` — save and load from secrets.json
- `test_get_connection_info_postgres` — returns correct connection string
- All tests mock Docker SDK

### test_templates.py (updates)
- `test_postgres_checkpointer` — generated code uses PostgresSaver
- `test_sqlite_checkpointer` — generated code uses SqliteSaver
- `test_no_resource_uses_memory` — default MemorySaver unchanged
- `test_postgres_requirements` — includes langgraph-checkpoint-postgres
- `test_sqlite_requirements` — includes langgraph-checkpoint-sqlite

## What This Spec Does NOT Cover

- Redis, DynamoDB, or other session store engines
- VectorStore, Database, Cache, ObjectStore, Queue provisioning
- Cloud-based resource provisioning (RDS, ElastiCache, etc.)
- Resource migrations or schema changes
- Multi-agent resource sharing validation
