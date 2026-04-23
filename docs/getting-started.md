# Getting Started

This guide covers setting up the Vystak monorepo for development. If you want to understand the philosophy behind Vystak first, read the [Principles](principles.md).

## Prerequisites

Install the following tools before proceeding:

| Tool | Minimum Version | Install |
|------|----------------|---------|
| Python | 3.11+ | [python.org](https://www.python.org/downloads/) |
| Node.js | 20+ | [nodejs.org](https://nodejs.org/) |
| uv | latest | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| pnpm | 9.x | `npm install -g pnpm` |
| just | latest | `cargo install just` or `brew install just` |

## Setup

```bash
# Clone the repository
git clone <repo-url>
cd Vystak

# Install Python dependencies (all workspace packages)
uv sync

# Install TypeScript dependencies (all workspace packages)
pnpm install

# Verify everything works
just test
```

## Project Structure

```
Vystak/
├── pyproject.toml              # Python workspace root (uv)
├── pnpm-workspace.yaml         # TypeScript workspace root (pnpm)
├── package.json                # Root TS config and shared dev deps
├── Justfile                    # Cross-language task runner
├── .pre-commit-config.yaml     # Pre-commit hooks (ruff, eslint, prettier)
├── .changeset/                 # Changesets versioning config
├── .github/workflows/          # CI and release pipelines
│
├── packages/python/
│   ├── vystak/             # Core SDK — schema, IR, hash engine, provider base classes
│   ├── vystak-cli/         # CLI tool — init, plan, up, destroy, status, logs
│   ├── vystak-adapter-mastra/  # Mastra framework adapter
│   ├── vystak-provider-docker/ # Docker platform provider
│   └── vystak-channel-api/     # REST API channel adapter
│
├── packages/typescript/
│   ├── tsconfig.base.json      # Shared TypeScript compiler config
│   ├── core/                   # @vystak/core — core SDK
│   ├── cli/                    # @vystak/cli — CLI tool
│   ├── adapter-mastra/         # @vystak/adapter-mastra — Mastra adapter
│   └── provider-docker/        # @vystak/provider-docker — Docker provider
│
└── docs/
```

### How the workspaces work

The monorepo has two independent workspace roots:

- **Python** is managed by **uv**. The root `pyproject.toml` declares `packages/python/*` as workspace members. All Python packages are pip-installable with names like `vystak`, `vystak-cli`, `vystak-adapter-mastra`.

- **TypeScript** is managed by **pnpm**. The `pnpm-workspace.yaml` declares `packages/typescript/*` as workspace members. All TS packages are npm-publishable under the `@vystak` scope.

The **Justfile** coordinates both ecosystems with unified commands.

### Package layout

Every Python package follows this structure:

```
packages/python/<package-name>/
├── pyproject.toml
├── src/<import_name>/
│   ├── __init__.py
│   └── ...
└── tests/
    └── test_*.py
```

Every TypeScript package follows this structure:

```
packages/typescript/<package-name>/
├── package.json
├── tsconfig.json          # extends ../tsconfig.base.json
├── vitest.config.ts
├── src/
│   └── index.ts
└── tests/
    └── index.test.ts
```

## Key Commands

### Cross-language (via Justfile)

| Command | Description |
|---------|-------------|
| `just test` | Run all tests (Python + TypeScript) |
| `just lint` | Lint all code (ruff + eslint) |
| `just typecheck` | Type check all code (pyright + tsc) |
| `just fmt` | Format all code (ruff format + prettier) |
| `just ci` | Run full CI check (lint + typecheck + test) |

Each command has per-ecosystem variants: `just test-python`, `just test-typescript`, etc.

### Single package commands

```bash
# Python — run tests for one package
uv run pytest packages/python/vystak/tests/ -v

# TypeScript — run tests for one package
pnpm --filter @vystak/core test
```

## Adding a New Package

### Python plugin

1. Create the directory structure:

```bash
mkdir -p packages/python/vystak-provider-aws/src/vystak_provider_aws
mkdir -p packages/python/vystak-provider-aws/tests
```

2. Create `packages/python/vystak-provider-aws/pyproject.toml`:

```toml
[project]
name = "vystak-provider-aws"
version = "0.1.0"
description = "Vystak AWS platform provider"
requires-python = ">=3.11"
license = "Apache-2.0"
dependencies = [
    "vystak>=0.1.0",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/vystak_provider_aws"]

[tool.uv.sources]
vystak = { workspace = true }
```

3. Create `src/vystak_provider_aws/__init__.py`:

```python
"""Vystak AWS platform provider."""

__version__ = "0.1.0"
```

4. Add a test and sync:

```bash
uv sync
uv run pytest packages/python/vystak-provider-aws/tests/ -v
```

### TypeScript plugin

1. Create the directory structure:

```bash
mkdir -p packages/typescript/provider-aws/src
mkdir -p packages/typescript/provider-aws/tests
```

2. Create `packages/typescript/provider-aws/package.json`:

```json
{
  "name": "@vystak/provider-aws",
  "version": "0.1.0",
  "description": "Vystak AWS platform provider",
  "type": "module",
  "license": "Apache-2.0",
  "exports": {
    ".": {
      "import": "./dist/index.js",
      "types": "./dist/index.d.ts"
    }
  },
  "files": ["dist"],
  "scripts": {
    "build": "tsc",
    "test": "vitest run",
    "lint": "eslint src/",
    "typecheck": "tsc --noEmit",
    "fmt": "prettier --write src/ tests/"
  },
  "dependencies": {
    "@vystak/core": "workspace:*"
  },
  "devDependencies": {
    "vitest": "^3.0.0",
    "eslint": "^9.0.0",
    "prettier": "^3.4.0"
  }
}
```

3. Create `tsconfig.json` extending the base, add `src/index.ts` and a test.

4. Install and verify:

```bash
pnpm install
pnpm --filter @vystak/provider-aws test
```

## Running Tests

| Scope | Command |
|-------|---------|
| Everything | `just test` |
| All Python | `just test-python` |
| All TypeScript | `just test-typescript` |
| Single Python package | `uv run pytest packages/python/<pkg>/tests/ -v` |
| Single TS package | `pnpm --filter @vystak/<pkg> test` |

## Secrets

Vystak delivers declared secrets into each principal's (agent /
workspace / channel) container environment. The container boundary
provides per-principal isolation: the LLM running in the agent
container cannot read environment variables belonging to a workspace
container, or vice versa.

### Default path — `.env`

For local development, write secrets to a `.env` file in your project
root and declare them on the principal that needs them:

```yaml
agents:
  - name: assistant
    secrets:
      - name: ANTHROPIC_API_KEY
    workspace:
      secrets:
        - name: STRIPE_API_KEY
```

At `vystak apply` time, values resolve from `.env` and are delivered
per-container:

- **Docker:** `.vystak/env/<principal>.env` (chmod 600, gitignored)
  is mounted as the container's `--env-file`.
- **Azure ACA:** values are inlined as `configuration.secrets[]`
  entries referenced per-container via `env[].secretRef`.

No Vault container, no sidecars, no init-file ceremony.

### Opt-in — `Vault`

If you want automatic rotation, an audit log of reads, or shared
secret storage across multiple deploys, declare a `vault:` block:

```yaml
vault:
  name: vystak-vault
  provider: docker     # or azure
  type: vault          # or key-vault on Azure
  mode: deploy         # or external for an existing Vault/KV
```

The container boundary still does the isolation work — Vault adds
operational features (rotation, audit, shared storage). The declared
`secrets:` on agent/workspace/channel are unchanged.

### CLI

- `vystak plan` — preview which secrets will be delivered; on the
  default path, emits an `EnvFiles:` section with per-principal
  resolution counts.
- `vystak secrets list` — show declared secrets and whether each is
  in `.env` / the vault.
- `vystak secrets push` — bootstrap declared secrets from `.env` into
  the vault (vault-declared deploys only).
- `vystak secrets diff` — compare `.env` ↔ `.vystak/env/*.env` ↔ vault.
  Prints only names and status — never values.
- `vystak secrets rotate-ssh <agent>` — regenerate the workspace SSH
  keypair for agent→workspace RPC.
