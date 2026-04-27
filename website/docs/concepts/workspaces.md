---
title: Workspaces
sidebar_label: Workspaces
---

import Tabs from '@theme/Tabs';
import TabItem from '@theme/TabItem';

# Workspaces

A **workspace** is an isolated execution environment that runs alongside an agent. When an agent has a workspace, its tools (file I/O, shell commands, git operations) execute *inside the workspace container* rather than inside the agent container.

This separation matters for two reasons:

1. **Isolation.** The LLM driving the agent never has direct access to your filesystem, secrets, or shell. Tool calls cross a JSON-RPC boundary into a sandboxed container.
2. **Tool richness.** Workspaces ship with a built-in tool library (`fs.*`, `exec.*`, `git.*`) that's only generated when a workspace is declared.

## Mental model

```
┌──────────────────┐                ┌──────────────────┐
│  Agent container │  JSON-RPC      │ Workspace        │
│  (LangGraph +    │  over SSH      │ container        │
│   FastAPI + LLM) │ ◄────────────► │ (your tools run  │
│                  │                │  here)           │
└──────────────────┘                └──────────────────┘
```

The agent container handles HTTP, channels, and LLM calls. The workspace container holds the filesystem the agent reads/writes, the shell where commands run, and any per-workspace secrets.

## Minimal workspace

A bare workspace gives your agent the built-in `fs.*`, `exec.*`, and `git.*` tools, backed by a Docker volume:

<Tabs groupId="config-format">
<TabItem value="yaml" label="YAML" default>

```yaml
agents:
  - name: coder
    instructions: |
      You are a coding assistant. Use fs.readFile to read, fs.edit to change,
      exec.run to test, git.status / git.diff to review changes.
    model: sonnet
    platform: local
    skills:
      - name: editing
        tools: [fs.readFile, fs.writeFile, fs.listDir, fs.edit]
      - name: shell
        tools: [exec.run, exec.shell]
      - name: vcs
        tools: [git.status, git.diff, git.commit]
    workspace:
      name: dev
      image: python:3.12-slim
      provision:
        - apt-get update && apt-get install -y git ripgrep
        - pip install ruff pytest
      persistence: volume
```

</TabItem>
<TabItem value="python" label="Python">

```python
import vystak as ast

docker = ast.Provider(name="docker", type="docker")
anthropic = ast.Provider(name="anthropic", type="anthropic")
platform = ast.Platform(name="local", type="docker", provider=docker)
model = ast.Model(
    name="sonnet", provider=anthropic, model_name="claude-sonnet-4-20250514",
)

workspace = ast.Workspace(
    name="dev",
    image="python:3.12-slim",
    provision=[
        "apt-get update && apt-get install -y git ripgrep",
        "pip install ruff pytest",
    ],
    persistence="volume",
)

agent = ast.Agent(
    name="coder",
    instructions=(
        "You are a coding assistant. Use fs.readFile to read, fs.edit to change, "
        "exec.run to test, git.status / git.diff to review changes."
    ),
    model=model,
    workspace=workspace,
    skills=[
        ast.Skill(name="editing", tools=["fs.readFile", "fs.writeFile", "fs.listDir", "fs.edit"]),
        ast.Skill(name="shell", tools=["exec.run", "exec.shell"]),
        ast.Skill(name="vcs", tools=["git.status", "git.diff", "git.commit"]),
    ],
    platform=platform,
)
```

</TabItem>
</Tabs>

`vystak apply` builds two containers — `coder` (the agent) and `dev` (the workspace) — links them on the shared `vystak-net` network, and wires the agent's tool calls to RPC into the workspace.

## Built-in tools

Declaring a workspace unlocks a tool catalog you can reference from `skills.tools`:

| Namespace | Examples | Purpose |
|-----------|----------|---------|
| `fs.*`    | `fs.readFile`, `fs.writeFile`, `fs.listDir`, `fs.edit` | Filesystem I/O scoped to the workspace |
| `exec.*`  | `exec.run`, `exec.shell` | Run shell commands inside the workspace |
| `git.*`   | `git.status`, `git.diff`, `git.commit` | Version control on the workspace's working tree |
| `search_project` | (alone) | Ripgrep-based code search |

These tools are generated automatically. You don't write Python for them — they're stubs that RPC into the workspace's tool server.

## Persistence modes

The `persistence` field controls how the workspace's filesystem survives container restarts:

