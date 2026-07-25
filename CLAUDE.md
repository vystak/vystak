# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Monorepo layout

Dual-language monorepo coordinated by `just`:

- **Python workspace** (`uv`) — root `pyproject.toml` declares `packages/python/*` as workspace members. Python 3.11+.
- **TypeScript workspace** (`pnpm`) — `pnpm-workspace.yaml` declares `packages/typescript/*` and `website/`. Node 20+. All TS packages are 3-line stubs except `vystak-panel`, a real Next.js app; the rest of the implementation is Python.

The `Justfile` and lowercase `justfile` are duplicates — both work. Use `just <recipe>`.

## Common commands

```bash
# Setup
uv sync                 # install Python deps (all workspace packages editable)
pnpm install            # install TS deps

# What GitHub Actions runs — the four currently-green gates
just ci-live            # lint-python + typecheck-typescript + test-python + test-typescript

# Full check incl. known-red gates (aspirational; see "Known pre-existing CI issues")
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
uv run pytest packages/python/vystak/tests/test_agent.py::TestAgent::test_minimal
uv run pytest packages/python/ -k "hash_tree"         # by name pattern

# Opt-in Docker integration tests — spin up real containers
uv run pytest -m docker -v           # runs only docker-marked tests
# (Default `just test-python` excludes them — root addopts excludes the
#  `docker` marker and every `release_*` marker.)

# Release-tier matrix from test_plan.md — each cell is a full
# deploy → verify → destroy lifecycle pytest. Gated cells auto-skip.
uv run pytest packages/python/vystak-provider-docker/tests/release/ -v \
  -m "release_smoke or release_integration or release_live_chat"

# Docs site (Docusaurus under website/)
just docs-dev           # pnpm --filter vystak-docs start
just docs-build
just docs-serve

# Cut a release: tags v<version>, release.yml publishes to PyPI + npm
just release 0.2.0
```

## Known pre-existing CI issues

As of main (`2edb7a0`), `just ci` does **not** fully green because of long-standing baseline issues:

- **`lint-typescript`** fails — ESLint 9 requires `eslint.config.js`, missing in the TS packages.
- **`typecheck-python`** fails — 370 pyright errors at last count (the number drifts; in-repo comments citing ~124 or ~300 are older snapshots). Mostly two patterns: (1) Pydantic-style test fixtures missing required fields; (2) `Optional` member access without narrowing (e.g. `agent.compaction.mode` on `Compaction | None`).

`just lint-python`, `just test-python`, `just typecheck-typescript`, `just test-typescript` all pass — these four are `just ci-live`, which is exactly what `.github/workflows/ci.yml` runs (matrix: Python 3.11–3.13 × Node 20/22). When adding work, assume these four gates are the live ones. Release tests never run in GitHub Actions.

## Release tests (matrix from test_plan.md)

Test cells live under `tests/release/` in each provider package and exercise
the full deploy → verify → destroy lifecycle. The canonical reference is
`test_plan.md` (repo root): **stack × secrets × channel × transport**, cells
D1–D8 (Docker) and A1–A8 (Azure), plus extra lifecycle cells beyond the grid:

- Docker (`vystak-provider-docker/tests/release/`, 15 files): `test_D1..D8_*`,
  `test_heartbeat_v2.py`, `test_template_smoke.py`, `test_skills_folder.py`,
  `test_live_chat.py`, and three Postgres variants (`test_sessions_postgres.py`,
  `test_memory_postgres.py`, `test_sessions_and_memory_postgres.py`).
- Azure (`vystak-provider-azure/tests/release/`, 8 files): `test_A1..A8_*`.

Markers (all gated — default `pytest` excludes them; registered in root `pyproject.toml`):

| Marker | What | Prereqs |
|---|---|---|
| `release_smoke` | Must-pass release gate (Docker cells + template smoke). | Docker daemon |
| `release_integration` | Compose two+ axes: Postgres variants, heartbeat, NATS/stream. | Docker daemon |
| `release_smoke_azure` | Azure smoke. | `AZURE_SUBSCRIPTION_ID` + `az login` |
| `release_slack` | Slack-channel cells. | `SLACK_BOT_TOKEN` + `SLACK_APP_TOKEN` |
| `release_discord` | Discord-channel cells. | `DISCORD_BOT_TOKEN` |
| `release_live_chat` | Real LLM round-trip (single cell). | Real `ANTHROPIC_API_KEY` + `ANTHROPIC_API_URL` in shell env (sentinel values auto-skip) |

Common invocations:

