# Getting Started Documentation — Design Spec

## Overview

Create a contributor-facing getting started guide that orients new developers to the AgentStack monorepo: how to set up their environment, understand the project structure, run commands, and add new packages.

## Audience

Contributors who want to work on AgentStack itself. Not end-users of the SDK (the SDK has no functionality yet).

## Location

`docs/getting-started.md`

## Sections

### 1. Prerequisites

List required tools with minimum versions and install links:
- Python 3.11+
- Node.js 20+
- uv (Python package manager)
- pnpm (Node package manager)
- just (command runner)

### 2. Setup

Step-by-step commands to go from clone to running tests:
- Clone the repo
- Install Python dependencies (`uv sync`)
- Install TypeScript dependencies (`pnpm install`)
- Run the full test suite (`just test`)

### 3. Project Structure

Annotated directory tree showing:
- Root config files and what they do (pyproject.toml, pnpm-workspace.yaml, package.json, Justfile)
- `packages/python/` — 5 Python packages with one-line descriptions
- `packages/typescript/` — 4 TypeScript packages with one-line descriptions
- How the two workspaces are independent but coordinated via Justfile

### 4. Key Commands

Table of Justfile commands with descriptions:
- `just test` — run all tests
- `just lint` — lint all code
- `just typecheck` — type check all code
- `just fmt` — format all code
- `just ci` — run full CI check (lint + typecheck + test)

Plus per-ecosystem commands for working on one side:
- `just test-python`, `just test-typescript`
- `uv run pytest packages/python/<pkg>/tests/ -v` for single package
- `pnpm --filter @agentstack/<pkg> test` for single package

### 5. Adding a New Package

Brief walkthrough for each ecosystem:

**Python plugin:** create directory under `packages/python/`, add pyproject.toml with workspace dependency on core, create src layout, add test, run `uv sync`.

**TypeScript plugin:** create directory under `packages/typescript/`, add package.json with `"@agentstack/core": "workspace:*"`, extend tsconfig.base.json, add vitest config, add test, run `pnpm install`.

### 6. Running Tests

- All tests: `just test`
- Python only: `just test-python`
- TypeScript only: `just test-typescript`
- Single Python package: `uv run pytest packages/python/<pkg>/tests/ -v`
- Single TypeScript package: `pnpm --filter @agentstack/<pkg> test`

## What This Spec Does NOT Cover

- End-user documentation (how to use AgentStack to deploy agents)
- Contribution guidelines (PR process, code review, branching strategy)
- Architecture decision records
- API reference
