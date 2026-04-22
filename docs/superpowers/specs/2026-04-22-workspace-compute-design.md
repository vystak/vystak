# Workspace Compute Unit — Design

**Status:** draft
**Date:** 2026-04-22
**Author:** anatoliy@ankosoftware.com (with Claude)
**Follow-up to:** `docs/superpowers/specs/2026-04-19-secret-manager-design.md`,
`docs/superpowers/specs/2026-04-20-hashicorp-vault-backend-design.md`

## Summary

Promote `Workspace` from a declarative schema field to a real, deployed
compute unit. When an agent declares a workspace, vystak deploys a
second container alongside the agent container. Agent tools are no
longer inline Python running in the agent's LangGraph process — they
proxy, via an SSH-channel JSON-RPC 2.0 connection, to a long-running
workspace server that offers filesystem, exec, git, and user-defined
tool services as namespaced method groups (`fs.*`, `exec.*`, `git.*`,
`tool.*`). The workspace carries a persistent volume for user project
files, a user-selected base Docker image with declarative provisioning,
and — finally — consumes its own principal's secrets (from v1) in the
container that actually uses them.

This spec is Spec 1 of a three-part arc. Spec 2 adds a sandboxed exec
model for LLM-generated code; Spec 3 adds LSP bridging. Per-user /
per-session workspace scope is deferred to an orchestrator spec.

## Motivation

Three structural problems in the current codebase motivate this work.

**1. `Agent.workspace` is declarative-only.** The schema has a
`Workspace` type with fields like `filesystem`, `terminal`, `browser`,
`network`, `gpu`, `persist`, `path` — none of which affect runtime
behavior. The LangChain adapter ignores the field entirely. Every
example that sets `workspace=Workspace(...)` is sketching an
architecture that doesn't exist.

**2. The v1 secret-manager isolation story is half-finished.** The
HashiCorp Vault backend deploys a dedicated Vault-Agent sidecar and a
per-principal secrets volume for the workspace principal. But there is
no workspace container for those secrets to land in; the volume is
mounted into the agent container and the agent container's tool code
is the only thing that could consume `STRIPE_API_KEY`. Isolation is
real at the RBAC layer (workspace's AppRole can't read agent secrets)
but leaky at the process layer (tools running in the agent process can
reach whatever workspace secrets happen to be mounted). Spec 1 closes
that gap by giving workspace secrets a real compute unit to live in.

**3. Coding agents have nowhere to code.** The most interesting class
of agent — "read this repo, edit these files, run the tests" — needs
a persistent filesystem, a shell to run commands in, and git. Today
users have to roll these as tool functions in the agent container,
which means every apply rebuilds the agent image, every tool call
shares the agent's Python process and memory, and there is no
separation between "LLM reasoning" and "doing work." Workspace as a
compute unit fixes the layering.

## Goals

- A `Workspace` becomes a deployable container with its own lifecycle,
  network identity, and persistent filesystem.
- Users declare workspaces with a base image + list of provisioning
  commands + optional file drops. Vystak generates the Dockerfile and
  builds at apply time.
- Agent tools proxy via JSON-RPC 2.0 over SSH channels to the workspace
  container. The workspace exposes four namespaced services in v1:
  `fs.*`, `exec.*`, `git.*`, `tool.*`.
- Built-in filesystem, exec, and git services come free — users do not
  need to write `read_file.py` to get basic coding-agent capabilities.
- Persistent filesystem: Docker named volume by default; bind-mount to
  host path for live-edit coding; ephemeral for stateless exec.
- Integration with v1 secret-manager: workspace secrets materialize in
  the workspace container's env (not the agent's), fixing the v1
  isolation half-story. **SSH keys for the agent↔workspace channel
  are themselves stored in the same Vault** — all sensitive material
  flows through one audited subsystem.
- Optional human SSH access to the workspace (same sshd, different
  user) for debugging and interactive use.
- Backward compat: agents without `workspace=` continue to work
  unchanged. Existing examples with declarative-only workspaces that
  are not adopting Spec 1 features keep compiling.

## Prerequisites

**Declaring a workspace requires a `Vault` declaration.** Workspaces
rely on the Secret Manager from v1 (Hashi Vault on Docker, Key Vault
on Azure) for:
- Delivery of `Workspace.secrets` (existing v1 role), and
- Delivery of vystak-generated SSH keypairs that secure the
  agent↔workspace channel (new in Spec 1 — see "SSH key lifecycle"
  below).

Validator: `Agent.workspace is not None → Vault must be declared in
the same deployment.` The load-time error message directs users to
the v1 Secret Manager spec to add `vault: {type: ..., provider: ...}`
to their config.

**Why require Vault?** SSH keys are sensitive material. Rather than
invent a parallel storage mechanism (per-deployment Docker volumes or
per-deployment host files), v1 uses the one we already have. One
storage backend, one audit log, one rotation command, one security
boundary to reason about. On Docker, users who don't want to operate
Hashi Vault themselves can declare `Vault(type="vault", mode="deploy")`
and vystak stands it up — same as v1 already does. On Azure, Key
Vault is lightweight.

## Non-goals

- **Sandboxed execution of LLM-generated code.** Spec 2. v1 workspace
  is a regular container; an LLM given a `run_shell` tool can do
  whatever the container can do. Don't ship v1 as a safe way to run
  untrusted code; document it as "a dev environment for a trusted
  agent."
- **LSP bridging.** Spec 3. Port forwarding is on the SSH transport
  for free, but no language-server tooling is packaged in v1.
- **Per-user / per-session / per-project workspaces.** Deferred to an
  orchestrator spec. v1 is 1:1 agent → workspace.
- **Workspace shared across multiple agents.** Deferred. v1 is
  per-agent.
