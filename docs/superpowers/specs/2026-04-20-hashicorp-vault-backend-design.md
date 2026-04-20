# HashiCorp Vault Backend (Docker) — Design

**Status:** draft
**Date:** 2026-04-20
**Author:** anatoliy@ankosoftware.com (with Claude)
**Follow-up to:** `docs/superpowers/specs/2026-04-19-secret-manager-design.md`

## Summary

Add a HashiCorp Vault backend for the Docker provider, extending the v1
Secret Manager feature that shipped Azure Key Vault only. The schema and
runtime SDK are unchanged; only the Docker provider learns to deploy a
production-mode Vault container with per-principal AppRoles and Vault
Agent sidecars. The isolation guarantee from v1 (LLM in agent container
cannot reach workspace secrets) is preserved using per-container Docker
volumes instead of ACA `secretRef` + `lifecycle: None`.

## Motivation

v1 shipped Azure-only. The Docker provider rejects `Vault` declarations
at plan time with a deferred-to-this-spec error. Users running Vystak
locally still rely on `.env`-passthrough with no secret-manager
abstraction, no rotation workflow, no LLM-to-workspace isolation, and no
feature parity with the Azure path.

This spec fills that gap by adding a first-class Vault backend for the
Docker provider. The feature lands under the same `Vault` schema
resource as v1, using `type="vault"` (v1 uses `type="key-vault"`).
Schema, CLI, and runtime SDK are unchanged.

## Goals

- Accept `Vault(type="vault", provider=docker, mode="deploy"|"external")`
  without the v1 plan-time rejection.
- Deploy a production-mode Vault container (sealed, file storage,
  persistent volume) when `mode="deploy"`. Auto-unseal on subsequent
  applies using a host-side key stash.
- Create one Vault AppRole per principal (agent, workspace, channel)
  with a policy scoped to only that principal's declared secrets.
- Run one Vault Agent sidecar per main container; each sidecar
  authenticates via its principal's AppRole and renders a per-container
  `secrets.env` file into a per-container shared volume.
- A generated entrypoint shim in the main container sources
  `secrets.env` into env before executing the main process. The runtime
  SDK (`vystak.secrets.get`) continues to read `os.environ[name]` —
  unchanged across backends.
- `.env` bootstrap via push-if-missing (with `--force`) works identically
  against Vault's KV v2 store.
- `vystak secrets {list, push, set, diff}` CLI dispatches to Vault or KV
  based on declared `Vault.type`. Plus new `vystak secrets rotate-approle`.

## Non-goals

- **Production Vault operations** (HSM/KMS/transit auto-unseal, HA,
  Raft storage, multi-node, upgrades, backup ceremony). Users needing
  this run Vault themselves and use `mode="external"`.
- **Alternate auth methods for external Vault** (Kubernetes, JWT,
  cloud-provider, token). v1 Hashi ships AppRole only.
- **SIGHUP-driven secret reload** without container restart. Values
  rotated via `vystak secrets push --force` require a restart of
  affected main containers to be picked up; Vault Agent re-renders the
  file but env has already been `exec`-evaluated. Follow-up spec if
  demand emerges.
- **Vault namespaces** (enterprise multi-tenancy).
- **Cross-backend migration** (move agents from KV to Vault without
  re-deploy). Out of scope; re-deploy is required.
- **Per-user / per-session / per-user-project workspace scope.** Same
  non-goal as v1; the orchestrator spec covers this.

## Architecture

### Concept model — delta from v1

**New for this spec:**
- Production-mode HashiCorp Vault as a deployable Docker container
  (persistent volume, file storage, Shamir seal with 5-of-3 unseal)
- Vault AppRole per principal with stable `role_id` and rotate-on-demand
  `secret_id`
- Vault Agent sidecar pattern — one sidecar container per main
  container, per-container AppRole mount, per-container secret volume
- `.vystak/vault/init.json` host-side unseal key stash (chmod 600,
  inherits existing `.vystak/` gitignore)
- Entrypoint shim injected into the main container's Dockerfile when
  Vault is declared

**Reused unchanged from v1:**
- `Vault` schema resource
- `Workspace.secrets`, `Workspace.identity`, `Agent.secrets`,
  `Channel.secrets`
