# Vystak monorepo task runner

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

# Run full CI check (lint + typecheck + tests, both languages).
# This includes pre-existing baseline failures (lint-typescript needs
# eslint.config.js per package; typecheck-python has ~124 pyright errors)
# and is intended for local development / aspirational green-build work.
ci: lint typecheck test

# What GitHub Actions actually runs — only the four currently-green gates.
# Mirrors the "live gates" list documented in CLAUDE.md. Move recipes
# from this list into ``ci`` (or vice versa) as gates flip green/red.
ci-live: lint-python typecheck-typescript test-python test-typescript

# Run docs site locally
docs-dev:
    pnpm --filter vystak-docs start

# Build docs site
docs-build:
    pnpm --filter vystak-docs build

# Serve built docs
docs-serve:
    pnpm --filter vystak-docs serve
