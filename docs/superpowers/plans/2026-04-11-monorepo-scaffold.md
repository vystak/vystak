# AgentStack Monorepo Scaffold Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Scaffold a polyglot monorepo with 5 Python packages and 4 TypeScript packages, workspace tooling, CI, and release automation.

**Architecture:** pnpm workspaces for TypeScript, uv workspaces for Python, Justfile for cross-language orchestration. Each package is independently publishable. GitHub Actions for CI and release.

**Tech Stack:** Python 3.11+, Node 20+, uv, pnpm, pytest, vitest, ruff, pyright, eslint, prettier, changesets, just

---

### Task 1: Root Configuration Files

**Files:**
- Create: `pyproject.toml`
- Create: `pnpm-workspace.yaml`
- Create: `package.json`
- Create: `.gitignore`
- Create: `LICENSE`

- [ ] **Step 1: Create root `.gitignore`**

```gitignore
# Python
__pycache__/
*.py[cod]
*$py.class
*.egg-info/
dist/
build/
.eggs/
*.egg
.venv/
.pytest_cache/
.ruff_cache/
.pyright/

# TypeScript
node_modules/
*.tsbuildinfo
coverage/

# IDE
.idea/
.vscode/
*.swp
*.swo
*~

# OS
.DS_Store
Thumbs.db

# Environment
.env
.env.local
```

- [ ] **Step 2: Create root `pyproject.toml` (uv workspace)**

```toml
[project]
name = "agentstack-workspace"
version = "0.0.0"
description = "AgentStack monorepo workspace root"
requires-python = ">=3.11"

[tool.uv.workspace]
members = ["packages/python/*"]

[tool.uv]
dev-dependencies = [
    "pytest>=8.0",
    "ruff>=0.8",
    "pyright>=1.1",
]

[tool.ruff]
target-version = "py311"
line-length = 100

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM"]

[tool.pyright]
pythonVersion = "3.11"
typeCheckingMode = "standard"
```

- [ ] **Step 3: Create `pnpm-workspace.yaml`**

```yaml
packages:
  - "packages/typescript/*"
```

- [ ] **Step 4: Create root `package.json`**

```json
{
  "name": "agentstack-workspace",
  "private": true,
  "type": "module",
  "engines": {
    "node": ">=20"
  },
  "packageManager": "pnpm@9.15.4",
  "scripts": {
    "test": "pnpm -r run test",
    "lint": "pnpm -r run lint",
    "typecheck": "pnpm -r run typecheck",
    "fmt": "pnpm -r run fmt"
  },
  "devDependencies": {
    "@changesets/cli": "^2.27.0",
    "typescript": "^5.7.0"
  }
}
```

- [ ] **Step 5: Create `LICENSE` (Apache 2.0)**

Download the standard Apache 2.0 license text. Set copyright line to:

```
Copyright 2026 AgentStack Contributors
```

- [ ] **Step 6: Commit**

```bash
git add .gitignore pyproject.toml pnpm-workspace.yaml package.json LICENSE
git commit -m "chore: add root workspace and config files"
```

---

### Task 2: Python Core Package (agentstack)

**Files:**
- Create: `packages/python/agentstack/pyproject.toml`
- Create: `packages/python/agentstack/src/agentstack/__init__.py`
- Create: `packages/python/agentstack/src/agentstack/schema/__init__.py`
- Create: `packages/python/agentstack/src/agentstack/ir/__init__.py`
- Create: `packages/python/agentstack/src/agentstack/hash/__init__.py`
- Create: `packages/python/agentstack/src/agentstack/providers/__init__.py`
- Create: `packages/python/agentstack/tests/test_version.py`

- [ ] **Step 1: Create `packages/python/agentstack/pyproject.toml`**

```toml
[project]
name = "agentstack"
version = "0.1.0"
description = "AgentStack core SDK — declarative AI agent orchestration"
requires-python = ">=3.11"
license = "Apache-2.0"
readme = "README.md"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/agentstack"]
```

- [ ] **Step 2: Create `packages/python/agentstack/src/agentstack/__init__.py`**

```python
"""AgentStack — declarative AI agent orchestration."""

__version__ = "0.1.0"
```

- [ ] **Step 3: Create submodule `__init__.py` files**

Create each of these with a single docstring:

`packages/python/agentstack/src/agentstack/schema/__init__.py`:
```python
"""Agent, Skill, Channel, Resource, Workspace, Provider, Platform definitions."""
```