- **Hot tool reload.** Tool code changes require `vystak apply` (image
  rebuild). Bind-mount for `/workspace/` supports editing project
  files, but tool code lives in the image.
- **GUI applications in the workspace.** No X11/RDP/browser plumbing.
- **Disk quotas.** `max_size` from the legacy schema is dropped.

## Architecture

### Topology

```
┌────────────────── Network: vystak-net / ACA env ─────────────────────┐
│                                                                       │
│  ┌─ vystak-vault ──────────────────────────────────────────────────┐ │
│  │ HashiCorp Vault (or Azure KV)                                   │ │
│  │  - User secrets (ANTHROPIC_API_KEY, STRIPE_API_KEY, …)         │ │
│  │  - SSH key material (client-key, host-key, both pubs)          │ │
│  │    under _vystak/workspace-ssh/<agent>/*                        │ │
│  └─────────────────────────────────────────────────────────────────┘ │
│           │                                     │                     │
│           ▼                                     ▼                     │
│  ┌─ vystak-<agent>-agent-vault-agent ─┐ ┌─ vystak-<agent>-workspace-vault-agent ─┐│
│  │ Renders:                           │ │ Renders:                              │ │
│  │   /shared/secrets.env (env vars)   │ │   /shared/secrets.env (env vars)      │ │
│  │   /vystak/ssh/id_ed25519 (0400)    │ │   /shared/ssh_host_ed25519_key (0600) │ │
│  │   /vystak/ssh/known_hosts          │ │   /shared/authorized_keys_vystak-agent │ │
│  └───────────────┬───────────────────┘ └────────────┬──────────────────────────┘ │
│                  │                                   │                             │
│                  ▼                                   ▼                             │
│  ┌─ vystak-<agent> ───────────────┐   ┌─ vystak-<agent>-workspace ──────────────┐ │
│  │ Agent container (LangGraph)    │   │ Workspace container                     │ │
│  │  - Reads /vystak/ssh/ for      │   │  - User's base image + provision        │ │
│  │    client key + known_hosts    │   │  - sshd on :22 (keypair auth)           │ │
│  │  - Opens asyncssh connection   │   │  - vystak-rpc subsystem                 │ │
│  │    to workspace                │ ◄─┤  - fs/exec/git/tool services            │ │
│  │  - Tools proxy via JSON-RPC    │SSH│  - Reads /shared/ for secrets + SSH keys│ │
│  │  - Reads /shared/secrets.env   │RPC│  - Mounts workspace-data at /workspace  │ │
│  │    for Agent.secrets in env    │   │                                         │ │
│  └────────────────────────────────┘   └─────────────────────────────────────────┘ │
│                                                │                                   │
│                                                │ (human may SSH here if ssh=True)  │
│                                                ▼                                   │
│                                        host port → sshd :22                        │
└────────────────────────────────────────────────────────────────────────────────────┘
```

The workspace container is a peer of the agent container, not a
sidecar. It has its own lifecycle: `vystak apply` creates both; a
re-apply with unchanged workspace config may update the agent without
restarting the workspace. Its persistent volume `vystak-<agent>-
workspace-data` is preserved across destroy-and-re-apply.

### Schema changes

`packages/python/vystak/src/vystak/schema/workspace.py`:

```python
from vystak.schema.common import NamedModel, WorkspaceType
from vystak.schema.provider import Provider
from vystak.schema.secret import Secret


class Workspace(NamedModel):
    """Declarative workspace — deploys as its own container when set on an Agent."""

    # --- Image + provisioning -------------------------------------------
    image: str | None = None
    """Base Docker image. Required unless `dockerfile` is set."""

    provision: list[str] = []
    """Shell commands run as RUN statements during image build.
    Execute top-to-bottom, Docker-layer-cached per line."""

    copy: dict[str, str] = {}
    """host_path → container_path pairs emitted as COPY statements.
    Paths are relative to the project directory."""

    dockerfile: str | None = None
    """Escape hatch: path to a user-supplied Dockerfile. When set,
    `image`, `provision`, and `copy` are ignored; vystak does not
    generate any build steps beyond appending its required tail."""

    tool_deps_manager: str | None = None
    """"pip" | "npm" | "none". Auto-detected from base image if unset."""

    # --- Filesystem / persistence ---------------------------------------
    persistence: str = "volume"
    """"volume" (default, named Docker volume at /workspace),
    "bind" (bind-mount `path` from host to /workspace),
    "ephemeral" (no persistence — fresh filesystem every deploy)."""

    path: str | None = None
    """Required if persistence="bind". Absolute or project-relative
    path on the host."""

    # --- Network / resources --------------------------------------------
    network: bool = True
    """False = egress disabled (future: fine-grained allow-list)."""

    gpu: bool = False
    """True = attach GPU runtime (nvidia)."""

    timeout: str | None = None
    """Default timeout for RPC calls. Per-call override available."""

    # --- Secrets (from v1 secret-manager) --------------------------------
    secrets: list[Secret] = []
    identity: str | None = None

    # --- Human SSH (opt-in) ---------------------------------------------
    ssh: bool = False
    """True = enable sshd for interactive human access. The agent's
    keypair already accesses the subsystem; this opens a separate user
    with full shell."""

    ssh_authorized_keys: list[str] = []
    """Public keys granted shell access. Empty + ssh=True is an error."""

    ssh_authorized_keys_file: str | None = None
    """Alternative: path to authorized_keys file to copy in."""

    ssh_host_port: int | None = None
    """Host port binding for sshd. If None, ephemeral port auto-
    allocated; reported in `vystak apply` output."""

    # --- Legacy / compat ------------------------------------------------
    type: WorkspaceType | None = None
    """Legacy field. If set and `persistence` is not, `type=persistent`
    maps to persistence='volume', 'sandbox' → 'ephemeral', 'mounted' →
    'bind'. Deprecation warning emitted when only `type` is used.
    Dropped in a future major release."""

    # Dropped from legacy schema (no-ops removed):
    #   filesystem, terminal, browser, persist, max_size
    #   provider (workspace inherits agent's platform.provider)
```