- `vystak.secrets.get(name)` runtime helper
- `vystak secrets` CLI surface (with one new subcommand below)
- `.env`-driven bootstrap with push-if-missing, `--force`,
  `--allow-missing`
- Validator that a tool-secret-holding deployable (Workspace/Skill/
  McpServer/Channel) must declare `identity` (or auto-create one)

### Topology — agent + workspace example

```
┌─────────── Docker Compose network: vystak-net ──────────────────┐
│                                                                   │
│  ┌─ vystak-vault ─────────────────────────────────────────────┐   │
│  │ hashicorp/vault:1.17 vault server -config=.../vault.hcl   │   │
│  │ Volume: vystak-vault-data → /vault/file (persistent)       │   │
│  │ State: unsealed by vystak apply on each startup            │   │
│  └─────────────────────────────────────────────────────────────┘   │
│        │                                                            │
│        │ Vault API :8200                                            │
│        ▼                                                            │
│  ┌─ vystak-<agent>-vault-agent ─┐  ┌─ vystak-<ws>-vault-agent ─┐   │
│  │ vault agent -config=...      │  │ vault agent -config=...   │   │
│  │ AppRole: <agent>             │  │ AppRole: <workspace>      │   │
│  │ Mounts: <agent>-approle      │  │ Mounts: <ws>-approle      │   │
│  │ Writes: <agent>-secrets:/sh… │  │ Writes: <ws>-secrets:/sh… │   │
│  └─────────────┬───────────────┘  └────────┬──────────────────┘   │
│                │ <agent>-secrets           │ <ws>-secrets          │
│                ▼                           ▼                        │
│  ┌─ vystak-<agent> ──────────┐   ┌─ vystak-<workspace> ──────────┐ │
│  │ entrypoint-shim sources   │   │ entrypoint-shim sources       │ │
│  │ /shared/secrets.env       │   │ /shared/secrets.env           │ │
│  │ execs agent process       │   │ execs workspace process       │ │
│  └──────────────────────────┘    └──────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────┘
```

Each principal's `approle` and `secrets` volumes are distinct — the
agent container cannot mount the workspace's `secrets` volume because
the generated compose file simply doesn't reference it there.

## Schema changes

### `vystak/schema/common.py`

```python
class VaultType(StrEnum):
    KEY_VAULT = "key-vault"   # Azure (v1)
    VAULT = "vault"           # HashiCorp (this spec)
```

### `vystak/schema/vault.py` — unchanged shape

`config: dict` absorbs Vault-specific tuning. New recognized keys:

| Config key | Default | Purpose |
|---|---|---|
| `image` | `hashicorp/vault:1.17` | Vault server image tag |
| `port` | `8200` | API port inside Docker network |
| `host_port` | *unset* | If set, binds `host_port:8200` for CLI access |
| `seal_key_shares` | `5` | Shamir split count at init |
| `seal_key_threshold` | `3` | Keys required to unseal |
| `url` | — | `mode="external"` only: existing Vault endpoint |
| `token_env` | — | `mode="external"` only: env var name holding bootstrap auth token |

### Cross-object validator (in `multi_loader.py`)

- `Vault.type == KEY_VAULT` requires `Vault.provider.type == "azure"`.
- `Vault.type == VAULT` requires `Vault.provider.type == "docker"`.
- Other combinations raise at load time.

### DockerProvider validator update

Plan-time check becomes type-aware: reject `Vault.type == KEY_VAULT`,
accept `Vault.type == VAULT`. Reject any other enum value with a
forward-looking error message.

## Docker resources per deployment

| Resource | Name | Persisted | Destroyed by |
|---|---|---|---|
| Container | `vystak-vault` | — | `destroy --delete-vault` only |
| Volume | `vystak-vault-data` | Vault file storage | `destroy --delete-vault` only |
| Host file | `.vystak/vault/init.json` | Root token + unseal keys, chmod 600 | `destroy --delete-vault` only |
| Container | `vystak-<principal>-vault-agent` | — | Regular `destroy` |
| Volume | `vystak-<principal>-secrets` | Shared with main container | Regular `destroy` |
| Volume | `vystak-<principal>-approle` | `role_id` + `secret_id` files | Regular `destroy` |
| Vault | AppRole `<principal>` | Inside Vault KV data | Regular `destroy` |
| Vault | Policy `<principal>-policy` | Inside Vault KV data | Regular `destroy` |
| Vault | Secret values at `secret/data/<NAME>` | Inside Vault KV data | Never (matches v1 KV) |