```bash
# Full local Docker suite (auto-skips gated cells)
uv run pytest packages/python/vystak-provider-docker/tests/release/ -v \
  -m "release_smoke or release_integration or release_live_chat"

# Single cell
uv run pytest .../test_D1_docker_default_chat_http.py -v -m release_smoke

# With Slack tokens
export SLACK_BOT_TOKEN=xoxb-... SLACK_APP_TOKEN=xapp-...
uv run pytest packages/python/vystak-provider-docker/tests/release/ -v \
  -m "release_integration or release_slack"

# Live LLM round-trip (costs ~pennies; asserts response contains "pong")
export ANTHROPIC_API_KEY=sk-ant-...
export ANTHROPIC_API_URL=https://api.anthropic.com
uv run pytest .../test_live_chat.py -v -m release_live_chat

# Azure smoke (3–5 min per cell; cleans up its own disposable RG)
az login && export AZURE_SUBSCRIPTION_ID=...
uv run pytest packages/python/vystak-provider-azure/tests/release/ -v \
  -m release_smoke_azure
```

Shared fixtures (per-provider `tests/release/conftest.py` — Docker conftest has
`project` / `vault_clean` / `postgres_clean` / `docker_required`; Azure conftest
has `azure_project` / `azure_required`):

- `project` / `azure_project` — tmp project dir with sentinel `.env`,
  guaranteed `vystak destroy` teardown even on test failure.
- `vault_clean` — removes stale `vystak-vault` container and
  `vystak-vault-data` volume before each Vault-path test. Required
  because the shared `vystak-vault-data` volume persists across
  worktrees; a per-project `init.json` can go missing while the
  volume survives with init state, producing "state mismatch" on apply.
- `postgres_clean` — removes stale `vystak-data-*` and legacy
  `agentstack-data-*` volumes before each Postgres test. Required
  because Postgres initializes PGDATA with the FIRST password it sees
  on that volume; subsequent runs with a fresh password in
  `.vystak/secrets.json` fail authentication.

Verification dimensions V1–V15 (see `test_plan.md`): V1 plan, V2 apply,
V3 isolation, V4 health, V5 agent card, V6 channel I/O, V7 transport,
V8 rotation, V9 destroy, V10–V12 workspace (isolation / SSH RPC /
persistence), V13–V15 multi-agent (subagent codegen / restrictive
routing / session continuity).

## Architecture — orthogonal axes

The core design idea (see `docs/principles.md` — its "Seven Concepts" table is
the conceptual map): an Agent definition is compiled against independent
choices, none of which abstracts the others:

```
Agent Schema (Pydantic)
    ├── Framework template  — HOW the agent thinks     (vystak-template-langchain-python)
    ├── Platform provider   — WHERE it runs            (vystak-provider-docker, vystak-provider-azure)
    ├── Channel plugin      — HOW users reach it       (vystak-channel-chat / -slack / -discord / -api)
    └── Transport plugin    — HOW agents talk east-west (vystak-transport-http, vystak-transport-nats)
```

Base ABCs live in `vystak/src/vystak/providers/base.py`: `PlatformProvider`
(with `plan/apply/destroy` + channel variants), `ChannelPlugin`,
`TransportPlugin`. **No source codegen anywhere** — components are real
importable modules; only build artifacts (Dockerfile, requirements, HCL,
config json) are emitted as strings. Channels are **separately deployed
containers** (one per declaration), registered via the `vystak.channels` entry
point into `vystak.channels.registry.ChannelPluginRegistry`.

**The codegen model changed** from the original design: agent code is no longer
emitted as source strings by an adapter. `vystak-template-langchain-python` is a
real, runnable project tree copied wholesale into the user's project at
`vystak init` (and refreshed by `vystak update`). Its `_vystak/runtime/`
machinery (`app_factory.build_agent_app`) composes the LangGraph react-agent +
FastAPI + A2A + OpenAI-compatible endpoints at runtime. `vystak-cli`'s
`templates.py` is a template *registry/resolver*, not an emitter.

## Core packages (Python)

