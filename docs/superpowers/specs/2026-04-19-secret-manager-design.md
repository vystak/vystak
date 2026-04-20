# Secret Manager — Design

**Status:** draft
**Date:** 2026-04-19
**Author:** anatoliy@ankosoftware.com (with Claude)

## Summary

Introduce a vault-backed secret management path for Vystak. Replace today's
scattered `.env`-driven passthrough with a declarative `Vault` resource
(Azure Key Vault in v1), bootstrapped from `.env` at `vystak apply`, with
per-container secret scoping that prevents the LLM in the agent container
from reaching secrets that belong to the workspace container.

The design prioritizes a simple, shippable v1: one backend (Azure KV), one
topology (sidecar on ACA), one SDK function (`vystak.secrets.get`). Multi-
agent workspaces, exec sandboxes, HashiCorp Vault, and per-user scope are
named as follow-ups.

## Motivation

Today every existing example calls `ast.Secret(name="ANTHROPIC_API_KEY")`,
and the provider reads `os.environ[name]` at deploy time, inlining the
value into a Container App secret. Three problems:

1. **Local-env dependence.** The deployer's shell is the source of truth.
   CI, rotation, and operator handoff are all awkward.
2. **No scoping.** Every secret declared on an agent is reachable by every
   tool in that agent container. A `run_python` / code-exec tool or an
   arbitrary-HTTP tool can read any env var.
3. **No principal separation.** The agent container holds model API keys
   alongside DB credentials, Slack tokens, external-API keys — a single
   compromise exposes everything.

The prompt-injection threat model makes this worse: any of the agent's
tools can be coerced by the LLM to exfiltrate secrets in its reach. The
defense has to be topological (process / identity boundary), not
disciplinary (asking tool authors to be careful).

## Goals

- A declarative `Vault` resource, deployable or linked to an existing store.
- `.env`-driven bootstrap: `vystak apply` pushes local `.env` values to the
  Vault, skipping already-present keys (`--force` to overwrite).
- Workspace-scoped secrets: secrets declared on `Agent.workspace` are
  materialized only into the workspace container's env, never the agent
  container's.
- Real runtime isolation on Azure: the LLM in the agent container has no
  path (IMDS, token endpoint, shared env) to reach workspace secrets.
- Backward compatibility: every existing example continues to work
  unchanged, using the existing `os.environ` passthrough.

## Non-goals (named, not implemented in v1)

- HashiCorp Vault backend — v1 ships Azure Key Vault only. Hashi support
  gets its own spec when a Docker-prod user needs it.
- Multi-agent workspace sharing (N agents referencing one workspace) —
  `Agent.workspace` stays 1:1 in v1. Top-level-workspace redesign is a
  follow-on.
- `Workspace.exec=True` (coding-agent sandboxes) — v1 ships no exec-mode
  workspace. Skills needing code execution use an `McpServer` with its
  own compute.
- Per-user / per-session / per-user-project workspace scope — v1 only
  supports `scope="shared"` semantics (no schema field for this yet;
  added when orchestrator spec lands).
- `SecretClient` with typed HTTP/DB clients, redacted exceptions, and
  telemetry scrubbers — v1 ships a single `get()` function. Redaction
  and typed clients are documented as follow-on work.
- Workspace orchestrator + warm pool — follow-on.
- Explicit `Principal` schema object — v1 uses auto-UAMI per deployable.
  Users can override by passing an existing UAMI resource ID.

## Schema changes

### New: `Vault` (top-level resource)

`packages/python/vystak/src/vystak/schema/vault.py`

```python
from vystak.schema.common import NamedModel, VaultType, VaultMode
from vystak.schema.provider import Provider


class Vault(NamedModel):
    """A secrets backing store — deployed by vystak or linked as external.

    Declared once per deployment. Every `Secret` in the declaration's
    agent tree materializes through this vault.
    """

    type: VaultType = VaultType.KEY_VAULT
    provider: Provider
    mode: VaultMode = VaultMode.DEPLOY
    config: dict = {}

    @model_validator(mode="after")
    def _validate(self) -> Self:
        if self.mode is VaultMode.EXTERNAL and not self.config:
            raise ValueError(
                "External Vault must declare config identifying the existing "
                "store (e.g. config={'vault_name': 'my-vault'})."
            )
        return self
```

### Extended: `common.py`

