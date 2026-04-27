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

# Build TypeScript packages (emits dist/ for each workspace member).
# typecheck-typescript depends on it because adapter-mastra and
# provider-docker import @vystak/core via its dist/.d.ts; on a fresh
# clone (CI), tsc can't resolve the cross-package import without it.
build-typescript:
    pnpm -r run build

# Type check TypeScript
typecheck-typescript: build-typescript
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

# Sync TypeScript package.json versions to the latest git tag (or argv[1]).
# Python packages use hatch-vcs and read the version from git tags
# directly — no sync needed there.
sync-ts-version version="":
    uv run python scripts/bump_version.py {{version}}

# Cut a release: tag HEAD with v<version> and push the tag.
# release.yml then verifies + publishes everything atomically.
# Usage:  just release 0.2.0
release version:
    @if ! [[ "{{version}}" =~ ^[0-9]+\.[0-9]+\.[0-9]+([-+][a-zA-Z0-9.]+)?$ ]]; then \
        echo "version must be semver (e.g. 0.2.0); got: {{version}}" >&2; exit 1; \
    fi
    @if git rev-parse "v{{version}}" >/dev/null 2>&1; then \
        echo "tag v{{version}} already exists" >&2; exit 1; \
    fi
    git tag -a "v{{version}}" -m "release v{{version}}"
    git push origin "v{{version}}"
    @echo "Tagged + pushed v{{version}} — release.yml will publish."

# Run docs site locally
docs-dev:
    pnpm --filter vystak-docs start

# Build docs site
docs-build:
    pnpm --filter vystak-docs build

# Serve built docs
docs-serve:
    pnpm --filter vystak-docs serve