Core:
- **`vystak`** — schema models, hash engine, provisioning graph, plugin ABCs, transport client, stores.
  - `vystak.schema/` — Pydantic contract: `Agent` (with `default_model` + `models` pool, `Heartbeat`, `Compaction`), `Skill`, `Channel`, `Resource`, `Workspace`, `Provider`, `Platform`, `Transport`, `Vault`, `Telemetry`, `Secret`, `McpServer`, `Service`, plus the OpenAI-compatible API models.
  - `vystak.hash/` — content-addressable hashing (`AgentHashTree`) for **hash-based change detection** — no state files. `vystak plan` compares definition hash to the hash stored as a platform label.
  - `vystak.provisioning/` — `ProvisionGraph`: DAG of `Provisionable` nodes with `depends_on`, `provision(context)`, `health_check()`, `destroy()`. Providers build a graph, topologically sort, thread results through `context`.
  - `vystak.providers/` — the three ABCs plus `DeployPlan`, `DeployResult`, `GeneratedCode` (despite the name, a file-transport bundle of real files + build artifacts, not emitted source).
  - `vystak.mcp/` — framework-agnostic MCP normalization (`normalize()` → `McpConnectionSpec`; transport inference + secret interpolation).
  - `vystak.transport/` — east-west A2A abstraction: `Transport`, `AgentClient`/`ask_agent`, `A2AHandler`, typed `A2AMessage`/`A2AResult`/`AgentRef`.
  - `vystak.state/` — local `.vystak/` deploy-side bookkeeping (pushed secrets, identities).
  - `vystak.secrets/` — runtime SDK for reading secrets from container env.
  - `vystak.channels/` — `ChannelPluginRegistry`.
- **`vystak-cli`** — `vystak init | plan | apply | destroy | status | logs | secrets | update` (Click; commands under `vystak_cli/commands/`). Scaffolds projects from bundled framework templates.
- **`vystak-chat`** — Rich/prompt-toolkit terminal REPL to talk to deployed agents (A2A client + agent picker).

Framework templates:
- **`vystak-template-langchain-python`** — the LangChain/LangGraph agent template (see Architecture above). Layout: user-owned `server.py`/`vystak.yaml`/`Dockerfile`/`tools/` + `_vystak/runtime/` (app_factory, graph, mcp, memory, subagents, skills, compaction, `a2a_native/`, `openai/`).

Channels (each a `ChannelPlugin`, deployed as its own container):
- **`vystak-channel-runtime`** — shared `ChannelRuntime` base bundled into every channel image: agent client, delivery, heartbeat hooks, store, telemetry.
- **`vystak-channel-chat`** — OpenAI-compatible unified endpoint (`/v1/chat/completions`), routes by `model="vystak/<agent-name>"`. This replaced the old `vystak-gateway` router.
- **`vystak-channel-slack`** — Slack Socket Mode runner (slack-bolt).
- **`vystak-channel-discord`** — Discord Gateway runner (discord.py).
- **`vystak-channel-panel`** — control-panel REST + SSE API (users, projects, conversations, message persistence with tool-call `parts`, admin-provisioned password auth via bcrypt + `POST /api/auth/verify`); consumed by the `vystak-panel` Next.js app. SQLite store with versioned in-place migrations (`SCHEMA_VERSION` in `store.py`).

Transports: **`vystak-transport-http`** (no broker), **`vystak-transport-nats`** (JetStream; provisions broker + injects listener code into agent `server.py`).

Providers: **`vystak-provider-docker`** (containers/volumes/network nodes under `nodes/` for agents, channels, heartbeat, vault, nats, otel, workspaces), **`vystak-provider-azure`** (ACA: `ResourceGroupNode → LogAnalyticsNode → ACRNode → ACAEnvironmentNode → ContainerAppNode`, plus Key Vault, managed identity, `AzurePostgresNode`).

Infra services:
- **`vystak-heartbeat`** — standalone scheduler container (cron via `croniter`): invokes agents over the configured Transport and delivers results through a channel. Auto-spawned once per platform when any agent declares `heartbeat` (`vystak-provider-docker/nodes/heartbeat.py`; ACA equivalent on Azure). See `docs/heartbeat.md`.
- **`vystak-workspace-rpc`** — JSON-RPC 2.0 server spoken **over SSH** (sshd `subsystem vystak-rpc`) inside standalone workspace containers; services: exec, fs, git, tool. Agent containers SSH into the workspace and drive it via this RPC.

## Agent endpoints (A2A + OpenAI-compatible)

Every agent built from the langchain template serves, on its HTTP port
(wired in `_vystak/runtime/app_factory.py`):
- `GET /.well-known/agent.json` — Agent Card (`a2a_native/card.py`)
- `POST /a2a` — JSON-RPC via a2a-sdk (`LangGraphExecutor`)
- `POST /v1/chat/completions`, `/v1/responses`, `GET /v1/models`, `/healthz`

Multi-agent setups call peers via the `vystak.transport` client (A2A over
HTTP or NATS) inside tool functions; `vystak-channel-chat` aggregates multiple
agents under one OpenAI-compatible endpoint.

## Codegen modules — load-bearing quirks

Modules that emit literal source/config as strings have `per-file-ignores`
for **E501** in root `pyproject.toml`:

- `vystak-channel-chat/src/vystak_channel_chat/server_template.py`
- `vystak-channel-slack/src/vystak_channel_slack/server_template.py`
- `vystak-provider-docker/src/vystak_provider_docker/templates.py`

