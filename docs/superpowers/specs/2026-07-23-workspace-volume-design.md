# Workspace Volumes — first-class persistence for Docker and Azure

**Date:** 2026-07-23
**Status:** Approved design, pending implementation plan
**Supersedes:** the `Workspace.persistence` string field (kept as a back-compat alias)
**Related:** `2026-04-22-workspace-compute-design.md` (Docker workspaces),
`2026-04-23-aca-workspace-compute-design.md` (Azure two-app workspaces)

## Context

Workspace runtime data (`/workspace`) is currently governed by a single string
field, `Workspace.persistence: "volume" | "bind" | "ephemeral"`, interpreted
independently by each provider:

- **Docker** — named volume `vystak-<agent>-workspace-data`, bind mount, or tmpfs.
- **Azure (ACA)** — Azure Files SMB share via ACA environment storage;
  `bind` rejected by the multi-loader; single replica pinned.

Problems this design addresses:

1. **Performance (Azure).** SMB is slow for git/npm/pip-heavy workloads
   (small-file metadata ops). ACA cannot mount managed disks; the only
   faster option is Azure Files **NFS** (premium tier, VNet required).
2. **Durability & lifecycle.** Retention is implicit ("volume survives unless
   `--delete-workspace-data`"); there is no snapshot/restore/backup story.
3. **Sharing & scale.** Strictly 1 agent : 1 workspace : 1 data volume.
   Nothing can be referenced by name, so nothing can be shared.
4. **Portability & parity.** The same string means different things per
   provider; there is no way to move workspace data between providers.

## Design overview

Promote workspace persistence to a first-class **named `Volume` object** in
the multi-doc schema (a peer of `providers`, `platforms`, `vault`). Workspaces
reference a volume by name. The volume declares *intent*; each provider maps
it to a concrete backend. On top of this, provider-neutral
**snapshot / restore / clone** commands are built entirely on the existing
SSH-RPC channel.

Delivered in two phases:

- **Phase 1** — `Volume` schema object, provider backends (incl. Azure NFS),
  sharing, retention, back-compat mapping.
- **Phase 2** — `vystak workspace snapshot | restore | clone`.

## Schema

New model `Volume(NamedModel)` in `vystak/schema/volume.py`; new top-level
`volumes:` section in `multi_loader`:

```yaml
volumes:
  - name: team-code
    mode: persistent        # persistent | ephemeral | bind   (default: persistent)
    performance: standard   # standard | premium              (default: standard)
    retention: retain       # retain | delete                 (default: retain)
    path: ~/code            # bind mode only; required for bind, rejected otherwise
```

`Workspace` gains an optional reference:

```yaml
workspace:
  volume: team-code
```

### Provider mapping

| `mode` + `performance` | Docker | Azure (ACA) |
|---|---|---|
| `persistent` + `standard` | named Docker volume | Azure Files **SMB** share (today's behavior) |
| `persistent` + `premium` | named Docker volume (tier ignored — already native speed) | Azure Files **NFS** share (premium FileStorage account, VNet-injected ACA env) |
| `ephemeral` | tmpfs | no volume mount (EmptyDir semantics) |
| `bind` | host bind mount of `path` | **rejected** by multi-loader (existing check, moved to volume validation) |

### Naming

- Named volumes: Docker volume / Files share `vystak-volume-<name>`.
- **Implicit volumes** (back-compat, below) keep the current
  `vystak-<agent>-workspace-data` name so existing deployments do not orphan
  their data.

### Back-compat

`Workspace.persistence` (and the older legacy `type:` mapping) remain valid
and map to an **implicit per-agent volume**:

- `persistence: volume` → implicit `Volume(mode=persistent)`
- `persistence: bind` + `path` → implicit `Volume(mode=bind, path=...)`
- `persistence: ephemeral` → implicit `Volume(mode=ephemeral)`

Declaring both `workspace.volume` and `workspace.persistence` is a validation
error. This follows the same legacy-alias pattern as
`WorkspaceType → persistence` (`_apply_legacy_type`).

### Validation (multi_loader)

- `workspace.volume` must reference a declared volume (same named-reference
  resolution as channels/providers).
- `mode: bind` requires `path`; any other mode rejects `path`.
- `mode: bind` rejected when the platform is container-apps (relocated from
  `_validate_workspace_platform_persistence`).
- `performance: premium` on container-apps requires a VNet-injected ACA
  environment — validated at provider plan time with an actionable message
  (see Azure specifics).

### Hash tree

The resolved volume config (mode, performance, backend identity) joins
`AgentHashTree` — changing a workspace's volume changes deploy identity.
Retention does **not** contribute to the hash (it only affects destroy).

## Sharing semantics

Two (or more) workspaces referencing the same volume name mount the same
Docker volume / Files share. That is the same-provider sharing story.

- **Concurrency is the user's responsibility** — SMB and NFS both permit
  multi-mount; Vystak adds no locking. Documented plainly.
- Azure keeps 1 replica per workspace app; sharing is *across agents*, not
  across replicas.
- Cross-provider "sharing" is `clone` (Phase 2), never a live mount.

## Lifecycle & retention

- `vystak destroy` of one agent never deletes a volume still referenced by
  another deployed agent.
- A volume is removed only when the last referencing agent is destroyed
  **and** either `retention: delete` is set or `--delete-workspace-data`
  is passed. Default `retention: retain` preserves today's behavior.
- Implicit volumes inherit the same rules (retain by default).

## Phase 2 — snapshot / restore / clone

Built entirely on the existing `vystak-rpc` SSH subsystem; no new provider
surface.

- **`vystak workspace snapshot <agent> [--tag <t>]`** — runs
  `exec.run("tar -czf - -C /workspace .")`, streaming stdout through the
  RPC's `$/progress` chunks. Archive + manifest JSON (source volume, agent,
  timestamp, vystak version) written to the snapshot backend:
  - Docker: `.vystak/snapshots/<volume>/<timestamp>[-<tag>].tar.gz`
  - Azure: Blob container `vystak-snapshots` in the deploy's storage account.
- **`vystak workspace restore <agent> <snapshot>`** — uploads the archive via
  chunked base64 `fs.appendFile`, then `exec.run("tar -xzf ...")`. Refuses a
  non-empty `/workspace` without `--force`. (The RPC has no exec-stdin
  streaming; chunked-write-then-extract avoids extending the protocol.)
- **`vystak workspace clone <src-agent> <dst-agent>`** — snapshot + restore,
  across agents or across providers. The tar.gz + manifest is the
  provider-neutral portability format.

Documented caveat: snapshots are **not crash-consistent** if taken during
active writes.

## Azure specifics

- **NFS path** (`performance: premium`): requires a premium **FileStorage**
  storage account and a VNet-injected ACA environment. The provider checks
  both preconditions during plan/apply and fails with an actionable message
  (what is missing, how to enable it) instead of ARM's opaque
  parent-resource error. This also fixes the existing unfriendly failure in
  `AzureFilesShareNode` when the storage account is absent.
- SMB remains the zero-prerequisite default.
- Snapshot blobs reuse the deploy's existing storage account.

## Error handling

- Missing storage account / non-VNet environment → actionable plan-time error.
- `restore` into non-empty workspace → error, `--force` to override.
- `snapshot`/`restore` with no reachable workspace (stopped app, cold start)
  → surfaced RPC/SSH error with retry hint (ACA cold start ~30–60s).
- Destroying a shared volume while another agent references it → skipped with
  an informational message naming the remaining referents.

## Testing

- **Unit:** `Volume` model + validators; multi-loader reference resolution and
  bind/platform rejection; Docker node volume-name mapping (named vs
  implicit); Azure share node SMB/NFS mapping and precondition errors; hash
  tree contribution.
- **Release matrix:** extend V12 with (a) a shared-volume cell — two agents,
  one volume, write from one / read from the other; (b) a
  snapshot → destroy → restore → verify cell.
- **Examples** (definition of done): new `examples/docker-shared-volume/`
  (two agents sharing one named volume); `premium` variant added to
  `examples/azure-workspace-vault/`.

## Explicitly out of scope

- Wiring workspace tools into the agent template
  (`app_factory.py` `TODO(later-phase)`) — separate effort; until it lands
  this design pays off at the CLI/infra surface.
- Live multi-replica or cross-provider shared filesystems.
- Ephemeral-with-auto-snapshot backend (future `mode` addition; the schema
  leaves room).
- Scale-to-zero; human SSH on Azure.
- Snapshot scheduling/automation (manual commands only in Phase 2).