## Bootstrap flow

### First apply

```
1. Build/pull hashicorp/vault:<tag>
2. docker volume create vystak-vault-data
3. docker run -d --name vystak-vault \
       -v vystak-vault-data:/vault/file \
       --network vystak-net \
       <image> vault server -config=/vault/config/vault.hcl
4. Poll vault status until Initialized=false, Sealed=true
5. docker exec vystak-vault vault operator init \
       -key-shares=5 -key-threshold=3 -format=json
6. Write stdout to .vystak/vault/init.json (chmod 600)
7. Unseal with 3 of 5 keys (sequential vault operator unseal <key>)
8. Using root token:
   - Enable KV v2 at secret/ (idempotent)
   - Enable AppRole auth at auth/approle/ (idempotent)
   - For each principal: create policy + AppRole
9. Push secret values from .env (push-if-missing semantics)
10. Write secret_id files to per-principal AppRole volumes
```

`.vystak/vault/init.json` format:

```json
{
  "unseal_keys_b64": ["...", "...", "...", "...", "..."],
  "root_token": "hvs.CAES...",
  "init_time": "2026-04-20T14:03:22Z"
}
```

### Subsequent apply

```
1. Detect container + volume + init.json exist
2. vault status:
   - Initialized=true, Sealed=true → auto-unseal from stash
   - Initialized=true, Sealed=false → skip unseal, proceed
   - Initialized=false → RECOVERY (see below)
3. Using root token from init.json:
   - Reconcile policies for current agent tree (add/remove/update)
   - Reconcile AppRoles (create new, update scope on existing)
   - Push secret values (push-if-missing unless --force)
4. Rewrite per-principal secret_id files if rotated
5. Vault Agent sidecars reload on their next poll interval or are
   restarted explicitly by vystak apply on secret_id rotation
```

### Recovery scenarios

| Scenario | Detection | Handling |
|---|---|---|
| `init.json` deleted, volume intact | File absent, Vault Initialized=true | Hard error. Unseal keys unrecoverable. User must `destroy --delete-vault` and start over. |
| Volume deleted, `init.json` intact | `docker volume inspect` fails | Delete stale `init.json`, proceed as first-apply. Warn that prior secrets are gone. |
| Both gone | Both absent | Clean first-apply. |
| Container missing, volume+init present | `docker inspect` fails | Recreate container attached to existing volume, skip init, auto-unseal. Normal "after reboot" path. |
| Vault running but wrong state | Unexpected `vault status` output | Abort with guidance: "Run `vystak destroy --delete-vault` and retry." No heroic repair in v1. |

## AppRole and policy shape per principal

For a principal with secrets `[S1, S2, S3]`:

```hcl
# policy: <principal>-policy
path "secret/data/S1" {
  capabilities = ["read"]
}
path "secret/data/S2" {
  capabilities = ["read"]
}
path "secret/data/S3" {
  capabilities = ["read"]
}
```

```
# AppRole: <principal>
#   token_policies:       [<principal>-policy]
#   token_ttl:            1h
#   token_max_ttl:        24h
#   bind_secret_id:       true
```

The Vault Agent authenticates using this AppRole; any read outside the
policy paths returns 403. Hard RBAC at the Vault layer, not deploy-time
scoping.

## Runtime wiring

### Vault Agent HCL (one per principal)

```hcl
# Generated by vystak — do not edit
exit_after_auth = false
pid_file = "/tmp/vault-agent.pid"

vault {
  address = "http://vystak-vault:8200"
}

auto_auth {
  method "approle" {
    config = {
      role_id_file_path   = "/vault/approle/role_id"
      secret_id_file_path = "/vault/approle/secret_id"
      remove_secret_id_file_after_reading = false
    }
  }
  sink "file" {
    config = {
      path = "/tmp/vault-token"
    }
  }
}

template {
  destination = "/shared/secrets.env"
  perms       = "0444"
  contents    = <<-EOT
    {{- with secret "secret/data/SECRET_NAME_1" }}
    SECRET_NAME_1={{ .Data.data.value }}
    {{- end }}
    {{- with secret "secret/data/SECRET_NAME_2" }}
    SECRET_NAME_2={{ .Data.data.value }}
    {{- end }}
  EOT
}
```