| Mode | Behavior | When to use |
|------|----------|-------------|
| `volume` (default) | Backed by a named Docker volume; survives container replacement | Long-running agents that build up state |
| `bind` | Mounted from a host directory (requires `path:`) | Local development against a real repo |
| `ephemeral` | Tmpfs; gone when the container stops | Sandboxed one-off runs |

<Tabs groupId="config-format">
<TabItem value="yaml" label="YAML" default>

```yaml
workspace:
  name: dev
  image: python:3.12-slim
  persistence: bind
  path: /Users/me/projects/my-repo
```

</TabItem>
<TabItem value="python" label="Python">

```python
workspace = ast.Workspace(
    name="dev",
    image="python:3.12-slim",
    persistence="bind",
    path="/Users/me/projects/my-repo",
)
```

</TabItem>
</Tabs>

## Provisioning

Three ways to set up the workspace's environment:

### 1. Pre-built image

<Tabs groupId="config-format">
<TabItem value="yaml" label="YAML" default>

```yaml
workspace:
  name: dev
  image: node:20-slim
```

</TabItem>
<TabItem value="python" label="Python">

```python
workspace = ast.Workspace(name="dev", image="node:20-slim")
```

</TabItem>
</Tabs>

### 2. Run setup commands at deploy time

<Tabs groupId="config-format">
<TabItem value="yaml" label="YAML" default>

```yaml
workspace:
  name: dev
  image: python:3.12-slim
  provision:
    - apt-get update && apt-get install -y git ripgrep
    - pip install ruff pytest
```

</TabItem>
<TabItem value="python" label="Python">

```python
workspace = ast.Workspace(
    name="dev",
    image="python:3.12-slim",
    provision=[
        "apt-get update && apt-get install -y git ripgrep",
        "pip install ruff pytest",
    ],
)
```

</TabItem>
</Tabs>

### 3. Build from a Dockerfile

<Tabs groupId="config-format">
<TabItem value="yaml" label="YAML" default>

```yaml
workspace:
  name: dev
  dockerfile: ./Dockerfile.workspace
```

</TabItem>
<TabItem value="python" label="Python">

```python
workspace = ast.Workspace(name="dev", dockerfile="./Dockerfile.workspace")
```

</TabItem>
</Tabs>

`dockerfile` is mutually exclusive with `image`, `provision`, and `copy` — pick one shape.

## Per-workspace secrets

Secrets declared on a workspace are only delivered into the workspace container. The agent (where the LLM runs) cannot reach them:

<Tabs groupId="config-format">
<TabItem value="yaml" label="YAML" default>

```yaml
workspace:
  name: dev
  image: node:20-slim
  secrets:
    - { name: STRIPE_API_KEY }
```

</TabItem>
<TabItem value="python" label="Python">

```python
workspace = ast.Workspace(
    name="dev",
    image="node:20-slim",
    secrets=[ast.Secret(name="STRIPE_API_KEY")],
)
```

</TabItem>
</Tabs>

This is the v1 isolation pattern: the LLM sees the *result* of `charge_card`, never the API key. Secret-manager backed workspaces require a `vault:` declaration at the project level — Azure Key Vault wiring is documented in [Deploying to Azure](/docs/deploying/azure#secrets--azure-key-vault-recommended); HashiCorp Vault for Docker is the analogous setup.

## Human SSH access

For interactive debugging you can opt into SSH on the workspace:

<Tabs groupId="config-format">
<TabItem value="yaml" label="YAML" default>

```yaml
workspace:
  name: dev
  image: python:3.12-slim
  ssh: true
  ssh_authorized_keys:
    - "ssh-ed25519 AAAA... me@laptop"
  ssh_host_port: 2222
```

</TabItem>
<TabItem value="python" label="Python">

```python
workspace = ast.Workspace(
    name="dev",
    image="python:3.12-slim",
    ssh=True,
    ssh_authorized_keys=["ssh-ed25519 AAAA... me@laptop"],
    ssh_host_port=2222,
)
```

</TabItem>
</Tabs>

`ssh_authorized_keys` (or `ssh_authorized_keys_file`) is required when `ssh: true` — Vystak refuses to deploy a passwordless shell.

## What's next

- [Agents](/docs/concepts/agents) — the agent definition that hosts a workspace
- [Examples: workspace + Vault](/docs/examples/overview) — `examples/docker-workspace-vault/`
- [Examples: Node workspace](/docs/examples/overview) — `examples/docker-workspace-nodejs/`
