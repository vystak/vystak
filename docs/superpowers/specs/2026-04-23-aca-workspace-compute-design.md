# ACA Workspace Compute — Design

**Date:** 2026-04-23
**Status:** Approved (tactical port of Spec 3 to Azure Container Apps)
**Depends on:**
- `2026-04-22-workspace-compute-design.md` (Docker implementation)
- `2026-04-19-secret-manager-design.md` (vault + workspace principal model)
- `2026-04-20-hashicorp-vault-backend-design.md` (HCL patterns, referenced only)

## Goal

Port the Docker workspace compute unit to Azure Container Apps with minimal
invention. Agent and workspace run as two separate Container Apps in the same
Environment, talking SSH + JSON-RPC 2.0 over internal DNS.

"Tactical" means: reuse the Docker-side Dockerfile generator, the
`vystak-workspace-rpc` subsystem, the LangChain adapter's generated
`builtin_tools.py`/`workspace_client.py`, and the existing `ACAAppNode` agent
path. Add Azure-specific provisioning for image push, SSH key storage,
persistent volume, and the workspace app itself.

## Topology

```
ACA Environment (shared)
├── <agent>             app — external ingress 443 → agent FastAPI
│                              UAMI → Key Vault (user + SSH client keys)
└── <agent>-workspace   app — internal  ingress 22  → sshd subsystem
                              UAMI → Key Vault (SSH host key + auth client pub)
                              Azure Files mount at /workspace (persistence=volume)
```

Both apps share the same ACA Environment so internal DNS works without VNet
integration.

## New provisioning nodes

All in `packages/python/vystak-provider-azure/src/vystak_provider_azure/nodes/`.

| Node | Responsibility |
|---|---|
| `AzureWorkspaceSshKeygenNode` | Generate 2 keypairs via local throwaway alpine (reuses the Docker keygen path). Push 4 values to Azure Key Vault as named secrets. |
| `AzureFilesShareNode` | Create or look up the Azure Files share for `persistence: volume`. Idempotent. |
| `ACAEnvStorageNode` | Register the Files share as an ACA Environment storage mount. One per share; shared across any apps in the same environment. |
| `ACAWorkspaceAppNode` | Deploy the workspace ACA app. Internal TCP ingress 22. Mounts the Files share at `/workspace`. References the 4 SSH-key Key Vault secrets via `secretRef`. Applies workspace-role UAMI. |

## Reused 1:1

- `ResourceGroupNode`, `LogAnalyticsNode`, `ACRNode`, `ACAEnvironmentNode`, `AzureKeyVaultNode`, `UAMIKeyVaultGrantNode`, `AzureSecretSyncNode`
- `ACAAppNode` — agent side; already wires model secrets via `secretRef`, UAMI identity, `lifecycle: None`
- `vystak-workspace-rpc` — unchanged (stdlib-only, runs in any base image)
- `vystak-adapter-langchain` generated `builtin_tools.py` + `workspace_client.py` — unchanged
- `generate_workspace_dockerfile` from `vystak-provider-docker` — reused for workspace image content. Image is built locally via Docker, tagged `<acr>.azurecr.io/vystak-<agent>-workspace:<hash>`, pushed to ACR, then referenced by the workspace app.

## SSH key delivery — `secretRef` + shim