The channel `server_template.py` files emit build-time `REQUIREMENTS`/
`DOCKERFILE` strings (the runnable code is the bundled package itself);
provider-docker `templates.py` emits deterministic Vault HCL + entrypoint
shims. Do **not** remove the ignores or mechanically break lines inside the
emitted strings.

**Channel containers install the emitted `REQUIREMENTS` string, not
`pyproject.toml`.** A dependency added only to a channel package's
pyproject deploys as a crash-looping container (`ModuleNotFoundError` at
import — bcrypt did exactly this; no CI gate catches it, only a live
deploy). When adding a runtime dependency to a channel package, add it to
that package's `server_template.py` `REQUIREMENTS` in the same commit.
`vystak-channel-panel/tests/test_server_template.py` pins the panel
channel's imports; extend it when adding deps there.

## Side-effect / test-mock import quirks

Imports that look unused but are load-bearing (all carry `# noqa: F401`
comments — **do not remove** even if ruff flags them):

- `vystak_provider_docker.network` — `import docker` (patched by `test_network.py`)
- `vystak_provider_docker.resources` — `import docker` + `import docker.errors` (patched by `test_resources.py`)
- `vystak_cli/cli.py` — `import vystak_channel_chat / _discord / _slack` registers each `ChannelType` plugin as an import side effect; removing them silently breaks channel resolution.

## Schema contract

`vystak.schema.Agent` is the authoritative shape. Everything generates *from*
this — template runtime, provisioning, hashing, validation. Adding fields means:
1. Add to the Pydantic model under `vystak/schema/`.
2. Update the hash contribution if the field affects deploy identity (`vystak/hash/tree.py`).
3. Update the template runtime to consume it (`vystak-template-langchain-python/_vystak/runtime/`).
4. Update `multi_loader` validation if cross-object references are involved.
5. Update test fixtures across packages.

Loading paths:
- Single-agent YAML/JSON: `vystak.schema.loader.load_agent` (rejects `subagents` — use multi-doc layout).
- Multi-agent/workspace YAML: `vystak.schema.multi_loader.load_multi_yaml` — top-level named `providers`, `platforms`, `models`, `agents`, `channels`, `vault`; resolves named references and validates channel↔agent and heartbeat `target_channel`.
- CLI entry: `vystak_cli.loader.load_definitions` — convention files `vystak.yaml` / `vystak.yml` / `vystak.py`. Python files are exec'd and **all** module-level `Agent` instances are collected. Environment overlays via `vystak.<env>.py` with an `override` binding.
- Folder skills: `vystak.schema.skill_resolver.resolve_folder_skills` runs at load time (schema loader + CLI loader + template `.py` dev path), filling `Skill.description/path/content_digest` from `skills/<name>/SKILL.md`. Idempotent (skips skills with a digest); a skill with no tools, no prompt, and no folder is a load-time error. Digest rules mirror `_bundle_project_dir`'s exclusions — keep them in sync.

## Examples

`examples/` (35 dirs) maps onto the feature axes: `docker-*` / `azure-*`
(provider), `*-vault` (secrets), `*-workspace-*` (workspace compute),
`heartbeat-*`, `*-multi-chat*` / `*multi-agent*` (multi-agent, incl.
`docker-multi-chat-nats` for the NATS transport), `*multi-channel*`,
`docker-skills` / `docker-skills-slack` (folder skills), `mcp-files`,
`memory-agent`, `sessions-postgres` / `docker-compaction` (sessions),
`docker-panel` (control panel). When modifying core behavior, update or run the matching example
to verify end-to-end.

**When implementing a specific feature, create (or update) an agents
configuration under `examples/` that simulates real usage of that feature** —
a `vystak.yaml`/`vystak.py` a user could actually deploy exercising the new
surface. This is part of the feature's definition of done, not an optional
extra.

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
- Releases: `just release <version>` tags `v<version>`; `.github/workflows/release.yml` publishes Python packages to PyPI (hand-maintained list — **update it when adding/removing packages**) then `pnpm -r publish` to npm. Deliberately unpublished: `vystak-template-langchain-python` (bundled into the `vystak-cli` wheel by its build hook).
- TS packages (`@vystak/core`, `vystak` CLI, `@vystak/adapter-mastra`, `@vystak/provider-docker`) are placeholder stubs — the TS port is not implemented. `vystak-panel` is the exception: a real Next.js app (control-panel UI) on Tailwind v4 + vendored shadcn/ui + AI Elements (see its README), not part of the TS port. Its optional email/password sign-in is enabled with `PANEL_PASSWORD_AUTH=1`.
