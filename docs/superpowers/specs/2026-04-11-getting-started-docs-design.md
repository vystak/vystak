# Getting Started & Principles Documentation — Design Spec

## Overview

Create two documents:
1. A contributor-facing getting started guide that orients new developers to the AgentStack monorepo
2. A standalone principles document that captures AgentStack's core philosophy and design decisions

## Audience

Contributors who want to work on AgentStack itself. Not end-users of the SDK (the SDK has no functionality yet).

## Files

- `docs/getting-started.md` — practical setup and orientation
- `docs/principles.md` — project philosophy and design principles

---

# Document 1: Getting Started

## Location

`docs/getting-started.md`

Links to `docs/principles.md` in its introduction for contributors who want to understand the "why" before the "how".

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

---

# Document 2: Principles

## Location

`docs/principles.md`

## Content

The 7 core principles from the AgentStack philosophy, each with a short explanation and a concrete example of what it means in practice:

### 1. Agents are infrastructure

An agent is a deployable unit with dependencies — models, memory, tools, skills, secrets, compute, and a workspace. Defined, versioned, tested, and deployed with the same rigor as any production service. Not a script. Not a notebook.

### 2. Define once, deploy everywhere

A single agent definition deploys to Docker, AWS AgentCore, Azure Foundry, DigitalOcean Gradient, Kubernetes, or any other platform. The definition is the contract. The platform is a deployment detail.

### 3. Build nothing, integrate everything

AgentStack does not build runtimes, tracing backends, vector stores, session stores, workflow engines, or sandbox environments. It integrates with existing best-in-class products through thin adapter plugins. Every external product is a provider.

### 4. Code over config

Use real programming languages (Python, TypeScript) for agent definitions. Loops, conditionals, functions, type safety, IDE autocomplete. YAML is available as a simple on-ramp but code is the primary API.

### 5. Progressive complexity

Three lines to deploy your first agent. Full infrastructure-as-code when you need it. Complexity is opt-in, never required. Five levels from simple agent definition to fleet management.

### 6. Stateless tool

AgentStack holds no state. No state files, no remote backend, no state locking. The agent definition is the desired state. The platform is the actual state. AgentStack diffs the two using content hashes stored as platform labels.

### 7. The framework is a runtime target, not an abstraction

AgentStack does not abstract frameworks. It targets them. Each framework adapter generates native code using that framework's idioms. No lowest common denominator.

## Closing Section: The Seven Concepts

Brief reference table of the 7 core concepts (Agent, Skill, Channel, Resource, Workspace, Provider, Platform) with one-line descriptions, linking back to the architecture for contributors who want to go deeper.

---

## What This Spec Does NOT Cover

- End-user documentation (how to use AgentStack to deploy agents)
- Contribution guidelines (PR process, code review, branching strategy)
- Architecture decision records
- API reference