`packages/python/agentstack/src/agentstack/ir/__init__.py`:
```python
"""Intermediate representation consumed by framework adapters."""
```

`packages/python/agentstack/src/agentstack/hash/__init__.py`:
```python
"""Content-addressable hash engine for stateless change detection."""
```

`packages/python/agentstack/src/agentstack/providers/__init__.py`:
```python
"""Provider base classes for platform and resource provisioning."""
```

- [ ] **Step 4: Write test**

`packages/python/agentstack/tests/test_version.py`:
```python
from agentstack import __version__


def test_version():
    assert __version__ == "0.1.0"
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd /Users/akolodkin/Developer/work/AgentsStack && uv run pytest packages/python/agentstack/tests/ -v`

Expected: PASS — `test_version` passes.

- [ ] **Step 6: Commit**

```bash
git add packages/python/agentstack/
git commit -m "feat: scaffold agentstack core Python package"
```

---

### Task 3: Python CLI Package (agentstack-cli)

**Files:**
- Create: `packages/python/agentstack-cli/pyproject.toml`
- Create: `packages/python/agentstack-cli/src/agentstack_cli/__init__.py`
- Create: `packages/python/agentstack-cli/src/agentstack_cli/cli.py`
- Create: `packages/python/agentstack-cli/src/agentstack_cli/commands/__init__.py`
- Create: `packages/python/agentstack-cli/tests/test_version.py`

- [ ] **Step 1: Create `packages/python/agentstack-cli/pyproject.toml`**

```toml
[project]
name = "agentstack-cli"
version = "0.1.0"
description = "AgentStack CLI — manage and deploy AI agents"
requires-python = ">=3.11"
license = "Apache-2.0"
dependencies = [
    "agentstack>=0.1.0",
]

[project.scripts]
agentstack = "agentstack_cli.cli:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/agentstack_cli"]

[tool.uv.sources]
agentstack = { workspace = true }
```

- [ ] **Step 2: Create `packages/python/agentstack-cli/src/agentstack_cli/__init__.py`**

```python
"""AgentStack CLI — manage and deploy AI agents."""

__version__ = "0.1.0"
```

- [ ] **Step 3: Create `packages/python/agentstack-cli/src/agentstack_cli/cli.py`**

```python
"""CLI entry point."""


def main() -> None:
    print(f"agentstack v{__version__}")


if __name__ == "__main__":
    from agentstack_cli import __version__

    main()
```

Wait — the import needs to be at the top for the normal path. Fix:

```python
"""CLI entry point."""

from agentstack_cli import __version__


def main() -> None:
    print(f"agentstack v{__version__}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Create `packages/python/agentstack-cli/src/agentstack_cli/commands/__init__.py`**

```python
"""CLI subcommands: init, plan, up, destroy, status, logs."""
```

- [ ] **Step 5: Write test**

`packages/python/agentstack-cli/tests/test_version.py`:
```python
from agentstack_cli import __version__


def test_version():
    assert __version__ == "0.1.0"
```

- [ ] **Step 6: Run test to verify it passes**

Run: `uv run pytest packages/python/agentstack-cli/tests/ -v`

Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add packages/python/agentstack-cli/
git commit -m "feat: scaffold agentstack-cli Python package"
```

---

### Task 4: Python Plugin Packages (adapter-mastra, provider-docker, channel-api)

**Files:**
- Create: `packages/python/agentstack-adapter-mastra/pyproject.toml`
- Create: `packages/python/agentstack-adapter-mastra/src/agentstack_adapter_mastra/__init__.py`
- Create: `packages/python/agentstack-adapter-mastra/src/agentstack_adapter_mastra/adapter.py`
- Create: `packages/python/agentstack-adapter-mastra/tests/test_version.py`
- Create: `packages/python/agentstack-provider-docker/pyproject.toml`
- Create: `packages/python/agentstack-provider-docker/src/agentstack_provider_docker/__init__.py`
- Create: `packages/python/agentstack-provider-docker/src/agentstack_provider_docker/provider.py`
- Create: `packages/python/agentstack-provider-docker/tests/test_version.py`
- Create: `packages/python/agentstack-channel-api/pyproject.toml`
- Create: `packages/python/agentstack-channel-api/src/agentstack_channel_api/__init__.py`
- Create: `packages/python/agentstack-channel-api/src/agentstack_channel_api/channel.py`
- Create: `packages/python/agentstack-channel-api/tests/test_version.py`

