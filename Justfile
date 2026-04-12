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
