# AgentStack Monorepo Scaffold — Design Spec

## Overview

Scaffold a polyglot monorepo for AgentStack — a declarative, platform-agnostic orchestration layer for AI agents. The monorepo hosts both Python and TypeScript packages, each managed by their native ecosystem tooling, with a thin cross-language coordination layer.

## Decisions

| Decision | Choice |
|----------|--------|
| Language ecosystem | Polyglot — full Python + TypeScript from the start |
| Monorepo tooling | pnpm workspaces (TS) + uv workspaces (Python) + Justfile |
| Python packaging | uv workspace, separate pyproject.toml per package |
| TypeScript packaging | pnpm workspace, separate package.json per package |
| npm scope | `@agentstack/*` |
| PyPI naming | `agentstack-*` prefix |
| Testing | pytest (Python) + vitest (TypeScript) |
| CI | GitHub Actions — lint, typecheck, test on PR; publish on release |
| Versioning | Changesets for both ecosystems |
| License | Apache 2.0 |

## Repository Structure

```
AgentsStack/
├── .github/
│   └── workflows/
│       ├── ci.yml
│       └── release.yml
├── packages/
│   ├── python/
│   │   ├── agentstack/
│   │   ├── agentstack-cli/
│   │   ├── agentstack-adapter-mastra/
│   │   ├── agentstack-provider-docker/
│   │   └── agentstack-channel-api/
│   └── typescript/
│       ├── core/
│       ├── cli/
│       ├── adapter-mastra/
│       └── provider-docker/
├── docs/
├── pyproject.toml                    # uv workspace root
├── pnpm-workspace.yaml
├── package.json                      # root TS config (private)
├── Justfile
├── .pre-commit-config.yaml
├── .changeset/
├── LICENSE
└── README.md
```

## Python Packages

### Internal Layout (all packages follow this)

```
packages/python/<package-name>/
├── pyproject.toml
├── src/
│   └── <import_name>/
│       ├── __init__.py
│       └── ...
└── tests/
    └── test_*.py
```

Uses `src/` layout to prevent accidental imports of uninstalled packages.

### agentstack (core SDK)

Import name: `agentstack`

```
src/agentstack/
├── __init__.py
├── schema/           # Agent, Skill, Channel, Resource, Workspace definitions
├── ir/               # Intermediate representation
├── hash/             # Content-addressable hash engine
└── providers/        # Provider base classes
```

The core SDK defines the seven concepts (Agent, Skill, Channel, Resource, Workspace, Provider, Platform), the intermediate representation that adapters consume, and the hash engine for stateless change detection.

### agentstack-cli

Import name: `agentstack_cli`

```
src/agentstack_cli/
├── __init__.py
├── cli.py            # Entry point
└── commands/         # init, plan, up, destroy, status, logs
```

Depends on `agentstack` core. Exposes a CLI entry point (click or typer). Each subcommand is a module in `commands/`.

### agentstack-adapter-mastra

Import name: `agentstack_adapter_mastra`

```
src/agentstack_adapter_mastra/
├── __init__.py
└── adapter.py        # Framework adapter implementation
```

Depends on `agentstack` core. Implements the framework adapter interface to generate native Mastra code from the IR.

### agentstack-provider-docker

Import name: `agentstack_provider_docker`

```
src/agentstack_provider_docker/
├── __init__.py
└── provider.py       # Platform provider implementation
```

Depends on `agentstack` core. Implements the platform provider interface for Docker (Dockerfile generation, container lifecycle, label-based hash storage).

### agentstack-channel-api

Import name: `agentstack_channel_api`

```
src/agentstack_channel_api/
├── __init__.py
└── channel.py        # REST API channel implementation
```

Depends on `agentstack` core. Implements the channel adapter interface for REST API endpoints.

### Python Constraints

- Python 3.11+ minimum
- pytest for testing
- ruff for linting and formatting
- pyright for type checking

## TypeScript Packages

### Internal Layout (all packages follow this)

```
packages/typescript/<package-name>/
├── package.json
├── tsconfig.json     # extends ../tsconfig.base.json
├── src/
│   └── index.ts
└── tests/
    └── index.test.ts
```

All TS packages are ESM-only (`"type": "module"`).

### @agentstack/core

Stubbed. Exports a version constant and core type definitions. One passing test.

### @agentstack/cli

Stubbed. Depends on `@agentstack/core`. Placeholder entry point.

### @agentstack/adapter-mastra

Stubbed. Depends on `@agentstack/core`. Placeholder adapter.

### @agentstack/provider-docker

Stubbed. Depends on `@agentstack/core`. Placeholder provider.

### TypeScript Constraints

- Node 20+
- ESM-only, target ES2022
- Strict TypeScript
- Vitest for testing
- ESLint + Prettier for linting/formatting

### Shared Config

`packages/typescript/tsconfig.base.json` — shared compiler options inherited by all TS packages.

## Workspace Configuration

### Root pyproject.toml (uv workspace)

- Declares workspace members: `packages/python/*`
- Not a package itself — workspace root only
- Shared dev dependencies: pytest, ruff, pyright

### Root pnpm-workspace.yaml

- Declares workspace members: `packages/typescript/*`

### Root package.json

- Private, not publishable
- Shared dev dependencies: vitest, eslint, prettier, typescript, @changesets/cli
- Scripts delegate to Justfile or pnpm commands

### Inter-Package Dependencies

- **Python:** CLI depends on core. Each adapter/provider/channel depends on core. Declared as uv workspace dependencies.
- **TypeScript:** Same pattern. Each package depends on `@agentstack/core` via `"workspace:*"`.

## Justfile (Cross-Language Task Runner)

```
test            run pytest + vitest across all packages
lint            run ruff + eslint
typecheck       run pyright + tsc --noEmit
fmt             run ruff format + prettier
ci              run lint + typecheck + test (what CI calls)
```

## CI / CD

### GitHub Actions CI (`ci.yml`)

- **Triggers:** PR and push to `main`
- **Matrix:** Python 3.11+, Node 20+
- **Steps:** install uv, install pnpm, `just ci`
- **Caching:** uv and pnpm stores

### GitHub Actions Release (`release.yml`)

- **Triggers:** tags matching `v*` or manual dispatch
- **Process:** changesets determines which packages changed
- **Python:** publishes to PyPI via `uv publish`
- **TypeScript:** publishes to npm via `pnpm publish`

### Pre-commit Hooks

- ruff (lint + format) for Python
- eslint + prettier for TypeScript
- Conventional commit message check

### Changesets

- `.changeset/config.json` at root
- Tracks version bumps per package independently
- Generates changelogs on release

## What This Spec Does NOT Cover

- Implementation of any SDK logic, CLI commands, or adapter code
- Agent definition schema design
- Harness architecture
- Skill loading mechanism
- Any runtime behavior

This spec covers only the monorepo scaffold: directory structure, package configs, workspace setup, CI, and tooling.