Template `contents` is generated from the principal's declared secret
names. `perms = 0444` (world-readable inside the volume) — safe because
the volume is mounted only in this principal's two containers.

### KV v2 secret layout

Every secret value is stored under `secret/data/<NAME>` with a single
field `value`:

```
vault kv put secret/<NAME> value=<VALUE>
```

The template renders `{{ .Data.data.value }}` to extract it. Matches
how `vystak secrets push` writes values.

### Entrypoint shim

Emitted into the main container's image by codegen when `Vault` is
declared:

```bash
#!/bin/sh
# /vystak/entrypoint-shim.sh — generated
set -e

SECRETS_FILE="/shared/secrets.env"

for i in $(seq 1 30); do
  [ -s "$SECRETS_FILE" ] && break
  sleep 1
done

if [ ! -s "$SECRETS_FILE" ]; then
  echo "vystak: $SECRETS_FILE never populated — Vault Agent unhealthy?" >&2
  exit 1
fi

set -a
. "$SECRETS_FILE"
set +a

exec "$@"
```

Dockerfile additions when Vault is declared (otherwise unchanged):

```dockerfile
COPY entrypoint-shim.sh /vystak/entrypoint-shim.sh
RUN chmod +x /vystak/entrypoint-shim.sh
ENTRYPOINT ["/vystak/entrypoint-shim.sh"]
CMD ["python", "server.py"]   # or whatever the main command was
```

### Volume mount matrix

| Volume | Mounted in | Path | Written by | Read by |
|---|---|---|---|---|
| `vystak-<principal>-approle` | Vault Agent | `/vault/approle` | `vystak apply` (role_id + secret_id files, chmod 400) | Vault Agent only |
| `vystak-<principal>-secrets` | Vault Agent + main container | `/shared` | Vault Agent (template) | Main container (entrypoint shim) |
| `vystak-vault-data` | Vault server only | `/vault/file` | Vault server | Vault server |

### Token lifecycle

- AppRole token TTL: 1h, renewable
- AppRole token max TTL: 24h
- Vault Agent auto-renews at 2/3 of TTL (default)
- If Vault goes down: Vault Agent keeps the last-rendered `secrets.env`
  intact; main container continues with last-known-good values

### UID and file permissions

Vault Agent runs as UID 100 (`vault` user). Main containers run as
UID 1000 (Python slim default). `secrets.env` uses `perms = 0444` so
both can read. Volume isolation is the actual security boundary; in-
volume file permissions are not relied upon.

### First-boot wait

The entrypoint shim blocks until `secrets.env` appears (up to 30s).
Typical: 1-3 seconds; cold start up to ~10s. The 30s ceiling is a
safety net — if hit, Vault Agent has failed for an unrelated reason
(bad AppRole, unreachable Vault, template error) and the shim exits
with a diagnostic.

## Trust boundary — what this does and doesn't prevent

### Prevents
- LLM in agent container cannot read workspace secrets: they're not in
  agent's env, not in agent's filesystem, and fetching them via Vault's
  API requires a token whose AppRole policy only allows the agent's
  secrets (not workspace's).
- A compromised Vault Agent sidecar holds only its own principal's
  short-TTL token; even full compromise leaks only that principal's
  scoped secrets.
- Cross-principal `role_id` / `secret_id` readability: each principal's
  AppRole credential volume is mounted only in that principal's Vault
  Agent container, not in any other.

### Does not prevent
- Host filesystem access to `.vystak/vault/init.json` grants full
  Vault root access. Anyone with host shell (or a `docker cp` equivalent)
  can read every secret. Documented as equivalent in sensitivity to
  `.env`.
- A container with Docker socket access could mount any volume and
  read any principal's `secrets.env`. Neither vystak-deployed container
  has Docker socket access by default; this only matters if a user
  opts in.
- Process-memory introspection inside a main container — same as v1
  Azure path. Code-exec tools must live in separate principals
  (McpServer with its own principal), not in the agent container.

### Explicitly documented
The spec's README will note:

> `.vystak/vault/init.json` is sensitive — keep it out of backups you
> don't trust, keep it out of source control (inherits the `.vystak/`
> gitignore), chmod 600 enforced at write time. Losing this file while
> the volume survives is unrecoverable: unseal keys exist nowhere else.
> If you need a stronger seal model (HSM auto-unseal, transit unseal,
> cloud KMS), run Vault yourself and use `mode="external"`.