Cross-object validators:
- `Workspace(persistence="bind") requires path=` — raise otherwise.
- `Workspace(ssh=True) requires ssh_authorized_keys or ssh_authorized_keys_file` — prevent foot-shoot.
- `Workspace(dockerfile=...) is mutually exclusive with image/provision/copy` — raise if both.
- `Workspace.secrets` still requires a Hashi `Vault(type="vault")` on Docker or a KV `Vault(type="key-vault")` on Azure (existing v1 rule).
- **`Agent.workspace is not None` requires a `Vault` declaration on
  the deployment** — new in Spec 1. Workspaces rely on Vault for both
  user secrets and vystak-managed SSH keys. Error message points users
  at the v1 Secret Manager spec to add a Vault.

### Image generation and build

When an agent declares a workspace and `dockerfile` is not set, vystak
generates a Dockerfile at apply time:

```dockerfile
FROM <workspace.image>
WORKDIR /workspace

# --- User provision steps (each as its own RUN layer for cache)
RUN <provision[0]>
RUN <provision[1]>
...

# --- User file drops
COPY <copy["src_1"]> <copy["dst_1"]>
COPY <copy["src_2"]> <copy["dst_2"]>
...

# --- Vystak's appendix ---
# Tool code
COPY tools/ /workspace/tools/
RUN <tool_deps_install>         # pip install -r tools/requirements.txt, or npm install, or skipped

# SSH server + vystak-rpc subsystem
RUN apt-get update && apt-get install -y --no-install-recommends openssh-server \
    && mkdir -p /var/run/sshd /etc/ssh/authorized_keys \
    && rm -rf /var/lib/apt/lists/*
COPY vystak-sshd.conf /etc/ssh/sshd_config.d/50-vystak.conf
COPY vystak-workspace-rpc /usr/local/bin/vystak-workspace-rpc
RUN chmod +x /usr/local/bin/vystak-workspace-rpc

# vystak + transport source bundled (same pattern as agent container)
COPY vystak /app/vystak
COPY vystak_transport_http /app/vystak_transport_http
ENV PYTHONPATH=/app:/workspace

# Entrypoint shim (v1 secret-manager pattern): waits for /shared/secrets.env,
# sources into env, then execs sshd.
COPY entrypoint-shim.sh /vystak/entrypoint-shim.sh
RUN chmod +x /vystak/entrypoint-shim.sh
ENTRYPOINT ["/vystak/entrypoint-shim.sh"]
CMD ["/usr/sbin/sshd", "-D", "-e"]
```

