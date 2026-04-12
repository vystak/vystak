# Getting Started

This guide covers setting up the AgentStack monorepo for development. If you want to understand the philosophy behind AgentStack first, read the [Principles](principles.md).

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
cd AgentsStack

# Install Python dependencies (all workspace packages)
uv sync

# Install TypeScript dependencies (all workspace packages)
pnpm install

# Verify everything works
just test
```

## Project Structure

```
AgentsStack/
├── pyproject.toml              # Python workspace root (uv)
├── pnpm-workspace.yaml         # TypeScript workspace root (pnpm)
├── package.json                # Root TS config and shared dev deps
├── Justfile                    # Cross-language task runner
├── .pre-commit-config.yaml     # Pre-commit hooks (ruff, eslint, prettier)
├── .changeset/                 # Changesets versioning config
├── .github/workflows/          # CI and release pipelines
│
├── packages/python/
│   ├── agentstack/             # Core SDK — schema, IR, hash engine, provider base classes
│   ├── agentstack-cli/         # CLI tool — init, plan, up, destroy, status, logs
│   ├── agentstack-adapter-mastra/  # Mastra framework adapter
│   ├── agentstack-provider-docker/ # Docker platform provider
│   └── agentstack-channel-api/     # REST API channel adapter
│
├── packages/typescript/
│   ├── tsconfig.base.json      # Shared TypeScript compiler config
│   ├── core/                   # @agentstack/core — core SDK
│   ├── cli/                    # @agentstack/cli — CLI tool
│   ├── adapter-mastra/         # @agentstack/adapter-mastra — Mastra adapter
│   └── provider-docker/        # @agentstack/provider-docker — Docker provider
│
└── docs/
```

### How the workspaces work

The monorepo has two independent workspace roots:

- **Python** is managed by **uv**. The root `pyproject.toml` declares `packages/python/*` as workspace members. All Python packages are pip-installable with names like `agentstack`, `agentstack-cli`, `agentstack-adapter-mastra`.

- **TypeScript** is managed by **pnpm**. The `pnpm-workspace.yaml` declares `packages/typescript/*` as workspace members. All TS packages are npm-publishable under the `@agentstack` scope.

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
uv run pytest packages/python/agentstack/tests/ -v

# TypeScript — run tests for one package
pnpm --filter @agentstack/core test
```

## Adding a New Package

### Python plugin

1. Create the directory structure:

```bash
mkdir -p packages/python/agentstack-provider-aws/src/agentstack_provider_aws
mkdir -p packages/python/agentstack-provider-aws/tests
```

2. Create `packages/python/agentstack-provider-aws/pyproject.toml`:

```toml
[project]
name = "agentstack-provider-aws"
version = "0.1.0"
description = "AgentStack AWS platform provider"
requires-python = ">=3.11"
license = "Apache-2.0"
dependencies = [
    "agentstack>=0.1.0",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/agentstack_provider_aws"]

[tool.uv.sources]
agentstack = { workspace = true }
```

3. Create `src/agentstack_provider_aws/__init__.py`:

```python
"""AgentStack AWS platform provider."""

__version__ = "0.1.0"
```

4. Add a test and sync:

```bash
uv sync
uv run pytest packages/python/agentstack-provider-aws/tests/ -v
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
  "name": "@agentstack/provider-aws",
  "version": "0.1.0",
  "description": "AgentStack AWS platform provider",
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
    "@agentstack/core": "workspace:*"
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
pnpm --filter @agentstack/provider-aws test
```

## Running Tests

| Scope | Command |
|-------|---------|
| Everything | `just test` |
| All Python | `just test-python` |
| All TypeScript | `just test-typescript` |
| Single Python package | `uv run pytest packages/python/<pkg>/tests/ -v` |
| Single TS package | `pnpm --filter @agentstack/<pkg> test` |
