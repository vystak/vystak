# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Monorepo layout

Dual-language monorepo coordinated by `just`:

- **Python workspace** (`uv`) — root `pyproject.toml` declares `packages/python/*` as workspace members. Python 3.11+.
- **TypeScript workspace** (`pnpm`) — `pnpm-workspace.yaml` declares `packages/typescript/*` and `website/`. Node 20+.

The `Justfile` and lowercase `justfile` are duplicates — both work. Use `just <recipe>`.

## Common commands

```bash
# Setup
uv sync                 # install Python deps (all workspace packages editable)
pnpm install            # install TS deps

# Full CI parity (what GitHub Actions runs)
just ci                 # lint + typecheck + test, both languages

# Lint / format / typecheck
just lint-python        # uv run ruff check packages/python/
just fmt-python         # uv run ruff format packages/python/
just typecheck-python   # uv run pyright packages/python/
just lint-typescript    # pnpm -r run lint
just typecheck-typescript

# Tests
just test-python        # uv run pytest packages/python/ -v
just test-typescript    # pnpm -r run test

# Single test / single file
uv run pytest packages/python/vystak/tests/test_agent.py -v
uv run pytest packages/python/vystak/tests/test_agent.py::TestAgent::test_name
uv run pytest packages/python/ -k "test_hasher"       # by name pattern

# Docs site (Docusaurus under website/)
just docs-dev           # pnpm --filter vystak-docs start
just docs-build
```

## Known pre-existing CI issues

As of main (`f82c342`), `just ci` does **not** fully green because of issues unrelated to any specific PR:

- **`lint-typescript`** fails — ESLint 9 requires `eslint.config.js`, missing in `packages/typescript/cli` and `packages/typescript/core`.
- **`typecheck-python`** fails with ~124 pyright errors, mostly Pydantic-style test fixtures missing required fields (`name=`, `provider=`, `type=`). Never ran in CI before 2026-04-16 because lint-python blocked it first.

`just lint-python`, `just test-python`, `just typecheck-typescript`, `just test-typescript` all pass. When adding work, assume these four gates are the live ones.

## Architecture — three orthogonal axes

The core design idea (see `docs/principles.md`): an Agent definition is compiled against three independent choices, none of which abstracts the others:

```
Agent Schema (Pydantic)
    ├── Framework Adapter  — HOW the agent thinks  (vystak-adapter-langchain)
    ├── Platform Provider  — WHERE it runs         (vystak-provider-docker, vystak-provider-azure)
    └── Channel Adapter    — HOW users reach it    (vystak-channel-api, vystak-gateway)
```

Adapters generate **native framework code** as strings, not runtime abstractions. `vystak-adapter-langchain` emits idiomatic LangGraph + FastAPI source for each agent.

## Core packages (Python)

- **`vystak`** — schema models, hash engine, provisioning graph, provider ABCs, stores.
  - `vystak.schema/` — Pydantic `Agent`, `Model`, `Provider`, `Platform`, `Channel`, `Service`, `Skill`, `Workspace`, `Secret`, `Mcp`. This is the contract.
  - `vystak.hash/` — content-addressable hashing (`AgentHashTree`). Used for **hash-based change detection** — no state files. `vystak plan` compares hash of definition to hash stored as a platform label.
  - `vystak.provisioning/` — `ProvisionGraph` is a DAG of `Provisionable` nodes with `depends_on`, `provision(context)`, `health_check()`, `destroy()`. Providers build a graph, topologically sort, run nodes, thread results through `context`.
  - `vystak.providers/` — base classes: `PlatformProvider`, `FrameworkAdapter`, `ChannelAdapter`, `DeployPlan`, `DeployResult`, `GeneratedCode`.
- **`vystak-cli`** — `vystak init | plan | apply | destroy | status | logs`. Loads agent definitions via `vystak_cli.loader` (YAML or Python file).
- **`vystak-adapter-langchain`** — generates LangGraph react-agent + FastAPI server. Also emits A2A protocol endpoints.
- **`vystak-provider-docker`** — `DockerProvider.apply()` builds a `ProvisionGraph` with ACR-free container/volume nodes for Postgres/SQLite.
- **`vystak-provider-azure`** — same pattern for Azure Container Apps: `ResourceGroupNode → LogAnalyticsNode → ACRNode → ACAEnvironmentNode → ContainerAppNode`, plus `AzurePostgresNode`.
- **`vystak-gateway`** — FastAPI service providing OpenAI-compatible `/v1/chat/completions` + `/v1/responses`, Slack Socket Mode runner, agent discovery, proxy routing.
- **`vystak-chat`** — Rich/prompt-toolkit terminal REPL (`vystak-chat`), slash commands, streaming, session history.
- **`vystak-adapter-mastra`**, **`vystak-channel-api`** — stubs.

Python TS packages (`@vystak/core`, `@vystak/cli`, `@vystak/adapter-mastra`, `@vystak/provider-docker`) are currently stubs — TS port is not yet implemented.

## A2A protocol (agent-to-agent)

Every agent deployed by the LangChain adapter exposes Google A2A endpoints on its HTTP port:
- `GET /.well-known/agent.json` — Agent Card
- `POST /a2a` with JSON-RPC methods `tasks/send`, `tasks/sendSubscribe` (SSE), `tasks/get`, `tasks/cancel`