- [ ] **Step 1: Create agentstack-adapter-mastra**

`packages/python/agentstack-adapter-mastra/pyproject.toml`:
```toml
[project]
name = "agentstack-adapter-mastra"
version = "0.1.0"
description = "AgentStack Mastra framework adapter"
requires-python = ">=3.11"
license = "Apache-2.0"
dependencies = [
    "agentstack>=0.1.0",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/agentstack_adapter_mastra"]

[tool.uv.sources]
agentstack = { workspace = true }
```

`packages/python/agentstack-adapter-mastra/src/agentstack_adapter_mastra/__init__.py`:
```python
"""AgentStack Mastra framework adapter."""

__version__ = "0.1.0"
```

`packages/python/agentstack-adapter-mastra/src/agentstack_adapter_mastra/adapter.py`:
```python
"""Mastra framework adapter implementation."""
```

`packages/python/agentstack-adapter-mastra/tests/test_version.py`:
```python
from agentstack_adapter_mastra import __version__


def test_version():
    assert __version__ == "0.1.0"
```

- [ ] **Step 2: Create agentstack-provider-docker**

`packages/python/agentstack-provider-docker/pyproject.toml`:
```toml
[project]
name = "agentstack-provider-docker"
version = "0.1.0"
description = "AgentStack Docker platform provider"
requires-python = ">=3.11"
license = "Apache-2.0"
dependencies = [
    "agentstack>=0.1.0",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/agentstack_provider_docker"]

[tool.uv.sources]
agentstack = { workspace = true }
```

`packages/python/agentstack-provider-docker/src/agentstack_provider_docker/__init__.py`:
```python
"""AgentStack Docker platform provider."""

__version__ = "0.1.0"
```

`packages/python/agentstack-provider-docker/src/agentstack_provider_docker/provider.py`:
```python
"""Docker platform provider implementation."""
```

`packages/python/agentstack-provider-docker/tests/test_version.py`:
```python
from agentstack_provider_docker import __version__


def test_version():
    assert __version__ == "0.1.0"
```

- [ ] **Step 3: Create agentstack-channel-api**

`packages/python/agentstack-channel-api/pyproject.toml`:
```toml
[project]
name = "agentstack-channel-api"
version = "0.1.0"
description = "AgentStack REST API channel adapter"
requires-python = ">=3.11"
license = "Apache-2.0"
dependencies = [
    "agentstack>=0.1.0",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/agentstack_channel_api"]

[tool.uv.sources]
agentstack = { workspace = true }
```

`packages/python/agentstack-channel-api/src/agentstack_channel_api/__init__.py`:
```python
"""AgentStack REST API channel adapter."""

__version__ = "0.1.0"
```

`packages/python/agentstack-channel-api/src/agentstack_channel_api/channel.py`:
```python
"""REST API channel adapter implementation."""
```

`packages/python/agentstack-channel-api/tests/test_version.py`:
```python
from agentstack_channel_api import __version__


def test_version():
    assert __version__ == "0.1.0"
```

- [ ] **Step 4: Run all Python tests**

Run: `uv run pytest packages/python/ -v`

Expected: all 5 `test_version` tests pass (core, cli, adapter-mastra, provider-docker, channel-api).

- [ ] **Step 5: Commit**

```bash
git add packages/python/agentstack-adapter-mastra/ packages/python/agentstack-provider-docker/ packages/python/agentstack-channel-api/
git commit -m "feat: scaffold Python plugin packages (mastra, docker, api)"
```

---

### Task 5: TypeScript Shared Config

**Files:**
- Create: `packages/typescript/tsconfig.base.json`

