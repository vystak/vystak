# Secret Manager — Simplification

**Status:** draft
**Date:** 2026-04-22
**Author:** anatoliy@ankosoftware.com (with Claude)
**Follow-up to:** `docs/superpowers/specs/2026-04-19-secret-manager-design.md`, `docs/superpowers/specs/2026-04-20-hashicorp-vault-backend-design.md`

## Summary

Make `Vault` entirely optional for workspace-bearing deploys. The per-container
isolation guarantee the branch was built around was always coming from the
container boundary, not from Vault itself — so platform-native secret delivery
(per-container `--env-file` on Docker, inline `configuration.secrets` on Azure
ACA) is sufficient to preserve it. Vault remains first-class for users who want
rotation, audit, or cross-deploy shared storage. The change is subtractive in
user-visible complexity and almost purely additive-and-gated in code.

The concrete outcome for the default case (`examples/docker-workspace-nodejs`):
5 containers + 6 volumes + `init.json` → 2 containers + 2 volumes + per-principal
env files. Cold start 15–30s → 2–3s. Same isolation.

## Motivation

The current `feat/secret-manager` branch requires a `Vault` declaration whenever
an `Agent` has a `Workspace`. The original justification was prompt-injection
defense: an LLM in the agent container must not be able to reach workspace-scoped
secrets like database credentials or third-party API keys. That justification
assumes Vault was providing the isolation.

It wasn't. The container boundary was. Two containers have two different process
trees, two different environment tables, and kernel namespace isolation. Nothing
the agent container runs can read the workspace container's env, regardless of
whether a Vault container is running on the side. Vault was the *delivery
mechanism* for the secret value — but the mechanism is interchangeable.

Every platform Vystak targets or plans to target (Docker, Azure ACA, Kubernetes,
AWS ECS, GCP Cloud Run) has a native primitive for "deliver this value into this
container's environment and no other's." The simplification replaces the
Vault-based delivery path with the platform-native one for the default case, and
leaves Vault as an opt-in feature for users who want its *other* properties.

Symptoms this addresses:
- `docker-workspace-nodejs` requires ~5 containers and 6 Docker volumes to run
  a conceptually-two-container agent.
- Cold start on a trivial Docker deploy is 15–30 seconds (Vault init, unseal,
  KV setup, sidecar template render, entrypoint shim wait).
- Every new user learning Vystak has to learn AppRole, Vault unseal, `init.json`
  sensitivity before they can ship a workspace.
- ~10 provisioning nodes for what is conceptually "run two containers."
- Cross-platform generalization is impractical: each future provider would have
  had to implement both a default path and a Vault path.

## Goals

- Make the `vault:` declaration optional on every provider.
- Preserve the per-container secret isolation invariant without Vault on the
  default path.
- Keep every existing Vault path — Hashi Vault on Docker, Azure Key Vault on
  ACA — working bit-for-bit unchanged when declared.
- Generalize: the design absorbs Kubernetes / AWS ECS / GCP Cloud Run later as
  per-provider implementation work, with no further schema change.
- Zero deletions of Vault-specific code on this branch. Vault features stay as
  first-class opt-ins.

## Non-goals

- **Hashi Vault on Azure ACA.** Separate follow-on spec.
- **Azure Key Vault on Docker.** Same.
- **SIGHUP-driven secret reload without container restart.** Same as the v1
  spec's non-goal.
- **Typed secret clients / redacted exceptions / telemetry scrubbers.** Still
  follow-on work.
- **Migration tooling to move secrets from Vault to `.env` automatically.**
  Manual — users opt out of Vault by updating `.env` and running
  `destroy --delete-vault && apply`.

## Architecture

### Invariant the schema guarantees

> Every `Secret` declared on a principal (`Agent`, `Workspace`, `Channel`)
> materializes only into that principal's container(s). Cross-principal access
> requires a deliberate schema change.

"Principal" = a container in the deploy graph. Agent, workspace (if declared),
and each channel are distinct principals, each with its own env scope. Channels
already deploy as their own container on Docker and their own ACA app on Azure,
so per-channel scoping falls out of existing provider code with no additional
work — regardless of Vault presence. The only new plumbing is for the
agent + workspace pair on a single platform.