Key Vault secret names (dashes, not slashes — KV secrets don't allow `/`):

| KV secret | Consumer | Env var |
|---|---|---|
| `vystak-workspace-ssh-<agent>-client-key` | agent | `VYSTAK_SSH_CLIENT_KEY` → `/vystak/ssh/id_ed25519` (0600) |
| `vystak-workspace-ssh-<agent>-host-key-pub` | agent | `VYSTAK_SSH_KNOWN_HOSTS_PUB` → `/vystak/ssh/known_hosts` (0444) |
| `vystak-workspace-ssh-<agent>-host-key` | workspace | `VYSTAK_SSH_HOST_KEY` → `/etc/ssh/ssh_host_ed25519_key` (0600) |
| `vystak-workspace-ssh-<agent>-client-key-pub` | workspace | `VYSTAK_SSH_AUTHORIZED_KEYS` → `/etc/ssh/authorized_keys_vystak-agent` (0444) |

The existing `entrypoint-shim.sh` is extended: after sourcing `secrets.env`
(for user-declared secrets), inspect a list of `VYSTAK_SSH_*` env vars; for
each one set, write the value to the mapped path with the mapped perms, then
`unset` the env var. Then exec the main process.

Rationale: `unset`ing clears the var from the current shell's environ before
`exec` clones it into the main process. The main process's `/proc/<pid>/environ`
no longer contains the key. Not perfect (the secret briefly lived in the ACA
app's revision config as a `secretRef`, which is itself backed by Key Vault),
but equivalent to how user API keys already flow through `secretRef`.

## Persistence

| mode | Azure mapping |
|---|---|
| `volume` | Azure Files share mounted at `/workspace` via ACA Environment storage reference. Share name: `vystak-<agent>-workspace-data`. |
| `ephemeral` | ACA's built-in `EmptyDir`-equivalent ephemeral volume at `/workspace`. |
| `bind` | Validation error at schema load time: *"persistence: bind is not supported on ACA — use volume or ephemeral"*. |

The Azure Files share survives across workspace revisions and is only deleted
by `vystak destroy --delete-workspace-data`.

## Networking

Workspace app ingress:
- `external: false` (only reachable from within the ACA Environment)
- `transport: tcp`
- `targetPort: 22`
- `exposedPort: 22`

Internal FQDN: `<workspace-app-name>.internal.<env-default-domain>`. The agent
provider computes this at deploy time and sets it as `VYSTAK_WORKSPACE_HOST`
on the agent app — exactly mirroring how `DockerAgentNode.set_workspace_context`
works today.

## Scale

Workspace: `minReplicas: 1, maxReplicas: 1`. Always-warm, no KEDA.

Multiple replicas would fight over the Files share and break SSH session
affinity with the agent (the agent holds a persistent SSH connection; a second
replica would be an invisible twin). Sharding or sticky sessions are out of
scope.

Agent: inherits existing scale rules (currently also 1:1).

## Destroy semantics

| Flag | Behavior |
|---|---|
| *(default)* | Deletes agent ACA app + workspace ACA app. Preserves Azure Files share. |
| `--delete-workspace-data` | Also deletes the Azure Files share. |
| `--keep-workspace` | Leaves the workspace ACA app running. |
| `--include-resources` | Plus everything: ACA env, ACR, KV, RG. |

## Schema changes

None to `Workspace`. Validation extension:
- `multi_loader.py` cross-object validator: when `agent.workspace.persistence == "bind"` and `agent.platform.type == "container-apps"`, raise
  `ValueError("persistence: bind is not supported on ACA — use volume or ephemeral")`.

## What doesn't change

- `Workspace` schema — reused 1:1
- `vystak-workspace-rpc` package — reused 1:1
- `vystak-adapter-langchain` generated code (builtin_tools, workspace_client) — reused 1:1
- `vystak secrets rotate-ssh <agent>` CLI — works across vault backends unchanged (node will dispatch on vault type)

## Explicitly out of scope

- ACA init containers (decided against in SSH delivery question — env-var path reuses existing primitives)
- Scale-to-zero / KEDA-based scaling for workspaces
- Multi-replica workspace (shared-fs races — future work)
- Human SSH access (`ws.ssh=True`) on Azure — the Docker code binds host port; ACA TCP ingress would need to be external, exposing SSH publicly. Skipped for tactical.
- Azure Key Vault CSI driver integration — requires AKS, not available on ACA
- Cross-region workspaces, multi-environment deploys

## Validation / test plan

Each phase ends with a commit and a passing unit-test slice. End-to-end
validation is opt-in (needs Azure credentials):

1. `uv run vystak plan --file examples/azure-workspace-compute/vystak.yaml` — shows new nodes in the plan output.
2. `uv run vystak apply --file examples/azure-workspace-compute/vystak.yaml` against a real Azure subscription — deploys, checks both apps running.
3. POST to the agent's ingress URL with a prompt that requires `fs.writeFile` + `exec.run` — verifies end-to-end RPC over internal TCP ingress.
4. `vystak destroy --file examples/azure-workspace-compute/vystak.yaml --delete-workspace-data` — verifies clean teardown including the Files share.

## Known risks

- **ACA internal TCP ingress + SSH idle timeout:** ACA ingress has an idle connection timeout (default ~240s). `asyncssh` keepalives must be enabled on the agent-side client. If absent, long-idle sessions get RST'd and the next `invoke()` has to reconnect. Acceptable; client already handles reconnect.
- **Azure Files share creation race:** `AzureFilesShareNode` is idempotent but the storage account creation (if it doesn't exist) is not part of this design. Assumes the user provides a storage account in `platform.config.storage_account` or we fail validation early.
- **First-deploy cold start:** workspace app going from 0→1 replica takes ~30–60s. The agent's first RPC will sit in SSH connect retry for up to ~60s; acceptable but worth noting.
