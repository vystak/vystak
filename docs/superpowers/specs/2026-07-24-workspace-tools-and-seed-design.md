# Workspace Tools + Seed Folders — finishing the workspace implementation

**Date:** 2026-07-24
**Status:** Approved design, pending implementation plan
**Related:** `2026-04-22-workspace-compute-design.md` (Docker workspaces),
`2026-04-23-aca-workspace-compute-design.md` (Azure two-app workspaces),
`2026-07-23-workspace-volume-design.md` (named volumes, Phase 1 shipped)

## Context

Workspace infrastructure fully provisions on both providers (image, sshd
`vystak-rpc` subsystem, key distribution, `VYSTAK_WORKSPACE_HOST`, named
volumes) — but the agent runtime never consumes it:
`_vystak/runtime/app_factory.py` line ~96 pins `workspace_tools: list[Any] = []`
behind a `TODO(later-phase)`. The LLM cannot call `fs`/`exec`/`git` at all.
Two secondary gaps block or degrade the path:

1. **Default-path `known_hosts` is never assembled** (test_plan.md gap #2):
   the agent container gets `/vystak/ssh/id_ed25519` and
   `/vystak/ssh/host_key.pub`, but no `known_hosts`, so
   `asyncssh.connect` cannot verify the workspace host — V11 fails on
   non-Vault deploys.
2. **The canonical `WorkspaceRpcClient` exists only as generated copies**
   under `examples/*/.vystak/` — violating the repo's no-codegen principle
   (components are real importable modules).

Additionally, users need a way to pre-load files into a workspace. This
spec adds **seed folders**: a `workspaces/<workspace-name>/` directory in
the project that is copied into `/workspace` on container start.

## Design overview

Four coordinated changes:

1. `_vystak/runtime/workspace_client.py` + `_vystak/runtime/workspace.py`
   (`build_workspace_tools`) — real managed modules wired into
   `app_factory`.
2. Default-path `known_hosts` assembly in the Docker agent node.
3. Seed folders: image-staged at `/vystak/seed/`, copied into `/workspace`
   by the container entrypoint with **copy-if-absent** semantics.
4. A V11 release cell + example proving the path end-to-end without an LLM.

## 1. Runtime workspace tools

### Modules (managed — refreshed by `vystak update`)

- **`_vystak/runtime/workspace_client.py`** — the canonical
  `WorkspaceRpcClient` (promoted from the generated copies): asyncssh, one
  persistent connection, `create_process(subsystem="vystak-rpc")` per
  call, `invoke(method, **params)` (single-shot JSON-RPC 2.0, skips
  `$/progress`), `invoke_stream(method, **params)` (yields progress
  chunks then result). Constructor keyword-only:
  `host, port=22, username="vystak-agent", client_keys, known_hosts`.
  Accepts key material as paths **or** inline strings (asyncssh supports
  both) so one class serves both providers.
- **`_vystak/runtime/workspace.py`** — `build_workspace_tools(agent) ->
  list[Any]`, following the `subagents.py`/`mcp.py` module pattern:
  - Returns `[]` when `agent.workspace is None` or
    `VYSTAK_WORKSPACE_HOST` is unset.
  - Lazy optional dependency: if `asyncssh` fails to import, log a
    warning and return `[]` (the `mcp.py` degradation pattern).
  - Connection resolved lazily on first tool call; reconnect on dropped
    connection (ACA idle-timeout resilience).
  - Tool errors are returned as strings, never raised, so the LLM turn
    survives.

### SSH material resolution (cross-provider)

A factory in `workspace.py` picks the delivery shape:

- **Docker (file paths):** `client_keys=["/vystak/ssh/id_ed25519"]`,
  `known_hosts="/vystak/ssh/known_hosts"` — used when those files exist.
- **Azure (inline env material):** `VYSTAK_SSH_CLIENT_KEY` (private key
  PEM) and `VYSTAK_SSH_KNOWN_HOSTS_PUB` (host public key) secretRef env
  vars — used when set; the factory builds the known-hosts entry
  `f"{host} {pubkey}"` and passes material inline to asyncssh.

### Tool set (matches the validated prototype `builtin_tools.py`)

| LLM tool | RPC method | Notes |
|---|---|---|
| `read_file` | `fs.readFile` | |
| `write_file` | `fs.writeFile` | |
| `edit_file` | `fs.edit` | returns unified diff |
| `list_dir` | `fs.listDir` | |
| `run` | `exec.run` | via `invoke_stream`; returns combined streamed output + exit code |
| `shell` | `exec.shell` | via `invoke_stream` |
| `git_status` | `git.status` | |
| `git_diff` | `git.diff` | |
| `git_commit` | `git.add` + `git.commit` | stages given paths then commits |

Remaining RPC methods (`fs.mkdir`, `fs.move`, `tool.invoke`, …) are
deliberately deferred — trivial additions once the pattern is in.

### Wiring

`app_factory.py`: replace the TODO block with
`workspace_tools = build_workspace_tools(agent)` and include
`workspace_tools` in the tool list at **both** `build_graph` call sites
(initial build and the lifespan MCP rebuild — omitting the second
silently drops the tools whenever MCP servers attach).

`asyncssh` is added to **`_vystak/requirements.txt`** (managed) — not the
user-owned `requirements.txt` — so `vystak update` delivers it to
existing projects.

## 2. Default-path `known_hosts` fix

`DockerAgentNode` (default path), at provision time — it already knows
`workspace_host` and the keygen output dir `.vystak/ssh/<agent>/`:

- Write `.vystak/ssh/<agent>/known_hosts` with content
  `f"{workspace_host} {host_key_pub_content}"` (idempotent overwrite —
  the host key is stable across applies; keygen skips existing keys).
- Bind-mount it read-only to `/shared/ssh/known_hosts` alongside the
  existing `id_ed25519` / `host_key.pub` mounts (the `/vystak/ssh`
  symlink already exposes it at the canonical path).

Vault path is untouched — the vault-agent sidecar already renders
`known_hosts`. This closes test_plan.md gap #2; V11 becomes passable on
the default path.

## 3. Seed folders — `workspaces/<workspace-name>/`

Convention over configuration, mirroring the existing `tools/` folder. No
schema change.

- **Source:** `workspaces/<ws.name>/` in the project dir (e.g.
  `workspaces/coder-ws/`). Absent folder → no seeding, zero behavior
  change.
- **Staging:** both image builders (`DockerWorkspaceNode.provision` and
  Azure `ACAWorkspaceAppNode._build_and_push_image`) copy the folder into
  the build context as `seed/`; the generated Dockerfile `COPY`s it to
  `/vystak/seed/` and `chown`s it to `vystak-agent`.
- **Application:** the container entrypoint copies
  `/vystak/seed/. → /workspace/` with **copy-if-absent** semantics
  (`cp -rn`): a seed file is copied only if the destination path does not
  exist. New seed files added later reach the workspace on the next
  apply (the image rebuilds); files modified inside the workspace are
  never clobbered. Deleting a seed file does not delete it from existing
  workspaces.
- **Entrypoint restructure:** the default path currently has no
  entrypoint (`CMD sshd` only). The Dockerfile generator gains a minimal
  always-present entrypoint script that (a) runs the seed copy when
  `/vystak/seed` exists, then (b) `exec`s the CMD. On the Vault path the
  existing secrets-wait shim runs first and chains into it (or the seed
  step is folded into the shim — implementation detail, single behavior:
  seed runs on both paths, after secrets are ready, before sshd).
- **Why not Dockerfile `COPY` straight to `/workspace`:** the volume
  mount shadows image content at runtime; Docker's empty-volume
  propagation is Docker-only and first-mount-only. Entrypoint-time copy
  is the only mechanism that behaves identically for Docker volumes,
  bind mounts, tmpfs, and Azure Files.
- **Hash:** seed-folder content **joins the workspace deploy hash**
  (file paths + content digests), scoped so workspaces without a seed
  folder keep byte-identical hashes. *Amended during implementation:*
  the original "no hash contribution, the rebuild carries changes"
  wording was self-contradictory — with hash-based change detection, a
  hash-exempt seed means `apply` reports "No changes" and never
  re-provisions, so pushed files would never arrive. (The `tools/`
  folder has this same latent gap — pre-existing, out of scope here.)
- **Azure `tools/` staging parity:** while touching the Azure image
  build, verify (and fix if broken) that it stages `tools/` the way the
  Docker node does — the generated Dockerfile references it
  unconditionally.

## 4. Testing & examples

- **Unit tests:**
  - `workspace.py`: builders return `[]` without a workspace / without
    env; each tool calls the right RPC method (mocked client); error
    strings, not exceptions; Docker-vs-Azure material resolution.
  - Docker agent node: `known_hosts` file written with correct content
    and mounted on the default path.
  - Dockerfile generator: seed COPY + entrypoint emitted when seed
    staged; unchanged output when no seed (snapshot-style assertions).
  - Azure workspace app: build context stages seed (and `tools/`).
- **Release cell (Docker, default path, `release_smoke`):**
  `test_workspace_tools_v11.py` — deploy one agent + workspace with a
  seed folder; assert:
  1. Seed file present in `/workspace` (`docker exec cat`).
  2. **V11 without an LLM:** `docker exec` into the *agent* container
     runs a Python one-liner using the shipped
     `_vystak.runtime.workspace_client` to call `fs.listDir` — proving
     keys, `known_hosts`, subsystem, and jail end-to-end with sentinel
     API keys.
  3. Copy-if-absent: modify the seeded file in the workspace, re-apply,
     assert the modification survives.
- **Example:** `examples/docker-workspace-tools/` — one agent, a
  `workspaces/<name>/` seed folder with a script the agent can `run`,
  README describing the built-in tools. (Definition-of-done per repo
  convention.)
- **Live Docker E2E** at the end of implementation, mirroring the
  volumes-phase verification.

## Out of scope

- Azure live testing (deferred until approved; code + unit tests only).
- A `workspace.seed:` schema field — the folder convention is the
  contract; a field can alias it later without breaking anything.
- Exposing the remaining RPC methods (`fs.mkdir`, `fs.move`,
  `tool.invoke`, `git.log`, …) as LLM tools.
- Per-call SSH process-spawn optimization (persistent RPC channel).
- Volume snapshots (Phase 2 of the volumes spec).
- Heartbeat/subagent interaction with workspace tools (works through the
  normal tool list; no special handling).