Notable choices:
- **`CMD ["/usr/sbin/sshd", "-D", "-e"]`**. sshd is PID 1 (via the
  shim's `exec`). The vystak-rpc subsystem is spawned per-channel by
  sshd, not a long-running process.
- **Tool deps auto-detection**: if `image` starts with `python`, use
  pip; if `node`, use npm; if starts with something else and
  `tool_deps_manager=None`, emit a warning and skip tool-deps install.
  Users override explicitly.
- **Base image constraints**: needs `apt-get` (Debian/Ubuntu family)
  for the openssh-server install. If the base image is Alpine or
  distroless, users must `provision=["apk add openssh"]` themselves
  OR use `dockerfile=` escape hatch. Documented; not auto-detected.

### JSON-RPC 2.0 protocol over SSH channels

**Transport:** `asyncssh` on the agent side, OpenSSH sshd on the
workspace side with a custom subsystem declaration. All vystak-managed
SSH state lives under `/etc/vystak-ssh/` (mounted from a named
volume, see "SSH key lifecycle" below):

```
# /etc/ssh/sshd_config.d/50-vystak.conf
HostKey /etc/vystak-ssh/ssh_host_ed25519_key
Subsystem vystak-rpc /usr/local/bin/vystak-workspace-rpc
PermitRootLogin no
PasswordAuthentication no
PubkeyAuthentication yes
ClientAliveInterval 60
ClientAliveCountMax 3

Match User vystak-agent
    AuthenticationMethods publickey
    AuthorizedKeysFile /etc/vystak-ssh/authorized_keys_vystak-agent
    ForceCommand /usr/local/bin/vystak-workspace-rpc
    PermitTTY no
    X11Forwarding no
    AllowTcpForwarding yes  # required for future LSP port-forwards
    GatewayPorts no
    PermitOpen any

Match User vystak-dev
    # normal shell access; AuthorizedKeysFile defaults to ~/.ssh/authorized_keys
    # (baked into image from ssh_authorized_keys schema field, not sensitive)
```

Agent flow at startup:
1. Reads the pre-generated private key + known_hosts from `/vystak/ssh/`
   (read-only volume mount, details in "SSH key lifecycle" below).
2. Opens one persistent `asyncssh.connect(host, user='vystak-agent',
   client_keys=['/vystak/ssh/id_ed25519'],
   known_hosts='/vystak/ssh/known_hosts')` connection.
3. Per tool call, opens an SSH **session channel** requesting
   subsystem `vystak-rpc`. Writes one or more JSON-RPC requests to the
   channel, reads responses line-by-line.
4. Channel closes at end of call. Connection stays alive across calls.

**Application protocol:** JSON-RPC 2.0 with newline-delimited JSON
framing (JSONL, one message per line).

Request (agent → workspace):
```json
{"jsonrpc":"2.0","id":"6ab1...","method":"fs.readFile","params":{"path":"main.py"}}
```

Non-streaming response:
```json
{"jsonrpc":"2.0","id":"6ab1...","result":"import sys\n...\n"}
```

Streaming: server emits zero or more notifications (no `id`), then a
final response (with `id`):
```json
{"jsonrpc":"2.0","method":"$/progress","params":{"id":"6ab1...","chunk":"..."}}
{"jsonrpc":"2.0","method":"$/progress","params":{"id":"6ab1...","chunk":"..."}}
{"jsonrpc":"2.0","id":"6ab1...","result":{"exit_code":0,"duration_ms":423}}
```

Error:
```json
{"jsonrpc":"2.0","id":"6ab1...","error":{"code":-32001,"message":"File not found","data":{"path":"main.py"}}}
```

Cancellation: agent closes the channel. Workspace-side handler
receives a cancellation signal and aborts any in-progress exec
(SIGTERM to subprocess, cleanup, no result sent).

**Why JSON-RPC 2.0 specifically:** same spec LSP uses. When Spec 3
brings LSP bridging, LSP messages can ride the same framing on the
same transport — either multiplexed with vystak's own methods or on a
separate `lsp` channel. DAP is also JSON-RPC 2.0; also free if needed
later. We don't build LSP/DAP in v1; we pick the framing that doesn't
close the door.

### Services (v1 built-in)

Namespaced method prefixes. All methods are on the single
`vystak-rpc` subsystem; no separate endpoints.

**`fs.*`** — filesystem over SFTP passthrough or direct implementation.
v1 implementation is direct Python in the subsystem (SFTP is harder to
multiplex cleanly with our JSON-RPC on the same channel). Methods:

| Method | Params | Result |
|---|---|---|
| `fs.readFile` | `{path, encoding?}` | `str` |
| `fs.writeFile` | `{path, content, encoding?, mode?}` | `null` |
| `fs.appendFile` | `{path, content, encoding?}` | `null` |
| `fs.deleteFile` | `{path}` | `null` |
| `fs.listDir` | `{path, glob?}` | `[{name, type, size, mtime}, ...]` |
| `fs.stat` | `{path}` | `{type, size, mtime, permissions}` |
| `fs.exists` | `{path}` | `bool` |
| `fs.mkdir` | `{path, parents?}` | `null` |
| `fs.move` | `{src, dst}` | `null` |
| `fs.edit` | `{path, old_str, new_str}` | `{diff}` (claude-code-style) |

All paths are constrained to `/workspace/` by default. Escape requires
explicit `allow_workspace_escape: true` in the Workspace schema (v1
default is strict).

**`exec.*`** — process execution.

| Method | Params | Streaming | Result |
|---|---|---|---|
| `exec.run` | `{cmd, args?, cwd?, env?, timeout_s?}` | Yes, `stdout` / `stderr` chunks via `$/progress` | `{exit_code, duration_ms}` |
| `exec.shell` | `{script, cwd?, timeout_s?}` | Yes | `{exit_code, duration_ms}` |
| `exec.which` | `{name}` | No | `str | null` |

`cmd` is argv-style (list); `script` is arbitrary shell (sh -c). `env`
merges over container env. `cwd` defaults to `/workspace/`.

**`git.*`** — git operations, if `git` is installed in the workspace
(typically from `provision=["apt-get install -y git"]`).

| Method | Params | Result |
|---|---|---|
| `git.status` | `{}` | `{branch, dirty, staged, unstaged, untracked}` |
| `git.log` | `{limit?, path?}` | `[{sha, author, message, date}, ...]` |
| `git.diff` | `{path?, staged?}` | `str` |
| `git.add` | `{paths}` | `null` |
| `git.commit` | `{message, author?}` | `{sha}` |
| `git.branch` | `{}` | `str` |

If git is not installed, all `git.*` methods return an error with
guidance.

**`tool.*`** — user-defined skill tools.

Each skill tool (file `tools/<name>.py` with a function named
`<name>`) is exposed as `tool.<name>`. Signature is the function's
signature; params are JSON-deserialized into its args. The function's
return value is the `result`. Streaming tool output uses Python
generators + the framework's `$/progress` emission:

```python
# tools/search_files.py
from vystak.workspace import progress

def search_files(pattern: str, max_results: int = 50) -> list[str]:
    results = []
    for path in walk_project():
        if match(path, pattern):
            progress(f"found: {path}")   # emits a $/progress notification
            results.append(path)
            if len(results) >= max_results:
                break
    return results
```

### Generated LangChain tool wrappers

On the agent side, the adapter generates a LangChain `@tool` wrapper
for each built-in and user-defined method. Wrapper body is async,
makes an RPC call over the SSH connection, and returns the result.

```python
# Generated
from langchain_core.tools import tool
from vystak.workspace_client import rpc

@tool
async def read_file(path: str, encoding: str = "utf-8") -> str:
    """Read a file from the workspace."""
    return await rpc.call("fs.readFile", path=path, encoding=encoding)

@tool
async def run_shell(script: str, timeout_s: int | None = None) -> dict:
    """Run a shell script in the workspace. Streams output as it runs."""
    return await rpc.call_streaming("exec.shell", script=script, timeout_s=timeout_s)

# ... per user-defined tool ...
```

The adapter decides streaming vs non-streaming from a static map:
`exec.*` methods always stream; `fs.*`, `git.*` do not; user tools
declare streaming via a `@streams` decorator in their implementation.

### Built-in tools vs user skills

In v1, most coding-agent needs are covered by `fs.*`, `exec.*`,
`git.*`. `Skill` objects become lightweight — prompts plus occasional
custom Python under `tools/`:

```python
agent = ast.Agent(
    name="coder",
    model=..., platform=...,
    skills=[
        ast.Skill(name="editing", tools=["fs.readFile", "fs.writeFile", "fs.edit", "fs.listDir"]),
        ast.Skill(name="testing", tools=["exec.run"]),
        ast.Skill(name="vcs", tools=["git.status", "git.diff", "git.commit"]),
        ast.Skill(name="research", tools=["search_project"]),  # custom tool
    ],
    workspace=ast.Workspace(
        name="dev",
        image="python:3.12-slim",
        provision=[
            "apt-get update && apt-get install -y git curl ripgrep",
            "pip install ruff pytest",
        ],
        persistence="bind",
        path="~/Projects/my-app",
    ),
)
```

`Skill.tools` now accepts:
- Built-in service method names like `fs.readFile`, `exec.run`,
  `git.status` — no file needed, resolves to the RPC wrapper.
- Bare tool names like `search_project` — resolves to
  `tools/search_project.py` on disk (current behavior). The function
  runs in the workspace, reachable via `tool.search_project`.

### Secret-manager integration — finishing the v1 story

v1 Secret Manager deployed a Vault-Agent sidecar for the workspace
principal but had no workspace container for it to feed. Spec 1 fixes
that, and extends the sidecar to also deliver vystak-generated SSH
keys (see "SSH key lifecycle" below for the key-specific
mechanics).

1. `Workspace.secrets: list[Secret]` drives the workspace principal's
   AppRole policy (same as v1).
2. Workspace Vault-Agent sidecar renders two kinds of files into the
   `vystak-<agent>-workspace-secrets` volume:
   - `/shared/secrets.env` — user-declared `Workspace.secrets` as
     env-var assignments (same as v1).
   - `/shared/ssh_host_ed25519_key`, `/shared/authorized_keys_vystak-agent`
     — vystak-managed SSH material (new in Spec 1).
3. **The workspace container mounts this volume at `/shared/`** (new
   in Spec 1). The entrypoint shim sources `/shared/secrets.env` into
   the sshd process's env; sshd reads the SSH key files directly per
   its sshd_config.
4. **The agent container mounts its own Vault-Agent-rendered volume**
   at `/vystak/ssh/` (containing `id_ed25519` and `known_hosts` —
   rendered by the agent principal's Vault-Agent sidecar). Clean
   separation: agent container has only `Agent.secrets` in env;
   workspace container has only `Workspace.secrets`. RBAC +
   filesystem + env-var layers all aligned.

Isolation guarantee (now honest):
- Workspace secret values reach only the workspace container's env.
- Tool RPC calls happen in that env, so tool code sees workspace
  secrets via `vystak.secrets.get(...)` (Spec 1 also exposes
  `os.environ[...]` as the ultimate source — no SDK migration).
- LLM reasoning happens in the agent container, which has only model
  keys. Tool *invocations* cross the SSH boundary; tool *outputs*
  return as JSON-RPC results, never as raw env dumps.

**What the LLM can still do** (honestly):
- Call `fs.readFile("/proc/self/environ")` on the workspace side → see
  workspace env (including `STRIPE_API_KEY`). `/proc` is not excluded
  from `fs.readFile` by default.
- Call `exec.shell("env")` on the workspace side → same.

Hardening hooks (documented in Spec 2, not Spec 1):
- `fs.*` path allow-list excluding `/proc`, `/sys`, `/shared`, `/etc`
- `exec.*` shell blocklist
- Neither is v1 scope — v1 documents the workspace as "trusted dev
  environment; don't put production-valuable secrets where an untrusted
  prompt can extract them via exec or fs."

### SSH key lifecycle

The agent↔workspace SSH channel is authenticated in both directions
with cryptographic keypairs. Neither the user nor the agent's
application code configures, stores, or manages these keys — they are
generated by vystak at apply time and delivered through the same
Secret Manager infrastructure that handles user secrets.

**Four pieces of key material, all stored in Vault:**

| Key | Vault path (Hashi / KV secret name) | Used by |
|---|---|---|
| Agent client private key | `_vystak/workspace-ssh/<agent>/client-key` | Agent container, to authenticate to workspace sshd |
| Workspace host private key | `_vystak/workspace-ssh/<agent>/host-key` | Workspace sshd, as its server-identity key |
| Agent client public key | `_vystak/workspace-ssh/<agent>/client-key-pub` | Workspace sshd, baked into `authorized_keys_vystak-agent` |
| Workspace host public key | `_vystak/workspace-ssh/<agent>/host-key-pub` | Agent container, written into `known_hosts` |

The `_vystak/` path prefix is a reserved namespace — validator rejects
user secrets that attempt to write under it. This keeps vystak-internal
key material clearly separated from user secrets in Vault audit logs.

**Generation — first apply only:**

On the first `vystak apply` for a deployment with a workspace:
1. A throwaway alpine container (same pattern as v1's AppRole credential
   writer) runs `ssh-keygen -t ed25519 -N ''` twice to produce both
   keypairs.
2. The four pieces are pushed to Vault via the standard `vystak secrets
   push` mechanism, under the `_vystak/workspace-ssh/<agent>/` path.
3. Vystak's secret-sync step on subsequent applies uses push-if-missing
   semantics (same as user secrets): the keys are generated once and
   preserved across apply cycles unless explicitly rotated.

**Delivery — via Vault Agent file templates:**

Each principal's Vault-Agent sidecar config gains template blocks for
the SSH keys it needs. For the workspace principal:

```hcl
template {
  destination = "/shared/ssh_host_ed25519_key"
  perms       = "0600"
  contents    = '{{ with secret "secret/data/_vystak/workspace-ssh/<agent>/host-key" }}{{ .Data.data.value }}{{ end }}'
}
template {
  destination = "/shared/authorized_keys_vystak-agent"
  perms       = "0444"
  contents    = '{{ with secret "secret/data/_vystak/workspace-ssh/<agent>/client-key-pub" }}{{ .Data.data.value }}{{ end }}'
}
```

For the agent principal:

```hcl
template {
  destination = "/vystak/ssh/id_ed25519"
  perms       = "0400"
  contents    = '{{ with secret "secret/data/_vystak/workspace-ssh/<agent>/client-key" }}{{ .Data.data.value }}{{ end }}'
}
template {
  destination = "/vystak/ssh/known_hosts"
  perms       = "0444"
  contents    = 'vystak-<agent>-workspace {{ with secret "secret/data/_vystak/workspace-ssh/<agent>/host-key-pub" }}{{ .Data.data.value }}{{ end }}'
}
```

Azure path: same four KV secrets, delivered via the existing
`lifecycle: None` UAMI + per-container `secretRef` mechanism from v1.
The secretRef values become files mounted at the paths above using
ACA's `volumeMounts[].secrets` feature. No new Azure plumbing beyond
what v1 already does for user secrets.

**User-visible surface:** none.
- No schema fields name SSH keys.
- No host-side files contain key material.
- No manual setup, no per-machine copying.
- No mention of SSH in the default error messages for the happy path
  (SSH is the transport, not a feature).

**Rotation:** `vystak secrets rotate-ssh <agent>` (new CLI subcommand,
mirrors `rotate-approle` from v1). Regenerates both keypairs via the
throwaway-alpine pattern, pushes over the old values with `--force`
semantics, the Vault Agents re-render the files on their next
template-render cycle (< 30s). Agent's SSH connection drops (server
key changed), reconnects with new client key. One-command rotation.

**Destroy semantics:**
- Default `vystak destroy`: SSH key secrets remain in Vault (same rule
  as user secrets — preserved by default).
- `vystak destroy --delete-vault`: Vault and all its secrets (user +
  vystak-internal) are dropped; next apply regenerates everything.
- `vystak destroy --delete-workspace-data`: drops workspace data
  volume only; SSH keys unaffected.

**Human SSH** (`ssh=True`): the `vystak-dev` user's `authorized_keys`
is populated from the schema field `ssh_authorized_keys=[...]` and
baked into the workspace image at build (user pubkeys are not
sensitive; image-baked is fine). The workspace's **host key** is
shared with the agent-auth path — humans see the same host key, which
matches `.vystak`-managed `known_hosts` entries they add once.

### Prerequisites enforcement — what happens without a Vault

If a user declares `Agent.workspace=...` but no `Vault` in the same
deployment:

```
ValidationError: Agent 'assistant' declares a workspace but no Vault
is declared. Spec 1 workspaces require a Vault for SSH key storage
and workspace-secret delivery.

To fix, add a Vault to your deployment:

  vault:
    name: vystak-vault
    provider: docker
    type: vault
    mode: deploy
    config: {}

See docs/superpowers/specs/2026-04-19-secret-manager-design.md for
the full Vault schema.
```

The error is caught at load time (in `multi_loader.py`) before any
provisioning work starts.

### Human SSH access (opt-in)

When `ssh=True`:
- sshd already runs (it's the CMD). Just opens a second user
  `vystak-dev` with full shell (no ForceCommand).
- `ssh_authorized_keys` populates `/home/vystak-dev/.ssh/authorized_keys`.
- `ssh_host_port` binds the container's port 22 to a host port. If
  unset, Docker auto-allocates; vystak reports it in the apply output.
- User connects: `ssh -p <host_port> vystak-dev@localhost` and lands
  in `/workspace/` with full shell.
- Same sshd serves both `vystak-agent` (subsystem-only) and
  `vystak-dev` (interactive). Different `Match User` blocks enforce
  the difference.

### Persistence modes

**`persistence="volume"` (default):**
- Named Docker volume `vystak-<agent-name>-workspace-data`
- Mounted at `/workspace/` read-write
- Created on first apply, preserved across subsequent applies and
  default destroy
- Dropped on `vystak destroy --delete-workspace-data`

**`persistence="bind":**
- Host path from `Workspace.path` bind-mounted at `/workspace/`
- `~/` expansion supported; path resolved relative to the apply cwd
  if not absolute
- Vystak does not create or delete the path — user owns it
- `vystak destroy` is a no-op for the path
- Great for pointing the agent at an actual git checkout

**`persistence="ephemeral":**
- `/workspace/` is a Docker tmpfs (in-memory) or empty directory
- Nothing persists across container restart
- Useful for stateless automation

### Provider deployment — Docker

`vystak-provider-docker` gains a new `DockerWorkspaceNode` that
inserts into the ProvisionGraph between the Vault-Agent sidecar node
and the agent node:

```
DockerNetworkNode
  └── HashiVaultServerNode (if vault declared)
        └── HashiVaultInitNode
              └── HashiVaultUnsealNode
                    └── VaultKvSetupNode
                          ├── AppRoleNode (agent)
                          │     └── AppRoleCredentialsNode (agent)
                          │           └── VaultAgentSidecarNode (agent)
                          └── AppRoleNode (workspace)
                                └── AppRoleCredentialsNode (workspace)
                                      └── VaultAgentSidecarNode (workspace)
                                            └── **DockerWorkspaceNode** ★ new
                                                  └── DockerAgentNode (now depends on workspace)
```

`DockerWorkspaceNode`:
- Generates the workspace Dockerfile (as above)
- Builds the image (keys are **not** baked in — sshd reads them from
  the Vault-Agent-rendered files at `/shared/`)
- Runs the container with:
  - Workspace data volume at `/workspace/`
  - Vault-Agent-rendered secrets volume at `/shared/` (pre-existing
    from v1 Hashi, now populated with both env secrets and SSH key
    files per the extended Vault Agent HCL template)
  - Network alias `vystak-<agent>-workspace`
  - Standard vystak labels
- Returns the workspace's internal DNS address in its ProvisionResult

New: `WorkspaceSshKeygenNode` — runs before the two Vault-Agent sidecar
nodes. Generates the four SSH key pieces via throwaway alpine and
pushes them into Vault under `_vystak/workspace-ssh/<agent>/*` using
the existing `VaultSecretSyncNode` mechanism extended with a `push-
if-missing` call for these specific paths. Once the secrets are in
Vault, the existing Vault-Agent sidecar configs (generated with the
extra template blocks for SSH files) deliver them to the containers.

`DockerAgentNode`:
- Gains a new `set_workspace_context(workspace_dns)` method (mirrors
  the `set_vault_context` pattern from v1 Hashi)
- When set, agent's Dockerfile adds `ENV VYSTAK_WORKSPACE_HOST=...`
  pointing at the workspace's internal DNS
- Agent's generated bootstrap code establishes the SSH connection on
  startup using `/vystak/ssh/id_ed25519` and `/vystak/ssh/known_hosts`
  (both rendered by the agent principal's Vault-Agent sidecar)
- Fails fast if workspace is unreachable or SSH auth fails

### Provider deployment — Azure Container Apps

`vystak-provider-azure` gains a new `WorkspaceContainerAppNode`:
- Creates a separate ACA app `<agent-name>-workspace`
- Builds the workspace image, pushes to ACR (same path as the agent
  image)
- Secrets flow via the existing `lifecycle: None` + `secretRef` pattern
  from v1 Azure secret-manager (workspace principal → KV-scoped UAMI
  → per-container secretRef)
- **SSH keys (both host and client-pub for authorized_keys) are
  additional KV secrets** under `_vystak/workspace-ssh/<agent>/*`,
  delivered via the same mechanism as user secrets. Mounted as files
  in the workspace container via ACA `volumeMounts[].secrets`. No new
  Azure plumbing.
- Internal DNS: `<agent-name>-workspace.internal.<env>.azurecontainerapps.io`
- Ingress: internal only (no external endpoint for the workspace)
- Agent's container gets `VYSTAK_WORKSPACE_HOST=<workspace DNS>:22`;
  its own SSH client key + known_hosts mounted as files from KV via
  the agent principal's UAMI.

Azure-side the workspace's compute lifecycle is independent (different
ACA app), so `vystak destroy` can delete-agent-keep-workspace if
desired — added flag `--keep-workspace`.

### CLI changes

- `vystak apply`: no new user-facing flags. Output grows a
  `Workspace:` section when a workspace is declared, showing image,
  persistence, workspace URL, and human-SSH port (if enabled).
- `vystak plan`: gains a `Workspace:` section mirroring apply's
  preview. Shows what image will be built, what RUN layers change,
  persistence mode, and whether the data volume will be preserved or
  created fresh.
- `vystak destroy`: new flags
  - `--delete-workspace-data` — drop the workspace data volume (if
    `persistence="volume"`). Mirrors `--delete-vault` pattern.
  - `--keep-workspace` — tear down the agent but leave the workspace
    container running. Useful when iterating on agent logic while
    keeping a stateful coding session alive.
- `vystak secrets`: gains one new subcommand.
  - `vystak secrets rotate-ssh <agent>` — regenerates the four
    SSH keypairs for the given agent's workspace, pushes to Vault
    with `--force`. Vault Agents re-render the files on next template
    cycle; agent's SSH connection drops and reconnects with new keys.
    Parallel structure to `vystak secrets rotate-approle` from v1.

### Hash tree additions

`AgentHashTree` extends with a `workspace_image: str` hash — the
sha256 of the effective Dockerfile (base image + provision list + copy
list + vystak appendix). Changes here trigger a workspace rebuild on
the next apply; changes elsewhere do not. This is deliberately
separate from the existing `workspace: str` hash (which captures the
`Workspace` schema object) so schema-only changes (e.g., renaming the
workspace) don't force a rebuild.

### Backward compatibility

- Agents without `Agent.workspace` continue to work identically.
  `DockerWorkspaceNode` / `WorkspaceContainerAppNode` are not added to
  the graph; tools run inline in the agent container as today.
- Existing examples with legacy `Workspace(type="persistent")` and no
  `image=` continue to compile. Warning emitted: "Workspace 'foo'
  declared without `image=`; set `image=...` + `provision=[...]` to
  opt into Spec 1 behavior." Until they opt in, the workspace field
  remains declarative-only — matching today's no-op behavior.
- The `type=` field is accepted for one release cycle, warns on use,
  then removed in a future major.
- Legacy fields `filesystem`, `terminal`, `browser`, `persist`,
  `max_size` are dropped in this spec — no current example or provider
  references them.

### Migration — concrete steps for existing users

**Users with declarative workspaces (no real behavior):**
```diff
  ast.Workspace(
-     name="dev",
-     type="persistent",
-     filesystem=True,
+     name="dev",
+     image="python:3.12-slim",
+     provision=[
+         "apt-get update && apt-get install -y git",
+         "pip install ruff pytest",
+     ],
+     persistence="volume",
  )
```

**Users with existing agent tool sets:**
- All `@tool`-decorated Python files under `tools/` continue to
  compile. When a workspace is added to the agent, those tools run in
  the workspace container instead of the agent process. For most
  tools this is transparent (they read files, make HTTP calls). Tools
  that rely on agent-process-local state break — documented.

### Testing

Unit tests (no Docker):
- Workspace schema validation (mutual-exclusion, required fields)
- Dockerfile generation from `image`/`provision`/`copy`
- Tool-deps auto-detection per base image
- Adapter code generation for `fs.*`, `exec.*`, `git.*`, `tool.*`
  wrappers
- Mock JSON-RPC 2.0 framing (request, streaming response, error,
  cancel)
- Persistence mode validation (bind requires path, ephemeral has no
  volume)
- Legacy `type=` → `persistence=` compatibility mapping

Integration tests (`-m docker`):
- Workspace deploys, agent can establish SSH connection to it
- `fs.readFile` / `fs.writeFile` round-trip against persistent volume
- `exec.run "echo hi"` streams "hi\n" as `$/progress` and final exit=0
- `exec.run` cancellation via SSH channel close kills the subprocess
- `git.status` in a pre-cloned workspace repo
- User tool `tools/search_project.py` invocable via `tool.search_project`
- Workspace secret in env via v1 integration:
  workspace container has `STRIPE_API_KEY`, agent container does not
- Human SSH access: `ssh -p <port> vystak-dev@localhost` lands in
  `/workspace/` with full shell
- `vystak destroy` (default): workspace data volume preserved
- `vystak destroy --delete-workspace-data`: volume removed

### Performance targets

- Agent-side SSH connection startup: < 2s (connect + authenticate +
  one smoke RPC)
- Per-call RPC latency (fs.readFile on a 10KB file, localhost
  network): < 5ms p50
- Streaming throughput (exec.run streaming 1MB of stdout): > 10MB/s
- Agent restart without workspace restart: < 5s (no workspace data
  loss)

### Non-goals (explicitly named, carry-forward)

- Sandboxed exec for LLM-generated untrusted code → Spec 2
- LSP bridging → Spec 3
- Per-user / per-session / per-project workspace scope → orchestrator
  spec
- Multiple workspaces per agent → TBD, probably orchestrator
- Workspace shared across multiple agents → TBD, probably orchestrator
- Hot-reload of tool code (today: apply rebuilds image)
- Disk quotas, resource limits beyond what the platform provides
- Remote-VM workspaces (SSH to a non-container target) — possible
  later, schema doesn't preclude it
- GUI/X11
- Alpine / distroless base image auto-support (requires user to
  provide their own `dockerfile=`)

## Follow-on specs

- `2026-??-??-workspace-sandbox-design.md` — Spec 2. Hardened
  execution for LLM-generated code. Per-tool allow-lists, path
  restrictions for `fs.*`, egress network policies, optional
  container-runtime alternatives (gVisor, Firecracker, e2b).
- `2026-??-??-workspace-lsp-design.md` — Spec 3. Language server
  integration. `lsp.<server_name>.<method>` routes LSP JSON-RPC
  through the same SSH connection (port forwarding enabled). Built-in
  support for Python (pyright), TypeScript (tsserver), Go (gopls),
  Rust (rust-analyzer). Per-project workspace configuration
  detection.
- `2026-??-??-workspace-orchestrator-design.md` — Per-user /
  per-session / per-project scoping. Dynamic workspace spawn / idle
  eviction / scope-based routing from channel → agent → workspace.

## Open questions for implementation

- **sshd user management.** Generating `vystak-agent` and
  (conditionally) `vystak-dev` users in the image requires either
  hardcoded UIDs (100, 101) or dynamic selection. v1 assumption:
  hardcoded. Documented.
- **Tool deps detection heuristic.** Simple prefix-match on image
  name is brittle (`python:3.12-slim-bullseye` matches python, but
  `cimg/python:3.12` doesn't). v1 heuristic: check if image contains
  `python`, `node`, or neither. User-override always available.
- **Vault Agent file-template edge cases.** Rendering a file (rather
  than the existing env-var template) requires Vault Agent version
  that supports `template.destination` with `perms` for sensitive
  files. All recent (1.14+) versions do; we pin a known-good version
  in the generated config.
- **Multi-file skill tools.** Current `tools/` layout is one file per
  tool. Users with complex tool packages (helpers, tests, shared
  utilities) want a package layout. v1 accepts `tools/` with
  arbitrary subdirectories; bundles them all. Conventions can firm up
  in Spec 2 if needed.

## Rationale for key decisions

**Why separate compute unit and not sidecar?** The decoupled
lifecycle is worth the minor latency. Being able to `vystak apply`
changes to agent logic without restarting the workspace (and losing
open terminal sessions, warm caches, in-flight git operations) is the
coding-agent daily-driver optimization. Sidecar would save ~1ms per
RPC and lose hours of developer-flow preservation over a typical
session.

**Why JSON-RPC 2.0, not a custom protocol?** Interop with LSP/DAP
means Spec 3 and follow-ons don't have to invent new framing. VS Code,
most IDEs, and most remote-dev tooling speak this natively. No
architectural cost to choose it over a custom shape.

**Why SSH, not HTTP+WebSocket?** Keypair auth comes free, port
forwarding ready for LSP (Spec 3), human access is a natural side
benefit. The cross-platform story is identical (localhost / internal
DNS works on Docker + ACA). WebSocket would've required designing a
token-auth scheme; SSH already has one.

**Why BYO base image over stock `vystak-workspace` image?** Coding
agents need specific toolchains — Python 3.11 vs 3.12, Node 20 vs 22,
Rust stable vs nightly, with specific packages. A stock image either
caters to everyone (huge) or nobody (too minimal). Declarative
provisioning lets users say exactly what they need; Docker layer-cache
makes the build fast on iterate.

**Why services model (`fs.*`, `exec.*`, ...) instead of flat tools?**
Scales better. Spec 3's LSP bridging will add `lsp.*`; Spec 2's
hardened exec will override `exec.*`; future services (`test.*`,
`build.*`) can be added without namespace collisions. Flat tool
namespace with prefixes works today but becomes a bikeshed once
there's more than one source of tools.