- [ ] **Step 1: Create `packages/typescript/tsconfig.base.json`**

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "ESNext",
    "moduleResolution": "bundler",
    "lib": ["ES2022"],
    "strict": true,
    "esModuleInterop": true,
    "skipLibCheck": true,
    "forceConsistentCasingInFileNames": true,
    "declaration": true,
    "declarationMap": true,
    "sourceMap": true,
    "outDir": "dist",
    "rootDir": "src",
    "isolatedModules": true,
    "verbatimModuleSyntax": true
  }
}
```

- [ ] **Step 2: Commit**

```bash
git add packages/typescript/tsconfig.base.json
git commit -m "chore: add shared TypeScript base config"
```

---

### Task 6: TypeScript Core Package (@agentstack/core)

**Files:**
- Create: `packages/typescript/core/package.json`
- Create: `packages/typescript/core/tsconfig.json`
- Create: `packages/typescript/core/vitest.config.ts`
- Create: `packages/typescript/core/src/index.ts`
- Create: `packages/typescript/core/tests/index.test.ts`

- [ ] **Step 1: Create `packages/typescript/core/package.json`**

```json
{
  "name": "@agentstack/core",
  "version": "0.1.0",
  "description": "AgentStack core SDK",
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
  "devDependencies": {
    "vitest": "^3.0.0",
    "eslint": "^9.0.0",
    "prettier": "^3.4.0"
  }
}
```

- [ ] **Step 2: Create `packages/typescript/core/tsconfig.json`**

```json
{
  "extends": "../tsconfig.base.json",
  "compilerOptions": {
    "outDir": "dist",
    "rootDir": "src"
  },
  "include": ["src"]
}
```

- [ ] **Step 3: Create `packages/typescript/core/vitest.config.ts`**

```typescript
import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    include: ["tests/**/*.test.ts"],
  },
});
```

- [ ] **Step 4: Create `packages/typescript/core/src/index.ts`**

```typescript
/** AgentStack core SDK */

export const VERSION = "0.1.0";
```

- [ ] **Step 5: Write test**

`packages/typescript/core/tests/index.test.ts`:
```typescript
import { describe, it, expect } from "vitest";
import { VERSION } from "../src/index.js";

describe("@agentstack/core", () => {
  it("exports version", () => {
    expect(VERSION).toBe("0.1.0");
  });
});
```

- [ ] **Step 6: Install dependencies and run test**

Run:
```bash
cd /Users/akolodkin/Developer/work/AgentsStack && pnpm install
pnpm --filter @agentstack/core test
```

Expected: PASS — 1 test passes.

- [ ] **Step 7: Commit**

```bash
git add packages/typescript/core/ pnpm-lock.yaml
git commit -m "feat: scaffold @agentstack/core TypeScript package"
```

---

### Task 7: TypeScript Plugin Packages (cli, adapter-mastra, provider-docker)

**Files:**
- Create: `packages/typescript/cli/package.json`
- Create: `packages/typescript/cli/tsconfig.json`
- Create: `packages/typescript/cli/vitest.config.ts`
- Create: `packages/typescript/cli/src/index.ts`
- Create: `packages/typescript/cli/tests/index.test.ts`
- Create: `packages/typescript/adapter-mastra/package.json`
- Create: `packages/typescript/adapter-mastra/tsconfig.json`
- Create: `packages/typescript/adapter-mastra/vitest.config.ts`
- Create: `packages/typescript/adapter-mastra/src/index.ts`
- Create: `packages/typescript/adapter-mastra/tests/index.test.ts`
- Create: `packages/typescript/provider-docker/package.json`
- Create: `packages/typescript/provider-docker/tsconfig.json`
- Create: `packages/typescript/provider-docker/vitest.config.ts`
- Create: `packages/typescript/provider-docker/src/index.ts`
- Create: `packages/typescript/provider-docker/tests/index.test.ts`

- [ ] **Step 1: Create @agentstack/cli**

`packages/typescript/cli/package.json`:
```json
{
  "name": "@agentstack/cli",
  "version": "0.1.0",
  "description": "AgentStack CLI",
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

`packages/typescript/cli/tsconfig.json`:
```json
{
  "extends": "../tsconfig.base.json",
  "compilerOptions": {
    "outDir": "dist",
    "rootDir": "src"
  },
  "include": ["src"]
}
```

`packages/typescript/cli/vitest.config.ts`:
```typescript
import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    include: ["tests/**/*.test.ts"],
  },
});
```

`packages/typescript/cli/src/index.ts`:
```typescript
/** AgentStack CLI */

export { VERSION } from "@agentstack/core";
```

`packages/typescript/cli/tests/index.test.ts`:
```typescript
import { describe, it, expect } from "vitest";
import { VERSION } from "../src/index.js";

describe("@agentstack/cli", () => {
  it("re-exports core version", () => {
    expect(VERSION).toBe("0.1.0");
  });
});
```

- [ ] **Step 2: Create @agentstack/adapter-mastra**

`packages/typescript/adapter-mastra/package.json`:
```json
{
  "name": "@agentstack/adapter-mastra",
  "version": "0.1.0",
  "description": "AgentStack Mastra framework adapter",
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

`packages/typescript/adapter-mastra/tsconfig.json`:
```json
{
  "extends": "../tsconfig.base.json",
  "compilerOptions": {
    "outDir": "dist",
    "rootDir": "src"
  },
  "include": ["src"]
}
```

`packages/typescript/adapter-mastra/vitest.config.ts`:
```typescript
import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    include: ["tests/**/*.test.ts"],
  },
});
```

`packages/typescript/adapter-mastra/src/index.ts`:
```typescript
/** AgentStack Mastra framework adapter */