```python
class VaultType(StrEnum):
    KEY_VAULT = "key-vault"   # Azure Key Vault — only v1-supported backend


class VaultMode(StrEnum):
    DEPLOY = "deploy"
    EXTERNAL = "external"
```

### Extended: `Workspace`

```python
class Workspace(NamedModel):
    # ... existing fields (type, provider, filesystem, terminal, etc.) ...
    secrets: list[Secret] = []
    identity: str | None = None   # existing UAMI resource ID; auto-created if None

    # Note: cross-object check "workspace secrets require Azure provider"
    # lives in `vystak/schema/multi_loader.py` during load, not here —
    # Workspace.provider may be None at construction time if inherited
    # from the Agent's platform.
```

**Materialization semantics:**
- `Agent.secrets` → each secret's value is wired (via ACA `secretRef` or
  env passthrough) into **the agent container's env only**.
- `Workspace.secrets` → wired into **the workspace container's env only**.
- `Channel.secrets` → wired into the channel's own ACA app env
  (channels deploy as separate ACA apps today; see
  `vystak_provider_azure/nodes/aca_channel_app.py`).
- Each deployable gets its own auto-created UAMI with narrow RBAC.

### Unchanged

- `Secret` — today's shape. Just `name` (with optional `path` / `key`).
- `Agent` — `workspace: Workspace | None` stays 1:1.
- `Channel` — `secrets: list[Secret]` unchanged.
- `Skill`, `McpServer` — no new fields.

### Implicit default

If no `Vault` is declared in the deployment, the implicit "env passthrough"
path applies to every `Secret`: deploy-time `os.environ[name]` is inlined
into ACA / Docker container env. This preserves today's behavior for every
existing example with zero migration.

## Architecture

### Deployment topology on Azure

When a `Vault` is declared AND the agent's workspace declares any secrets,
the provider emits a **single ACA app with two containers** (agent +
workspace sidecar):

```
┌─────────────────── ACA app (one revision) ─────────────────────┐
│                                                                 │
│  userAssignedIdentities:                                       │
│    • agent-uami       (lifecycle: None, RBAC: model secrets)   │
│    • workspace-uami   (lifecycle: None, RBAC: tool secrets)    │
│                                                                 │
│  configuration.secrets:                                        │
│    • anthropic-api-key  keyVaultUrl=..., identity=agent-uami  │
│    • stripe-api-key     keyVaultUrl=..., identity=workspace-u.│
│                                                                 │
│  ┌─── Agent container ─────┐   ┌─── Workspace container ────┐ │
│  │ env:                     │   │ env:                       │ │
│  │  ANTHROPIC_API_KEY ←ref  │   │  STRIPE_API_KEY ←ref       │ │
│  │                          │   │                            │ │
│  │ Cannot acquire a token   │   │ Cannot acquire a token     │ │
│  │ for any UAMI via the     │   │ for any UAMI via the       │ │
│  │ token endpoint — all     │   │ token endpoint — same      │ │
│  │ lifecycle: None.         │   │                            │ │
│  └──────────────────────────┘   └────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

**Why this is real isolation:**

- ACA's `identitySettings[].lifecycle: None` explicitly blocks container
  code from fetching tokens for that identity via the ACA token endpoint.
  Each container can hit `$IDENTITY_ENDPOINT` and get back "no identity."
- Per-container `env[].secretRef` means each container's env contains only
  the secrets explicitly wired to it. Agent container never has
  `STRIPE_API_KEY` in any form.
- ACA does not expose the standard Azure IMDS endpoint
  (`169.254.169.254`). The token endpoint is ACA-controlled and enforces
  lifecycle.
- Two separate UAMIs with narrow per-secret RBAC give defense-in-depth
  even if lifecycle were bypassed.

**Topology cases:**

| `Vault` declared | `Agent.secrets` | `Workspace.secrets` | Topology |
|---|---|---|---|
| no | any | any | Single-container agent, env-passthrough (today) |
| yes | any | empty | Single-container agent, KV secretRef for agent env |
| yes | any | non-empty | Sidecar (2 containers), per-container KV secretRef |
| yes | empty | non-empty | Sidecar; agent container has no secrets in its env |

`Channel.secrets` materializes into the channel's own ACA app regardless
of the table above.

### Deployment topology on Docker (dev)

Azure Key Vault is Azure-only. On Docker, if a user declares a
`Vault(type="key-vault", ...)`, the provider rejects it at plan time
(v1 limitation). On Docker the existing `os.environ` passthrough path
remains the default and only option.

### Security residual trust boundary

What the design **does** prevent:
- LLM in agent container cannot obtain a token for the workspace UAMI.
- LLM in agent container cannot read `STRIPE_API_KEY` from env, filesystem,
  or network metadata endpoints.
- LLM output in tool responses cannot include a secret value that was
  never in the agent container's address space to begin with.

What the design **does not** prevent (documented limitations):
- The workspace container itself holds `STRIPE_API_KEY` in memory. A
  compromised or buggy tool in the workspace can leak it via
  response body, exception string, log line, telemetry span, or the
  workspace's gRPC return to the agent. Tool-author discipline is
  required (don't log requests, don't return error strings verbatim).
- If the agent container has a tool that does `return os.environ.keys()`
  or similar introspection of its own process, the LLM sees its own
  model-provider API key. That's by design — the model key IS meant to
  be in the agent container.
- Supply-chain compromise of a dependency in either container exposes
  every secret that container holds. Principal-scoping limits blast
  radius to one container's secrets.

## Runtime SDK

One function. Emitted into both agent and workspace container images.

```python
# vystak.secrets
def get(name: str) -> str:
    """Return the value of the named secret.

    The value is materialized into the container's environment at start
    (via ACA secretRef for vault-backed deployments, or via os.environ
    for env-passthrough deployments). This function is a thin wrapper
    over os.environ[name] with a clearer error on missing keys.
    """
    try:
        return os.environ[name]
    except KeyError:
        raise SecretNotAvailableError(
            f"Secret {name!r} is not available in this container. "
            f"Declare it on the Agent / Workspace / Channel that uses it."
        )