Multi-agent setups (`examples/multi-agent/`) call peers via `httpx` + A2A JSON-RPC inside tool functions. Gateway also aggregates multiple agents under one OpenAI-compatible endpoint.

## Codegen modules — load-bearing quirks

Two modules emit literal Python source as strings, producing long lines by nature:

- `packages/python/vystak-adapter-langchain/src/vystak_adapter_langchain/a2a.py`
- `packages/python/vystak-adapter-langchain/src/vystak_adapter_langchain/templates.py`

`pyproject.toml` has `per-file-ignores` for **E501** on these files. Do **not** remove the ignores or try to mechanically break lines inside the generated source — that's intentionally intact framework code.

## Test-mock import quirks

Several tests patch module attributes that are imported at module level but not otherwise used (`ruff` will want to F401-remove them):

- `vystak_provider_docker.network` — `import docker` (patched by `test_network.py`)
- `vystak_provider_docker.resources` — `import docker` + `import docker.errors` (patched by `test_resources.py`)

These have `# noqa: F401 — re-exported for test patching` comments. **Do not remove** these imports even if ruff flags them as unused.

## Schema contract

`vystak.schema.Agent` is the authoritative shape. Everything generates *from* this — codegen, provisioning, hashing, validation. Adding fields means:
1. Add to the Pydantic model under `vystak/schema/`.
2. Update the hash contribution if the new field affects deploy identity (see `vystak/hash/tree.py`).
3. Update relevant adapter codegen (`vystak-adapter-langchain/templates.py`) to consume the new field.
4. Update test fixtures across packages.

YAML schema is loaded via `vystak.schema.loader.load_agent`; Python files are loaded as modules with an `agent = ...` module-level binding (see `vystak-cli/src/vystak_cli/loader.py`).

## Examples

`examples/` contains real agent configurations exercising different features (multi-agent, MCP tools, Postgres sessions, Azure, memory). When modifying core behavior, update or run the matching example to verify end-to-end.

## Secrets and sensitive data

This is a **public** repo. Every commit is indexable by credential-harvesting bots within minutes.

**Scan the staged diff before any `git commit`.** Look for:

- Real-format API keys: `sk-ant-api03-*`, `sk-cp-*`, `sk-proj-*`, `sk-[A-Za-z0-9]{48}`, `ghp_/gho_/ghs_*`, `xoxb-/xapp-*` with high entropy, `AKIA[0-9A-Z]{16}`, `AIza[0-9A-Za-z_-]{35}`, Anthropic/OpenAI-style tokens
- UUIDs `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx` that could be Azure subscription/tenant/client/object IDs, AWS account IDs, or GCP project IDs
- Connection strings (`postgresql://`, `mongodb://`, etc.) with non-placeholder passwords
- `-----BEGIN * PRIVATE KEY-----`, JWTs (`eyJ...`), bearer tokens
- Local filesystem paths like `/Users/<name>/...` or `C:\Users\...` — substitute `~` or repo-relative paths
- Internal hostnames (`.local`, `.internal`, `.corp`), non-default private IPs tied to real infra

**In `examples/` use placeholders.** Established convention: `YOUR_SUBSCRIPTION_ID`, `<your-api-key>`, template `.env.example` with `your-*-api-key-here`. The placeholder should be invalid enough that accidental execution fails fast.

**In tests use obvious fakes:** `testpass`, `pw`, `test-sub-123`, `env-sub-456`, `cli-sub-789`, `xoxb-test`, `xapp-test`, `mock-*`, `fake-*`. These are the repo's existing test-fixture conventions.

**Known-clean (don't flag):** `*@users.noreply.github.com` and `noreply@anthropic.com` (git authorship — never flag a commit author/committer email), `user-00000000-0000-0000-0000-000000000001` in `vystak-chat/config.py`, `claude-sonnet-4-20250514` / `MiniMax-M2.7` (model names), `NamedModel` / `Secret` / `password` field *names* in schema code.

**If you find a real credential already committed:**
1. **Alert the user immediately** — do not bundle the finding into an end-of-task summary. Rotation is a user action and is time-sensitive.
2. Do not commit a "fix" that just overwrites the value in HEAD — the old blob stays in history.
3. Proven remediation path in this repo: `brew install git-filter-repo`, then `git filter-repo --replace-text /tmp/replacements.txt` with `pattern==>replacement` lines (and/or `--path <dir> --invert-paths`). Re-add `origin` (filter-repo strips it), then `git push --force origin main`.
4. Flag residual exposure: GitHub's `refs/pull/*/head` refs are immutable, and unreachable objects linger in GitHub's cache for ~90 days. For anything genuinely critical, tell the user to file a GitHub support ticket requesting GC.

## Project status

- Renamed from **AgentStack → Vystak** (commit history still shows `AgentStack` in older messages).
- Legacy `.agentstack/` output path is retained in `.gitignore` alongside new `.vystak/`.
- Package names on PyPI: `vystak`, `vystak-cli`, `vystak-adapter-langchain`, `vystak-provider-docker`, `vystak-provider-azure`, `vystak-gateway`, `vystak-chat`.
- TS package `vystak` (CLI) is published to npm; other TS packages are stubs.