### Delivery-mechanism matrix

| `Vault` declared? | Docker provider | Azure provider |
|---|---|---|
| No (default) | Per-container `--env-file=.vystak/env/<principal>.env` resolved from `.env` at apply | Inline `configuration.secrets[]` + per-container `env[].secretRef` |
| `type="vault"` (Hashi, opt-in) | Current sidecar path: Vault server + per-principal AppRole + Vault Agent sidecar + `/shared/secrets.env` + entrypoint shim | Rejected at plan time |
| `type="key-vault"` (Azure KV, opt-in) | Rejected at plan time | Per-principal UAMI + `keyVaultUrl` secretRef + `lifecycle: None` |

### Universal generalization

Every platform Vystak might target has a native primitive for per-container env
scoping:

| Platform | Default delivery | Opt-in secret store |
|---|---|---|
| Docker | Per-container `--env-file` | Hashi Vault sidecar (current) |
| Azure ACA | Inline `configuration.secrets[]` + `secretRef` | Azure KV + UAMI + `lifecycle:None` (current) |
| Kubernetes | Per-principal `Secret` + `envFrom` / `env[].valueFrom.secretKeyRef` | CSI driver or External Secrets Operator |
| AWS ECS Fargate | Task def `environment[]` + per-container scoping | Secrets Manager / SSM via `secrets[].valueFrom` |
| GCP Cloud Run / GKE | `--set-secrets=ENV=secret:version` / k8s `Secret` | GCP Secret Manager |

The invariant generalizes without schema change. Each new provider is
self-contained implementation work.

### SSH key delivery decoupled from Vault

The current branch pushes agent↔workspace SSH keys through Vault because Vault
was on the critical path. Decoupled:

| | Default path | Vault opt-in |
|---|---|---|
| Generation | `SshKeygenNode` at apply time | Same |
| Agent private key | Bind-mounted from `.vystak/ssh/<agent>/id_ed25519` | Vault Agent renders into `/shared/id_ed25519` (current) |
| Workspace `authorized_keys` | Bind-mounted from `.vystak/ssh/<agent>/authorized_keys` | Vault Agent renders into workspace's mount (current) |
| Rotation | `vystak secrets rotate-ssh <agent>` — regen into `.vystak/ssh/<agent>/`; container restart picks up new key | `vystak secrets rotate-ssh <agent>` — regen in-memory and push directly to Vault; no host file at any point; Vault Agent re-renders on next poll or forced restart |

On the default path, `.vystak/ssh/<agent>/` is chmod 600, inherits the existing
`.vystak/` gitignore, and the trust boundary is identical to `.env`. On the
Vault opt-in path, no SSH material ever touches host disk.

## Schema changes

### Validators removed

Three validators in `packages/python/vystak/src/vystak/schema/multi_loader.py`:

1. **Lines 118–129** — "workspace secrets on Docker requires Hashi Vault."
   Replaced by default `--env-file` delivery.
2. **Lines 130–136** — "workspace secrets on non-Azure, non-Docker provider
   rejected." Each provider implements per-container delivery natively;
   policing at load time is premature.
3. **Lines 139–155** — "Agent declares a workspace but no Vault is declared —
   Spec 1 requires Vault for SSH key storage." SSH keys move to a plain Docker
   volume / host file; Vault is no longer on the workspace critical path.

Total diff: ~40 lines deleted. Tests asserting these errors flip to assert
success on the default path.

### Validators kept

`_validate_vault_provider_pairing` — still enforces `Vault(type="key-vault")`
requires `provider.type="azure"` and `Vault(type="vault")` requires
`provider.type="docker"`. Opting into Hashi on Azure or KV on Docker are
separate follow-on specs.

### Models unchanged

Zero lines changed in any Pydantic model. `Secret`, `Vault`, `Workspace`,
`Agent`, `Channel`, `VaultType`, `VaultMode` all stay at their current shape.
**A user who was on this branch yesterday has zero breaking schema changes.**

### Before / after YAML