```

No typed HTTP clients, no exception redaction, no telemetry scrubbers in
v1. A ruff-level lint rule flags raw `os.environ["X"]` reads where `X`
matches a declared secret name, suggesting `vystak.secrets.get(...)`
instead — the wrapper carries no security guarantee, but its presence in
code makes audit easier.

Follow-on work adds typed clients and redaction; the spec path is
compatible (`vystak.secrets.http_client(name)` can be added later
without breaking existing call sites).

## Deploy lifecycle

### `vystak apply` — phase additions

Deterministic phase order in the provisioning graph:

1. Provider auth (existing)
2. Platform prereqs (existing)
3. **Vault node** — `mode="deploy"` creates the KV; `mode="external"`
   verifies it exists and fails fast if not.
4. **Identity nodes** — one UAMI per deployable with secrets (per-agent,
   per-workspace, per-channel). Skipped if user provided `identity=...`
   override.
5. **Grant nodes** — KV role assignments: each UAMI granted
   `Key Vault Secrets User` on only its scoped secrets. Computed from the
   agent tree at plan time.
6. **Secret sync nodes** — read `.env`, push each declared secret to KV
   with push-if-missing semantics.
7. Agent / Workspace compute (existing; now emits ACA secretRef wiring)
8. Channel compute (existing)
9. DNS / ingress (existing)

### Secret sync — push-if-missing

Per secret:

```
if KV has the secret:
    skipped (KV value preserved)
elif .env has the secret:
    pushed to KV
else:
    missing (apply aborts with actionable error listing all missing)
```

`vystak apply --force` flips to push-always: every secret whose value
exists in `.env` is pushed to KV, overwriting. Missing-in-`.env` secrets
still abort unless `--allow-missing` is also set.

### `vystak destroy`

- Removes Agent / Workspace / Channel compute.
- Removes grants (role assignments).
- Removes auto-created UAMIs (not user-provided ones).
- **Does not** delete secret values from KV.
- **Does not** delete the KV itself unless `--delete-vault` is passed.

Rationale: secrets outlive deployments (rotation state, shared across
envs); destroy should not be destructive to them.

### `vystak secrets` CLI

```
vystak secrets list              # declared secrets + presence in KV
vystak secrets push [NAME...]    # push from .env (push-if-missing)
vystak secrets push --force      # overwrite KV values from .env
vystak secrets set NAME=VALUE    # set one value directly (not from .env)
vystak secrets diff              # .env vs KV (present / missing / differs)
```

`list` and `diff` never print secret values — only presence, last-updated
timestamp, and a hash prefix for change detection.

### `vystak plan` — new output sections

```
Vault:
  vystak-vault (key-vault, deploy, azure)   will create