## CLI surface

### Backend dispatch for existing subcommands

| Subcommand | Azure KV | Hashi Vault |
|---|---|---|
| `list` | `SecretClient.list_properties_of_secrets()` | Vault `secret/metadata/?list=true` |
| `push [NAME...] [--force] [--allow-missing]` | `get_secret` / `set_secret` with push-if-missing | `vault kv get` / `vault kv put` with same semantics |
| `set NAME=VALUE` | `set_secret` | `vault kv put secret/<NAME> value=<VALUE>` |
| `diff` | Compare `.env` to KV, never print values | Compare `.env` to Vault values, never print values |

Dispatch happens in `vystak-cli/commands/secrets.py` by inspecting the
declared `Vault.type`.

### New subcommand

```
vystak secrets rotate-approle <principal>                # new secret_id only
vystak secrets rotate-approle <principal> --rotate-role-id
vystak secrets rotate-approle --all                      # all principals
```

Hashi-only. Rotates the AppRole `secret_id`, writes the new credential
to the per-principal volume, restarts the Vault Agent sidecar. Main
container does not restart — its env does not change; the Agent
renews its own token on next cycle.

### `vystak plan` output for Vault-backed Docker deploys

```
Vault:
  vystak-vault (vault, deploy, docker)   will start

AppRoles:
  assistant-agent      will create (policy: 1 secret)
  assistant-workspace  will create (policy: 1 secret)

Secrets:
  ANTHROPIC_API_KEY    will push  (presence depends on .env and vault state)
  STRIPE_API_KEY       will push  (presence depends on .env and vault state)

Policies:
  assistant-agent      → ANTHROPIC_API_KEY  (read)
  assistant-workspace  → STRIPE_API_KEY     (read)
```

"Identities" → "AppRoles", "Grants" → "Policies". No secret values
at any verbosity.

### `vystak apply` output

No new flags. When Vault is first-deployed, the apply output surfaces
the init fingerprint once:

```
Vault initialized:
  init.json:  .vystak/vault/init.json  (chmod 600)
  Sensitive — keep out of backups and source control.
```

### `vystak destroy` flags

| Flag | Effect |
|---|---|
| (default) | Remove main + Vault Agent sidecar containers + per-principal volumes. Vault server + data + init.json preserved. |
| `--delete-vault` | Also remove `vystak-vault` container, `vystak-vault-data` volume, and `.vystak/vault/init.json`. Unrecoverable. |
| `--keep-sidecars` | Leave Vault Agent sidecars running. Useful for local iteration; they 403 on deleted principals' policies and quietly continue serving the alive ones. |

## Hash tree

No new fields. A change in `Vault.type` changes the existing `vault`
section hash, triggering appropriate redeploy. The existing `grants`
field (from v1) captures the AppRole → policy-path mapping equivalently
to the Azure (principal → KV secret) mapping — same shape, different
backend.

## File structure (to be created / modified)

**New:**
- `packages/python/vystak-provider-docker/src/vystak_provider_docker/nodes/hashi_vault.py`
  — `HashiVaultServerNode`, `HashiVaultInitNode`, `HashiVaultUnsealNode`
- `packages/python/vystak-provider-docker/src/vystak_provider_docker/nodes/vault_agent.py`
  — `VaultAgentSidecarNode`
- `packages/python/vystak-provider-docker/src/vystak_provider_docker/nodes/approle.py`
  — `AppRoleNode` (creates policy + AppRole via Vault API)
- `packages/python/vystak-provider-docker/src/vystak_provider_docker/nodes/vault_secret_sync.py`
  — `VaultSecretSyncNode` (push-if-missing against Vault KV v2)
- `packages/python/vystak-provider-docker/src/vystak_provider_docker/vault_client.py`
  — Thin wrapper for Vault HTTP API (init, unseal, auth, kv v2, approle)