Before (required even for a trivial workspace):

```yaml
vault:
  name: vystak-vault
  provider: docker
  type: vault
  mode: deploy
  config: {}

agents:
  - name: assistant
    secrets:
      - name: ANTHROPIC_API_KEY
    workspace:
      secrets:
        - name: STRIPE_API_KEY
```

After (`vault:` block entirely optional):

```yaml
agents:
  - name: assistant
    secrets:
      - name: ANTHROPIC_API_KEY
    workspace:
      secrets:
        - name: STRIPE_API_KEY
```

Same isolation guarantee, delivered by per-container `--env-file` on Docker or
inline `configuration.secrets[].secretRef` on Azure ACA.

## Provider implementation changes

### Docker provider (`vystak-provider-docker`)

**Branching in `provider.py`:** `apply()` dispatches on `vault is not None`.

**Default graph (Vault is None):**

| Node | Purpose | Status |
|---|---|---|
| `NetworkNode` | Create `vystak-net` bridge | Existing |
| `DockerEnvFileNode` (×N principals) | Write `.vystak/env/<principal>.env` from declared secrets ∩ `.env`, chmod 600 | **New, ~50 lines** |
| `SshKeygenNode` (if workspace) | Generate keypair → `.vystak/ssh/<agent>/`, chmod 600 | Simplified from existing `WorkspaceSshKeygenNode` |
| `DockerAgentNode` | Run with `--env-file` + SSH bind mount | Modified: shim gated on `vault is not None` |
| `DockerWorkspaceNode` | Run with its own `--env-file` + `authorized_keys` bind mount | Modified: same gating |

**Vault graph (Vault is not None):** unchanged. Every existing node —
`HashiVaultServerNode`, `HashiVaultInitNode`, `HashiVaultUnsealNode`,
`VaultKvSetupNode`, `AppRoleNode`, `AppRoleCredentialsNode`,
`VaultSecretSyncNode`, `VaultAgentSidecarNode`, entrypoint shim injection —
runs bit-for-bit as it does today.

**Per-file modifications:**
- `provider.py`: ~30 lines of branching.
- `nodes/agent.py`, `nodes/channel.py`, `nodes/workspace.py`: ~10–15 lines each,
  gating shim + mount selection.
- `nodes/workspace_ssh_keygen.py`: ~20 lines — mutually exclusive paths.
  Default path (no Vault): write keypair to `.vystak/ssh/<agent>/`, chmod 600.
  Vault path: push to Vault only (current behavior); Vault Agent templates
  into `/shared` and no host file is written. This preserves the property
  that the Vault path's only sensitive host file is `.vystak/vault/init.json`.

**New:** `nodes/env_file.py` (~50 lines), `tests/test_node_env_file.py`,
`tests/test_default_path_integration.py` (docker-marked).

### Azure provider (`vystak-provider-azure`)

Smaller delta: the env-passthrough code path from the v1 spec already exists for
agent-only deploys. The confirmation/fix work is:

1. Verify `ACAAppNode` emits per-container `env[].secretRef` scoping with inline
   `configuration.secrets` when a workspace is present.
2. Wire workspace-container secrets if missing — expected ~20 lines.
3. Gate UAMI / grant / `lifecycle:None` nodes on `vault is not None`.

Vault-on-Azure path unchanged:
`ResourceGroupNode → LogAnalyticsNode → ACRNode → ACAEnvironmentNode →
VaultNode → IdentityNode → KvGrantNode → SecretSyncNode →
ACAAppNode(secretRef + lifecycle:None)`.

### CLI (`vystak-cli`)

All existing commands keep working:

| Command | No Vault | Vault declared |
|---|---|---|
| `secrets list` | Show declared + `.env` presence | Dispatch to KV or Vault (current) |
| `secrets push [--force]` | Write `.env` values into `.vystak/env/<principal>.env` | Dispatch to KV or Vault (current) |
| `secrets set NAME=VAL` | Not supported — error message directs user to edit `.env` directly (and run `vystak apply` to materialize) | Dispatch to KV or Vault (current) |
| `secrets diff` | `.env` vs `.vystak/env/*` vs declared | Dispatch to KV or Vault |
| `secrets rotate-approle <p>` | Rejected: "requires Vault(type=vault)" | Current |
| `secrets rotate-ssh <agent>` | Regen into `.vystak/ssh/<agent>/` | Regen + push to Vault |