export { VERSION } from "@agentstack/core";
```

`packages/typescript/adapter-mastra/tests/index.test.ts`:
```typescript
import { describe, it, expect } from "vitest";
import { VERSION } from "../src/index.js";

describe("@agentstack/adapter-mastra", () => {
  it("re-exports core version", () => {
    expect(VERSION).toBe("0.1.0");
  });
});
```

- [ ] **Step 3: Create @agentstack/provider-docker**

`packages/typescript/provider-docker/package.json`:
```json
{
  "name": "@agentstack/provider-docker",
  "version": "0.1.0",
  "description": "AgentStack Docker platform provider",
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

`packages/typescript/provider-docker/tsconfig.json`:
```json
{
  "extends": "../tsconfig.base.json",
  "compilerOptions": {
    "outDir": "dist",
    "rootDir": "src"
  },
  "include": ["src"]
}
```

`packages/typescript/provider-docker/vitest.config.ts`:
```typescript
import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    include: ["tests/**/*.test.ts"],
  },
});
```

`packages/typescript/provider-docker/src/index.ts`:
```typescript
/** AgentStack Docker platform provider */

export { VERSION } from "@agentstack/core";
```

`packages/typescript/provider-docker/tests/index.test.ts`:
```typescript
import { describe, it, expect } from "vitest";
import { VERSION } from "../src/index.js";

describe("@agentstack/provider-docker", () => {
  it("re-exports core version", () => {
    expect(VERSION).toBe("0.1.0");
  });
});
```

- [ ] **Step 4: Install and run all TS tests**

Run:
```bash
cd /Users/akolodkin/Developer/work/AgentsStack && pnpm install
pnpm -r run test
```

Expected: all 4 TS test suites pass (core, cli, adapter-mastra, provider-docker).

- [ ] **Step 5: Commit**

```bash
git add packages/typescript/cli/ packages/typescript/adapter-mastra/ packages/typescript/provider-docker/ pnpm-lock.yaml
git commit -m "feat: scaffold TypeScript plugin packages (cli, mastra, docker)"
```

---

### Task 8: Justfile

**Files:**
- Create: `Justfile`

- [ ] **Step 1: Create `Justfile`**

```just
# AgentStack monorepo task runner

# Run all tests
test: test-python test-typescript

# Run Python tests
test-python:
    uv run pytest packages/python/ -v

# Run TypeScript tests
test-typescript:
    pnpm -r run test

# Lint all code
lint: lint-python lint-typescript

# Lint Python
lint-python:
    uv run ruff check packages/python/

# Lint TypeScript
lint-typescript:
    pnpm -r run lint

# Type check all code
typecheck: typecheck-python typecheck-typescript

# Type check Python
typecheck-python:
    uv run pyright packages/python/

# Type check TypeScript
typecheck-typescript:
    pnpm -r run typecheck

# Format all code
fmt: fmt-python fmt-typescript

# Format Python
fmt-python:
    uv run ruff format packages/python/

# Format TypeScript
fmt-typescript:
    pnpm -r run fmt

# Run full CI check (what GitHub Actions runs)
ci: lint typecheck test
```

- [ ] **Step 2: Verify `just test` works**

Run: `cd /Users/akolodkin/Developer/work/AgentsStack && just test`

Expected: all Python and TypeScript tests pass.

- [ ] **Step 3: Commit**

```bash
git add Justfile
git commit -m "chore: add Justfile for cross-language task running"
```

---

### Task 9: Pre-commit Hooks

**Files:**
- Create: `.pre-commit-config.yaml`

- [ ] **Step 1: Create `.pre-commit-config.yaml`**

```yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.8.6
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format

  - repo: https://github.com/pre-commit/mirrors-eslint
    rev: v9.17.0
    hooks:
      - id: eslint
        files: \.tsx?$
        types: [file]
        additional_dependencies:
          - eslint@9.17.0

  - repo: https://github.com/pre-commit/mirrors-prettier
    rev: v4.0.0-alpha.8
    hooks:
      - id: prettier
        files: \.(ts|tsx|json|yaml|yml|md)$

  - repo: https://github.com/compilerla/conventional-pre-commit
    rev: v4.0.0
    hooks:
      - id: conventional-pre-commit
        stages: [commit-msg]
```

- [ ] **Step 2: Commit**

```bash
git add .pre-commit-config.yaml
git commit -m "chore: add pre-commit hook configuration"
```

---

### Task 10: Changesets Configuration

**Files:**
- Create: `.changeset/config.json`

- [ ] **Step 1: Create `.changeset/config.json`**

```json
{
  "$schema": "https://unpkg.com/@changesets/config@3.0.0/schema.json",
  "changelog": "@changesets/cli/changelog",
  "commit": false,
  "fixed": [],
  "linked": [],
  "access": "public",
  "baseBranch": "main",
  "updateInternalDependencies": "patch",
  "ignore": []
}
```

- [ ] **Step 2: Commit**

```bash
git add .changeset/
git commit -m "chore: add changesets versioning configuration"
```

---

### Task 11: GitHub Actions CI

**Files:**
- Create: `.github/workflows/ci.yml`

- [ ] **Step 1: Create `.github/workflows/ci.yml`**

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  ci:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.11", "3.12", "3.13"]
        node-version: ["20", "22"]

    steps:
      - uses: actions/checkout@v4

      - name: Install uv
        uses: astral-sh/setup-uv@v5
        with:
          enable-cache: true

      - name: Set up Python ${{ matrix.python-version }}
        run: uv python install ${{ matrix.python-version }}

      - name: Install pnpm
        uses: pnpm/action-setup@v4

      - name: Set up Node ${{ matrix.node-version }}
        uses: actions/setup-node@v4
        with:
          node-version: ${{ matrix.node-version }}
          cache: pnpm

      - name: Install just
        uses: extractions/setup-just@v2

      - name: Install Python dependencies
        run: uv sync

      - name: Install TypeScript dependencies
        run: pnpm install --frozen-lockfile

      - name: Run CI checks
        run: just ci
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: add GitHub Actions CI workflow"
```

---

### Task 12: GitHub Actions Release

**Files:**
- Create: `.github/workflows/release.yml`

- [ ] **Step 1: Create `.github/workflows/release.yml`**

```yaml
name: Release

on:
  push:
    tags:
      - "v*"
  workflow_dispatch:

jobs:
  release:
    runs-on: ubuntu-latest
    permissions:
      contents: write
      id-token: write

    steps:
      - uses: actions/checkout@v4

      - name: Install uv
        uses: astral-sh/setup-uv@v5
        with:
          enable-cache: true

      - name: Set up Python
        run: uv python install 3.13

      - name: Install pnpm
        uses: pnpm/action-setup@v4

      - name: Set up Node
        uses: actions/setup-node@v4
        with:
          node-version: "22"
          cache: pnpm
          registry-url: "https://registry.npmjs.org"

      - name: Install dependencies
        run: |
          uv sync
          pnpm install --frozen-lockfile

      - name: Build TypeScript packages
        run: pnpm -r run build

      - name: Publish Python packages to PyPI
        run: |
          for pkg in packages/python/*/; do
            if [ -f "$pkg/pyproject.toml" ]; then
              uv build --directory "$pkg"
              uv publish --directory "$pkg"
            fi
          done
        env:
          UV_PUBLISH_TOKEN: ${{ secrets.PYPI_TOKEN }}

      - name: Publish TypeScript packages to npm
        run: pnpm -r publish --no-git-checks --access public
        env:
          NODE_AUTH_TOKEN: ${{ secrets.NPM_TOKEN }}
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/release.yml
git commit -m "ci: add GitHub Actions release workflow"
```

---

### Task 13: Final Verification

- [ ] **Step 1: Run full CI locally**

Run: `cd /Users/akolodkin/Developer/work/AgentsStack && just test`

Expected: all Python and TypeScript tests pass.

- [ ] **Step 2: Verify Python workspace**

Run: `uv tree`

Expected: shows all 5 Python packages and their dependency relationships.

- [ ] **Step 3: Verify TypeScript workspace**

Run: `pnpm list -r`

Expected: shows all 4 TypeScript packages and their workspace dependencies.

- [ ] **Step 4: Verify project structure**

Run: `find packages -type f -name "*.py" -o -name "*.ts" -o -name "pyproject.toml" -o -name "package.json" -o -name "tsconfig.json" | sort`

Expected: all files from the spec are present.