Identities:
  assistant-agent      will create (UAMI, lifecycle: None)
  assistant-workspace  will create (UAMI, lifecycle: None)

Secrets:
  ANTHROPIC_API_KEY   will push  (in .env, absent in KV)
  STRIPE_API_KEY      will skip  (present in KV)

Grants:
  assistant-agent      → ANTHROPIC_API_KEY  will assign
  assistant-workspace  → STRIPE_API_KEY     will assign
```

No secret values appear at any verbosity.

### Hash tree additions

`AgentHashTree` and `WorkspaceHashTree` gain:

- `vault: str` — hash of the declared `Vault` resource (name, type, mode,
  provider, config).
- `identity: str` — hash of the deployable's identity config (auto-created
  or user-provided UAMI resource ID).
- `grants: str` — hash of the computed `(identity, secret_name)` set.

Secret **values** do not affect the hash — they're behavioral state tracked
by the KV, not deploy identity. Changing a secret value via
`vystak secrets push --force` does not trigger a redeploy.

### `.vystak/` state additions

- `.vystak/secrets-state.json` — per-secret: `{pushed_at, hash_prefix,
  last_rotated_at}`. Used by subsequent `apply` to decide skip-vs-push.
- `.vystak/identities-state.json` — UAMI resource IDs for auto-created
  identities. Used by `destroy` to know what to clean up.

## User surface

### Python — minimal

```python
import vystak as ast

agent = ast.Agent(
    name="hello",
    model=ast.Model(...),
    secrets=[ast.Secret(name="ANTHROPIC_API_KEY")],
)
```

No Vault declared → env passthrough (today's behavior). Zero migration
for existing examples.

### Python — vault-backed, with workspace-scoped secret

```python
azure = ast.Provider(name="azure", type="azure",
                     config={"resource_group": "vystak-rg"})
vault = ast.Vault(name="vystak-vault", provider=azure, mode="deploy",
                  config={"vault_name": "vystak-vault"})

agent = ast.Agent(
    name="assistant",
    model=ast.Model(name="sonnet", provider=anthropic,
                    model_name="claude-sonnet-4-6"),
    secrets=[ast.Secret(name="ANTHROPIC_API_KEY")],
    workspace=ast.Workspace(
        type="persistent",
        secrets=[ast.Secret(name="STRIPE_API_KEY")],
        filesystem=True,
    ),
    platform=ast.Platform(name="aca", type="container-apps", provider=azure),
)
```

Vystak deploys one ACA app with two containers; LLM in the agent cannot
reach `STRIPE_API_KEY`.

### YAML equivalent

```yaml
providers:
  azure:
    type: azure
    config:
      resource_group: vystak-rg
  anthropic:
    type: anthropic

vault:
  name: vystak-vault
  provider: azure
  mode: deploy
  config:
    vault_name: vystak-vault

platforms:
  aca:
    type: container-apps
    provider: azure

models:
  sonnet:
    provider: anthropic
    model_name: claude-sonnet-4-6

agents:
  - name: assistant
    model: sonnet
    secrets:
      - name: ANTHROPIC_API_KEY
    workspace:
      type: persistent
      secrets:
        - name: STRIPE_API_KEY
      filesystem: true
    platform: aca
```

A new top-level `vault:` key in the multi-loader; a single declaration
per deployment (no multi-vault support in v1).

### Tool code convention

Tools that live in the workspace container read secrets via
`vystak.secrets.get`:

```python
from vystak.secrets import get
import httpx