- `packages/python/vystak-provider-docker/src/vystak_provider_docker/templates.py`
  — HCL generators (server config, agent config, policy)
- `packages/python/vystak-provider-docker/tests/test_node_hashi_vault.py`
- `packages/python/vystak-provider-docker/tests/test_node_vault_agent.py`
- `packages/python/vystak-provider-docker/tests/test_node_approle.py`
- `packages/python/vystak-provider-docker/tests/test_node_vault_secret_sync.py`
- `packages/python/vystak-provider-docker/tests/test_templates.py`
- `packages/python/vystak-provider-docker/tests/test_vault_integration.py` (docker-marked)
- `examples/docker-workspace-vault/vystak.py`, `vystak.yaml`,
  `.env.example`, `README.md`, `tools/charge_card.py`

**Modified:**
- `packages/python/vystak/src/vystak/schema/common.py` — add `VaultType.VAULT`
- `packages/python/vystak/src/vystak/schema/multi_loader.py` — add
  cross-object validator for `(vault.type, provider.type)` pairing
- `packages/python/vystak-provider-docker/src/vystak_provider_docker/provider.py`
  — type-aware `Vault` plan-time check; wire new nodes into `apply` graph
- `packages/python/vystak-provider-docker/src/vystak_provider_docker/nodes/__init__.py`
  — export new nodes
- `packages/python/vystak-provider-docker/src/vystak_provider_docker/nodes/agent.py`
  — entrypoint-shim injection when Vault is declared
- `packages/python/vystak-provider-docker/src/vystak_provider_docker/nodes/channel.py`
  — same entrypoint-shim injection
- `packages/python/vystak-cli/src/vystak_cli/commands/secrets.py` — dispatch
  by `Vault.type`; add `rotate-approle` subcommand
- `packages/python/vystak-cli/src/vystak_cli/commands/plan.py` — render
  Hashi-specific AppRoles/Policies sections
- `packages/python/vystak-cli/src/vystak_cli/commands/destroy.py` — add
  `--delete-vault`, `--keep-sidecars` flags
- `pyproject.toml` of `vystak-provider-docker` — add `hvac>=2.0` (Vault
  HTTP client) if we choose a library over raw httpx; see Open Questions

## Testing

### Unit tests (no Docker)

1. `VaultType.VAULT` enum value + cross-object validator tests
2. `DockerProvider` accepts `Vault.type == VAULT`, still rejects `KEY_VAULT`
3. HCL template generators — server config, agent config, policy: exact
   byte-for-byte output given input
4. Entrypoint shim generator — exact byte-for-byte output
5. Dockerfile injection logic — shim is added iff Vault is declared
6. `vault_client.py` wrapper — all Vault API calls mocked at HTTP layer
7. `AppRoleNode.provision()` — creates policy + role, returns role_id +
   secret_id; destroy deletes both
8. `VaultSecretSyncNode.provision()` — push-if-missing, force, allow-missing
   paths, all HTTP-mocked
9. `vystak secrets` CLI dispatch — correct backend given `Vault.type`
10. `rotate-approle` CLI — generates new secret_id, writes to volume,
    restarts sidecar

### Docker integration tests (opt-in, `-m docker`)

1. `test_vault_deploy_bootstrap` — fresh `vystak apply`, verify:
   - `vystak-vault` running
   - `init.json` written (chmod 600)
   - Vault unsealed
   - One AppRole + policy per principal
   - Secrets pushed to KV
   - Vault Agent containers running
   - `secrets.env` rendered per-principal
   - Main container has secret in env
2. `test_vault_idempotent_apply` — apply twice: no duplicate policies,
   no re-init, same `init.json` contents
3. `test_vault_restart_auto_unseal` — `docker restart vystak-vault`,
   run `vystak apply`, verify auto-unseal from stash
4. `test_vault_isolation` — exec into agent container:
   - `cat /shared/secrets.env` shows only agent's secrets
   - `curl http://vystak-vault:8200/v1/secret/data/<workspace's secret>`
     without token returns 400; with agent's token returns 403
5. `test_rotate_approle` — `vystak secrets rotate-approle <agent>`:
   new secret_id present; sidecar restarted; main container still healthy
6. `test_destroy_preserves_vault` — `vystak destroy` (no flag):
   `vystak-vault` still running with same volume and `init.json`