`plan` output shows `EnvFiles:` on the default path; `Vault:` / `Identities:` /
`Grants:` only when Vault declared. Plus orphan-resource detection (see
Migration).

`destroy` default cleans up `.vystak/env/` and `.vystak/ssh/`. `--delete-vault`
behavior unchanged.

### LangChain adapter

`vystak-adapter-langchain/templates.py` currently emits the entrypoint shim
into generated agent Dockerfiles when the adapter detects a workspace. This
becomes conditional on Vault being declared in the agent's deploy tree.
~10 lines of gating.

## Security envelope

### Primary threat

Prompt injection can coerce an LLM's tools to exfiltrate any secret the tool's
process can reach. The defense must be topological (the value is not in the
agent's reach), not disciplinary.

### Isolation attacks — same defense, both paths

| Vector | Default | Vault |
|---|---|---|
| LLM prompts agent to `echo $STRIPE_KEY` | Blocked — not in env | Blocked — not in env |
| Read `/proc/self/environ` | Blocked — not present | Blocked — not present |
| Read workspace container memory | Blocked — kernel namespace isolation | Blocked — kernel namespace isolation |
| Read workspace's env file on host | Blocked — not mounted | Blocked — not mounted |
| Ask workspace via RPC to `exec.run("echo $STRIPE_KEY")` | **Tool-discipline issue** — workspace RPC must not expose arbitrary shell. Identical both paths. | Identical |
| Supply chain compromise of agent deps | Agent secrets leak; workspace untouched | Same |
| Supply chain compromise of workspace deps | Workspace secrets leak; agent untouched | Same |

### Azure-specific difference (the only real delta)

| Vector | Default (inline ACA) | Vault (KV + UAMI + lifecycle:None) |
|---|---|---|
| RBAC `Reader` on Container App reads ARM template | **Sees plaintext values** | Sees `keyVaultUrl` refs; needs KV RBAC for values |
| Container code calls IMDS / token endpoint | No UAMI → returns nothing | `lifecycle:None` blocks |
| Cross-container token fetch | N/A | Blocked by `lifecycle:None` |

ARM-template readability is the one place the default path is weaker on Azure.
Users whose compliance requires "secret values not visible to deploy-config
readers" opt into `Vault(type="key-vault")`. The opt-in path preserves the
property without taxing users without that requirement.

### Host compromise — Vault arguably worse

| Attacker capability | Default | Vault (Docker) |
|---|---|---|
| Read current secret values | `.vystak/env/*.env` — current only | `.vystak/vault/init.json` → root token → current + historical + write access |
| Read SSH keypair | `.vystak/ssh/<agent>/` — on host | Stored in Vault only, never on host |
| Persist after rotation | Needs fresh host access | Root token stable until explicit rotation |

Both paths chmod 600 + gitignored. Vault's blast radius on host compromise is
strictly larger for secret values; strictly smaller for SSH keys. The SSH-key
host file exists *only* on the default path — on the Vault path, SSH keys
live exclusively in Vault and are rendered by Vault Agent into the per-container
`/shared` volume.

### What Vault adds

| Feature | Default | Vault |
|---|---|---|
| Audit log of secret fetches | None | Yes (at fetch granularity, not process-read) |
| Rotation without redeploy | No (restart still needed — env is evaluated at start) | No (same) — but smoother workflow |
| Cross-deploy shared storage | Per-deploy `.env` | Single KV/Vault |
| Compliance: dedicated secret manager | No | Azure KV HSM / Vault audit log |
| Compliance: values not in deploy config (Azure) | No | Yes |

Each is a legitimate reason to opt in. None is *isolation*.

### Bottom line

The default path's primary isolation guarantee — "LLM in agent cannot reach
workspace secrets" — is identical to today's Vault-required path. Vault was
not adding to this invariant. Users who need the *other* properties Vault
provides opt in via the `vault:` block and get the existing implementation
unchanged. No user is forced into a weaker path; no user's primary threat model
changes.

## Migration

### Three user scenarios

| Situation today | After ship | Action needed |
|---|---|---|
| Has `vault:` declared, wants Vault features | Deploy identical | None |
| Has `vault:` declared because the validator forced it | Can remove `vault:`, next `apply` uses default path — ~10× faster cold start | Optional; release notes explain. Must `destroy --delete-vault` first to reclaim resources. |
| Fresh user, no existing deploy | Writes schema without `vault:`, gets default path | None |

### The one gotcha

A user with an active Vault-backed deploy who removes the `vault:` block.
`vystak plan` detects the delta and warns:

```
Vault:
  (removed from config)

Orphan resources detected:
  vystak-vault                      container — will remain
  vystak-vault-data                 volume — will remain
  vystak-<principal>-vault-agent    containers — will remain
  vystak-<principal>-approle        volumes — will remain
  vystak-<principal>-secrets        volumes — will remain

These are from a previous Vault-backed deploy. To clean up:
  vystak destroy --delete-vault
  vystak apply

To keep them during migration, proceed with 'vystak apply' — new default-path
containers will deploy alongside.
```

The apply proceeds with new default-path containers; the orphan Vault stack
sits idle until the user explicitly destroys it. Auto-destroying `init.json`
is too dangerous — unseal keys exist nowhere else.

### Tests that need updating

Grep for the error strings in the removed validators to find affected tests.
Estimated 5–10 across `test_multi_loader.py`, `test_multi_loader_vault.py`,
`test_multi_loader_workspace.py`, `test_examples.py`. Each flips from
expect-raise to expect-success-via-default-path.

### New tests

- `DockerEnvFileNode` unit tests: push, force, missing-secret reporting.
- Multi-loader: workspace without `vault:` loads and emits default-path graph.
- Docker integration (`-m docker`): deploy agent+workspace+secrets without
  Vault; exec into agent and assert workspace's secret absent from env.
- Azure: ACA revision with workspace+secrets and no Vault emits inline secrets
  + per-container `secretRef`.

### Example changes

| Example | Action |
|---|---|
| `examples/docker-workspace-vault/` | Unchanged — demonstrates Vault on Docker |
| `examples/azure-workspace-vault/` | Unchanged — demonstrates Vault on Azure |
| `examples/docker-workspace-nodejs/` | Update in place: drop `vault:` block, drop shim injection. Same two-container isolation, no Vault ceremony. Deploy 15–30s → 2–3s. |

### Release notes draft

> **Vault is now optional for workspaces.** Previously, deploying an `Agent`
> with a `Workspace` required declaring a HashiCorp Vault (on Docker) or an
> Azure Key Vault (on Azure). This is no longer required.
>
> Secrets declared on a workspace still land only in the workspace container's
> environment — the per-container isolation guarantee is unchanged. Delivery
> now uses platform-native mechanisms by default: per-container `--env-file`
> on Docker, inline `configuration.secrets` on Azure. Vault remains available
> as a first-class opt-in feature for rotation, audit logging, and
> cross-environment secret storage.
>
> **If you have a `vault:` block you don't need:** you can remove it. Run
> `vystak destroy --delete-vault && vystak apply` to migrate. Keeping the block
> works too — your deploy is unchanged.
>
> **SSH keys between agent and workspace** now live in `.vystak/ssh/<agent>/`
> by default (chmod 600, gitignored). Vault-stored SSH keys remain available
> when `vault:` is declared.

## Implementation sequencing

Four phases, each a separate PR, each green before the next starts:

**Phase 1 — Schema validators + Docker default path (single PR):** Remove three
validators, flip tests, add `DockerEnvFileNode`, branch `DockerProvider.apply()`,
gate shim injection, simplify SSH keygen, add docker-marked integration test.
Shipping together avoids a transient regression where configs load cleanly but
fail at provider plan time with a less-specific error.

**Phase 2 — Azure default path confirmation:** Verify multi-container
inline-secrets scoping, fix if missing, add unit test.

**Phase 3 — CLI + adapter:** Branch `secrets.py`, `plan.py`, `destroy.py`.
Gate adapter shim emission in `vystak-adapter-langchain/templates.py`.

**Phase 4 — Examples + docs:** Update `docker-workspace-nodejs`, READMEs,
release notes.

Phases 2 and 3 can be parallel after Phase 1.

## Risk register

| Risk | Mitigation |
|---|---|
| Azure no-Vault path incomplete for multi-container workspace | Phase 3 verification + fix if needed |
| LangChain adapter emits shim unconditionally | Gate in `templates.py`; ~10 lines |
| Orphan Vault resources on block removal | Plan-time warning; `destroy --delete-vault` is the documented migration |
| Host SSH key permission (UID mismatch bind mount) | `SshKeygenNode` writes files to `.vystak/ssh/<agent>/` with host UID/perms. Private key is bind-mounted read-only into the agent container at a staging path (e.g. `/vystak/ssh/id_ed25519.ro`). A one-line startup step in the agent container copies the file to `$HOME/.ssh/id_ed25519` and chmods 600 against the container's own UID before first SSH use. This avoids host-UID/container-UID matching entirely and satisfies SSH's strict 0600 requirement. Emitted by the LangChain adapter's workspace-bootstrap codegen. |
| `secrets diff` semantics | Defined: compare declared ∩ `.env` ∩ `.vystak/env/*`; never print values |
| Hash tree redeploys on toggle | Documented: adding/removing `vault:` is a redeploy trigger |

## Rationale for cut decisions

**Why not delete any Vault code?** The Vault implementation is well-tested and
works. Users who opt in deserve bit-for-bit stability. Gating is cheaper than
deletion+resurrection-later, and the Vault features (rotation, audit,
compliance) remain legitimate user needs.

**Why `--env-file` and not Docker Swarm `secrets:` / `/run/secrets/*` tmpfs?**
Keeping the SDK uniform (`vystak.secrets.get(name) == os.environ[name]`)
across every platform matters more than the modest blast-radius improvement
tmpfs gives on a compromised host. Users who want tmpfs-level delivery opt
into Vault. Requiring Swarm or Compose to get default-path behavior would also
complicate the "plain `docker run` just works" story.

**Why keep the three-cell topology matrix (no Vault / Hashi / KV) and not
collapse into two?** Hashi-on-ACA and KV-on-Docker are real wants for *some*
users but have non-trivial implementation costs (seal-key storage on ACA,
UAMI semantics on Docker). Collapsing prematurely adds complexity before
proven demand.

**Why not auto-destroy orphan Vault resources?** Unseal keys exist nowhere
else. Destroying them on an accidental config edit is irreversible. Explicit
action via `destroy --delete-vault` matches how the current destroy path
gates on the same flag.

**Why generalize the invariant now, before adding k8s / AWS / GCP providers?**
Without the simplification, every new provider would have had to implement
both a default path and a Vault path. With the simplification, each new
provider implements one default path using that platform's native secret
primitive, and opts into a store only if / when a user declares one. The
simplification is load-bearing for every future provider.

## Follow-on specs (named, not written)

- `2026-??-XX-kubernetes-provider-design.md` — k8s provider using `Secret`
  resource + `envFrom` for the default path; CSI driver / External Secrets
  for opt-in.
- `2026-??-XX-aws-ecs-provider-design.md` — AWS ECS/Fargate provider using
  task-def `environment[]` default + Secrets Manager / SSM opt-in.
- `2026-??-XX-gcp-cloud-run-provider-design.md` — GCP Cloud Run with Secret
  Manager.
- `2026-??-XX-hashi-on-azure-design.md` — run Hashi Vault on ACA with
  cloud-KMS auto-unseal for users who want one backend across clouds.
- `2026-??-XX-kv-on-docker-design.md` — Azure KV as an external secret store
  on Docker (requires `mode="external"` + Azure-auth config).
- `2026-??-XX-secret-client-sdk-design.md` — typed HTTP/DB clients with
  redacted exceptions, replacing the thin `vystak.secrets.get`.