def charge_card(card_id: str, amount: int) -> dict:
    api_key = get("STRIPE_API_KEY")
    response = httpx.post(
        "https://api.stripe.com/v1/charges",
        data={"source": card_id, "amount": amount},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    response.raise_for_status()
    return {"charge_id": response.json()["id"]}
```

Discipline (not enforced in v1): do not log the response text verbatim,
do not return exception strings that contain request details, do not put
the secret in a tool return value or prompt.

## Validation and error messages

At load time, the schema and cross-object validators produce actionable
errors:

- `Vault(mode='external') requires config identifying the existing vault` —
  when external mode declared without identifier.
- `Workspace declares secrets but agent.platform.provider is not Azure. v1 only supports workspace-scoped secrets on Azure (ACA lifecycle:None). See follow-up spec for HashiCorp Vault on Docker.` — cross-object check in the loader.
- `Secret 'X' declared in agent tree but not present in .env and not in the vault. Either set it in .env, run 'vystak secrets set X=...', or remove the reference.` — at secret-sync phase in apply.
- `KV role assignment failed for UAMI 'X' on secret 'Y'. This is usually an RBAC propagation delay — retry in 30s.` — with automatic backoff retry built in.

## Testing

- Schema validator tests for each error case above.
- Provisioning graph integration tests that assert: with a two-secret
  agent-and-workspace declaration, the emitted ACA revision has exactly
  two UAMIs with `lifecycle: None`, each granted `get` on exactly one KV
  secret, with per-container `env[].secretRef` scoped accordingly.
- Deploy end-to-end test (marked `docker` or `azure`, opt-in) that
  deploys a skeleton agent, exec's into the agent container, hits the
  ACA token endpoint, and asserts no tokens are issued.
- Canary-value test: provision with a fixture secret name bound to a
  recognizable sentinel value, run codegen, grep every generated
  artifact for the sentinel. Assert never found.

## Migration

- All existing examples load unchanged (no Vault declared → env
  passthrough preserved).
- New examples demonstrating vault-backed mode added under
  `examples/azure-vault/` (one-agent) and `examples/azure-workspace-vault/`
  (agent + workspace sidecar).
- Changelog and README update call out the new CLI subcommand.

## Open questions for implementation

- **ACA `lifecycle: None` GA status.** Documented under API version
  `2024-02-02-preview` as of 2026-02-13. Before merge, verify GA status
  in target regions. If still preview in some regions, the provider logs
  a warning and proceeds — the preview behavior is stable per Microsoft
  Q&A threads.
- **KV role assignment propagation delay.** Up to 5 minutes in practice.
  Apply retry strategy with 30s intervals for up to 10 minutes.
- **Per-container `env[].secretRef` name collision.** ACA secret names
  must match the regex `[a-z0-9][a-z0-9-]*`. Provider normalizes
  `MINIMAX_API_KEY` → `minimax-api-key` for the ACA secret name, keeps
  the original for the env var name.

## Follow-on specs (named, not written)

- `2026-05-XX-hashicorp-vault-backend-design.md` — Hashi Vault for Docker
  and Azure, using per-container AppRole token files.
- `2026-06-XX-workspace-orchestrator-design.md` — Workspace as top-level
  resource, multi-agent sharing, per-user / per-session / per-user-project
  scope, orchestrator + warm pool topology.
- `2026-??-XX-exec-workspace-design.md` — `Workspace.exec=True` with a
  container-only sandbox profile and pluggable sandbox backend (E2B,
  Daytona, Firecracker).
- `2026-??-XX-secret-client-sdk-design.md` — Typed HTTP / DB clients with
  redacted exceptions and telemetry scrubbers, replacing the thin
  `vystak.secrets.get` with a richer SDK that makes secret leakage harder.

## Rationale for cut decisions

**Why Azure-only in v1?** The secret isolation property requires
platform-specific plumbing (ACA `lifecycle: None` + per-container
`secretRef`). Supporting Docker + Hashi Vault means building a second,
differently-shaped isolation pipeline (Vault Agent sidecar, per-container
AppRole). Doubling the implementation cost for a second backend that
serves local dev is hard to justify before the primary (Azure prod) path
is proven.

**Why no `Principal` schema?** A `Principal` object without runtime
identity sharing across deployables is just a named box for one UAMI.
Auto-creation gets the same result with less schema surface. When the
orchestrator spec introduces real cross-deployable identity sharing,
`Principal` can be promoted to a first-class concept without breaking
v1 users (auto-created becomes implicit-default).

**Why no `SecretClient` SDK in v1?** Typed clients and redaction are
defense-in-depth over the primary guarantee (per-container env scoping).
The primary guarantee carries the security story. SDK ergonomics improve
discipline; they're valuable, but shipping them requires solving:
HTTP-library-of-choice (httpx vs. requests), DB-library coverage
(asyncpg / psycopg / sqlalchemy), observability-framework integration
(OTel / LangSmith / Arize), and exception-redaction regex maintenance.
Each is a real chunk of work. Ship the schema + topology first;
layer SDK on when the topology has users.

**Why no multi-agent workspaces / exec / per-user scope?** All three are
valuable, all three expand the spec's implementation cost by 2-5x, and
all three have non-trivial design questions remaining (topology
auto-selection, sandbox backend choice, orchestrator architecture,
templated Vault policies for per-user). Each earns its own spec.