7. `test_destroy_delete_vault` — `vystak destroy --delete-vault`:
   Vault container + volume + `init.json` all gone

Estimated total integration run time: 90-120s.

## Examples

- `examples/docker-workspace-vault/` — agent + workspace + Hashi Vault,
  mirrors `examples/azure-workspace-vault/` structure. Demonstrates the
  isolation story end-to-end on Docker.

No simple-agent Hashi example — the selling point is workspace isolation;
a single-agent Hashi deploy is less illustrative than Azure's because
the Docker env-passthrough path already works fine without Vault.

## Validation and error messages

At load time:

- `Vault(type='vault') requires provider.type='docker'. Current: provider.type='azure'.`
- `Vault(type='key-vault') requires provider.type='azure'. Current: provider.type='docker'.`

At plan time:

- `Vault(type='vault') with mode='external' requires config['url']. Add: config={'url': 'http://vault.example:8200', 'token_env': 'VAULT_TOKEN'}`

At apply time:

- `Vault init already recorded at .vystak/vault/init.json but Vault container reports Initialized=false. State mismatch — run 'vystak destroy --delete-vault' to start fresh.`
- `Vault KV value for '<NAME>' was rotated — restart '<container>' to pick up the new value. (Env is evaluated at container start; Vault Agent has updated secrets.env but the running process still has old values.)`
- `AppRole authentication failed for '<principal>' — the AppRole may have been rotated externally. Run 'vystak secrets rotate-approle <principal>' to regenerate vystak-managed credentials.`

## Open questions for implementation

- **Vault API client library.** `hvac` is the canonical Python Vault
  client (well-maintained, covers init/unseal/approle/kv-v2). Alternative:
  raw `httpx` against the Vault HTTP API (smaller dep footprint, more
  code to write). **Recommendation:** use `hvac` — saves ~200 lines of
  HTTP-glue code and handles edge cases (lease renewal, wrap/unwrap)
  we'd otherwise have to reimplement.
- **Vault image tag pinning strategy.** Default `hashicorp/vault:1.17`
  pins a major.minor. Minor version bumps land patches; major version
  needs a deliberate upgrade. Document the upgrade path (destroy-
  recreate or swap image in config + restart).
- **Compose generation vs. direct Docker API calls.** The existing
  DockerProvider uses `docker-py` direct calls for containers; the new
  Vault stack could also use compose for simpler orchestration. **Stay
  consistent** with existing provider style — use `docker-py` direct.
  `depends_on` semantics implemented in provisioning-graph dependencies,
  not in a compose file.

## Rationale for cut decisions

**Why not share v1's Azure nodes via a common abstraction?** Vault's
init/seal/unseal lifecycle has no Azure analogue. Forcing a shared
`VaultInitNode` base class would have abstractions that fit neither
backend's reality. Each provider gets its own nodes; the `Vault` schema
resource is the stable coupling point.

**Why production-mode Vault rather than dev-mode?** Dev-mode Vault loses
all state on container restart — every laptop reboot means re-setting
every secret, re-creating every AppRole, re-generating every credential.
Unusable in practice. Production mode plus host-side unseal stash gives
persistence with a honest trust boundary.

**Why not rotate AppRole every apply?** Matches Azure UAMI's "stable
identity" model, keeps the two backends conceptually identical from the
user's mental-model perspective, avoids unnecessary container restarts
that slow local iteration. Explicit rotation available via
`rotate-approle` when wanted.

**Why env-shim instead of runtime Vault API?** Keeps the runtime SDK
uniform (`vystak.secrets.get(name)` is `os.environ[name]` on both
backends — zero branching, zero dual-path tests). Avoids making tool
calls depend on Vault availability. Matches Azure path's "secrets
materialized at container start" semantics.

## Follow-on specs (named, not written)

- `2026-??-XX-vault-signal-reload-design.md` — Optional SIGHUP reload
  support so rotated secrets are picked up without container restart.
- `2026-??-XX-external-vault-auth-methods-design.md` — Kubernetes, JWT,
  cloud-provider auth for `mode="external"` Vault.
- `2026-??-XX-vault-namespaces-design.md` — Vault Enterprise namespace
  support for multi-tenant deployments.
