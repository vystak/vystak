# Framework Template Scaffold (No-Codegen Agents) — Design

**Date:** 2026-05-02
**Status:** Approved (brainstorm complete; awaiting implementation plan)

## Summary

Replace `vystak-adapter-langchain` (a codegen package that emits Python source as
strings) with `vystak-template-langchain-python` — a real, runnable agent
project that ships inside the `vystak-cli` wheel and is copied into the user's
project at `vystak init` time.

After init, the user owns the project tree. A `_vystak/` namespace inside the
project holds framework runtime code (real Python modules, not strings) that
`vystak update` can refresh in place. Files outside `_vystak/` are
user-controlled and never touched by `update`.

The `Agent` schema gains a `framework: str` field (default
`"langchain-python"`) that names which template registry entry the agent runs
against. This is the seam that makes additional templates
(`mastra-typescript`, `raw-anthropic-python`, etc.) trivial to add later.

This is the agent-side counterpart to the channel-side pivot landed in
`2026-05-02-channel-runtime-and-discord-design.md`. Channels already moved off
codegen; agents are the larger, harder cousin.

## Goals

- Eliminate string-emission codegen for the LangChain/LangGraph adapter.
  Replace the ~3,100 LOC of generated source plus ~2,200 LOC of "does emitted
  string contain X" tests with real Python modules and ordinary pytest.
- Make every framework-side runtime concern (A2A, Responses, compaction,
  memory, MCP, graph wiring) unit-testable in-process with `TestClient` and
  fake LangGraph events. No Docker required for unit coverage.
- Give users full visibility and control over their agent project. The
  scaffolded code is theirs; framework code is namespaced under `_vystak/` and
  refreshed by an explicit `vystak update` command.
- Make `vystak.yaml` self-describing about which runtime it depends on via a
  required `framework` field — so a glance at the YAML tells you which
  template it requires, not just which model.
- Land in vertical slices that keep the repo green and existing examples
  deployable at every step.

## Non-goals

- TypeScript template (`mastra-typescript`). Out of scope. The `framework:`
  key is the seam that lets it land later without re-architecting.
- Third-party / external template authoring. The registry is a directory
  bundled inside `vystak-cli`. The dir-based loader is forward-compatible with
  external templates (e.g. `pip install`able template packages) but that work
  is a separate effort.
- Per-project template version pinning (e.g.
  `framework: { name: langchain-python, version: ">=0.6,<0.7" }`). The CLI
  version is the unit of release; one CLI ships exactly one version of each
  bundled template. Object-form `framework:` lands when there's actual demand.
- Migrating in-place deployments. A user with a deployed Docker container from
  before this work runs `vystak destroy && vystak init … && vystak apply`. We
  do not surgically retrofit `_vystak/` into pre-migration projects.
- Three-way merge / git-aware update. The contract is: edit anything outside
  `_vystak/`; never edit inside. `vystak update` overwrites `_vystak/` blindly.
  No conflict markers, no `.new` files, no merge tool.
- Codegen opt-out post-migration. Once `vystak-adapter-langchain` is deleted
  (Step 9), it stays deleted. No "use the old path" flag.
- Auto-scaffolding from `vystak apply`. If `_vystak/` is missing, `apply`
  errors with remediation; it does not silently create files in the user's
  workdir.

## Architecture

### Package layout

```
packages/python/
├── vystak                               # core schema + provisioning ABCs
│                                        # NEW: Agent.framework field
│                                        # NEW: vystak.schema.manifest module
├── vystak-cli                           # CLI commands + bundled templates
│   └── templates/
│       └── langchain-python/            # bundled template tree (copied at init)
├── vystak-template-langchain-python     # NEW workspace member
│                                        # has its own pytest suite, lints,
│                                        # is the development home of the
│                                        # template tree that gets bundled
│                                        # into vystak-cli at build time
├── vystak-provider-docker               # simplified — no longer bundles
│                                        # vystak_adapter_langchain
├── vystak-provider-azure                # same simplification
└── vystak-adapter-langchain             # DELETED at end of migration
```

The template package is a workspace member (editable install, lints, tests
run as part of `just ci`) but is **not** published to PyPI on its own. It
ships inside the `vystak-cli` wheel as package data.

### Distribution

`vystak-cli`'s build copies `vystak-template-langchain-python/`'s tree
(excluding `tests/` and any `_test_assets/` directories) into the wheel under
`vystak_cli/templates/langchain-python/`. The copy is performed by a custom
hatchling (or setuptools) build hook in `vystak-cli/pyproject.toml`. The
bundled directory exists only in built sdists/wheels — it is NOT committed to
the repo.

**Development resolution.** During editable workspace installs (`uv sync`),
the bundled directory does not exist on disk. `vystak_cli.templates` falls
back to a sibling path discovered via the workspace layout: starting from the
installed CLI's package root, walk up to `packages/python/`, then look for
`vystak-template-langchain-python/`. If found, treat it as the registry entry
for `langchain-python`. This keeps the local edit loop fast — touch a file in
the template, rerun `vystak init` in another terminal, no rebuild step. The
fallback only fires when the bundled dir is missing; in installed wheels the
bundled dir wins.

`vystak init` resolves the template by name → directory in the registry →
`shutil.copytree` into the user's target dir → fills in
`_vystak/manifest.json` with file hashes and timestamps.

### Build / deploy flow

`vystak apply` no longer generates code. The user's project directory **is**
the Docker build context.

```
User project (post-init)                  Docker build context
─────────────────────────                 ─────────────────────
my-agent/
├── vystak.yaml          (user)           COPY . /app/
├── server.py            (user, shim)
├── Dockerfile           (user, thin)     pip install -r _vystak/requirements.txt
├── requirements.txt     (user, overlay)  pip install -r requirements.txt
├── tools/               (user)
├── _vystak/                              CMD ["python", "server.py"]
│   ├── manifest.json    (managed)
│   ├── runtime/         (managed)
│   ├── requirements.txt (managed)
│   └── Dockerfile.base  (managed)
```

### File ownership boundary

The split is enforced purely by directory namespace. There is no metadata flag
on individual files saying "managed" or "user."

**User-owned (never touched by `update`):**
```
my-agent/
├── vystak.yaml          # agent definition (or vystak.py)
├── .env.example         # secret placeholders
├── .gitignore           # written once at init, never overwritten
├── server.py            # ~12-line FastAPI shim
├── Dockerfile           # thin; user can extend
├── requirements.txt     # overlay deps for user tools
├── pyproject.toml       # optional, for `uv sync` workflows
├── tools/               # user tool modules
└── README.md            # written once at init
```

**Managed (overwritten by `update`):**
```
my-agent/_vystak/
├── manifest.json
├── DO_NOT_EDIT.md       # contract reminder
├── CHANGELOG.md         # per-template-version notes
├── runtime/             # all framework Python modules
├── requirements.txt     # framework dependencies
└── Dockerfile.base      # optional base image (user's Dockerfile may FROM it)
```

### Starter `server.py` (user-owned)

```python
from _vystak.runtime.app_factory import build_agent_app
from _vystak.runtime.config import load_agent

agent = load_agent("vystak.yaml")  # or vystak.py — extension dispatch
app = build_agent_app(agent)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
```

The user can wedge in custom middleware, extra routes, lifespan hooks — any
FastAPI extension point — without touching `_vystak/`.

### Starter `Dockerfile` (user-owned)

```dockerfile
FROM python:3.12-slim
WORKDIR /app

COPY _vystak/requirements.txt /app/_vystak/requirements.txt
RUN pip install -r /app/_vystak/requirements.txt

COPY requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt

COPY . /app
CMD ["python", "server.py"]
```

(The starter ships an empty `requirements.txt` at the user level; pip exits 0
on empty files, so no `|| true` guard is needed. Users append tool-specific
deps as their agent grows.)

`_vystak/Dockerfile.base` exists for users who want to switch to a managed
base image later, but it is **not** referenced by the starter Dockerfile.
Keeps init simple at the cost of the framework not being able to push base-
image upgrades automatically — explicit tradeoff.

## Schema additions

### `Agent.framework`

```python
# vystak.schema.agent
class Agent(BaseModel):
    name: str
    framework: str = "langchain-python"   # NEW; registry key
    model: Model
    # ... existing fields unchanged
```

YAML:
```yaml
name: weather
framework: langchain-python
model:
  provider:
    type: anthropic
  model_name: claude-sonnet-4-6
skills:
  - name: forecast
    tools: [get_weather]
```

The schema accepts any string. Validation that the name exists in the bundled
registry happens in `vystak-cli` at `init`/`apply`/`update` time, because the
`vystak` schema package does not know about CLI-bundled assets.

`framework` contributes to the agent hash. Changing it triggers a forced
redeploy.

### `TemplateManifest`

A new module `vystak.schema.manifest` defines the manifest written to
`_vystak/manifest.json`:

```python
class TemplateRef(BaseModel):
    name: str
    version: str

class VystakCompat(BaseModel):
    schema_version: str
    min_compat: str
    max_compat: str

class TemplateManifest(BaseModel):
    schema_version: int = 1
    template: TemplateRef
    vystak: VystakCompat
    scaffolded_at: datetime
    scaffolded_by_cli: str
    files: dict[str, str]   # rel_path -> "sha256:<hex>"
```

Lives in core (not in CLI) because the runtime in `_vystak/runtime/config.py`
reads it at boot to verify schema compatibility — not just at apply time.

`schema_version: 1` is the manifest format's own version; bumps only if the
manifest's shape changes.

Example manifest written by `vystak init`:

```json
{
  "schema_version": 1,
  "template": {
    "name": "langchain-python",
    "version": "0.6.2"
  },
  "vystak": {
    "schema_version": "0.5",
    "min_compat": "0.4",
    "max_compat": "0.6"
  },
  "scaffolded_at": "2026-05-02T15:30:00Z",
  "scaffolded_by_cli": "1.4.0",
  "files": {
    "_vystak/runtime/app_factory.py": "sha256:abc123...",
    "_vystak/runtime/a2a.py": "sha256:def456...",
    "_vystak/requirements.txt": "sha256:..."
  }
}
```

### Manifest-template seed

Each template directory carries a `_vystak/manifest.template.json` — a partial
manifest with `template.name`, `template.version`, and `vystak` compat range
filled in. At `init`, the CLI computes file hashes, fills in `scaffolded_at`
and `scaffolded_by_cli`, and writes the final `manifest.json`.

## Template internals

### Module map

```
_vystak/runtime/
├── __init__.py
├── app_factory.py        # build_agent_app(agent) -> FastAPI
├── config.py             # load_agent(path), manifest reader
├── a2a.py                # A2AHandler, TaskManager, AgentCard
├── responses.py          # ResponsesHandler, ChatCompletionsHandler
├── compaction.py         # PreCallPruner, ThresholdCompactor
├── memory.py             # MemoryManager + save/forget tool sentinels
├── graph.py              # build_graph(agent, prompt, tools, checkpointer)
├── prompt_callable.py    # build_prompt(agent, memory_mgr, compactor, pruner)
├── mcp.py                # attach_mcp_servers(graph, agent)
├── store.py              # build_checkpointer(agent)
├── tools.py              # load_user_tools(agent, tools_dir)
└── builtin_tools.py      # workspace tools (read_offloaded, fs.*, exec.*, git.*)
```

### Class interfaces

```python
class A2AHandler:
    def __init__(self, agent: Agent, graph: CompiledGraph,
                 task_manager: TaskManager) -> None: ...
    async def dispatch(self, payload: dict) -> dict | StreamingResponse: ...

class ResponsesHandler:
    def __init__(self, agent: Agent, graph: CompiledGraph,
                 *, store: CompactionStore | None) -> None: ...
    async def create(self, body: ResponsesCreateBody) -> dict | StreamingResponse: ...
    async def get(self, response_id: str) -> dict: ...

class ThresholdCompactor:
    def __init__(self, agent: Agent, store: CompactionStore,
                 summarizer: BaseChatModel) -> None: ...
    async def maybe_compact(self, thread_id: str,
                            messages: list[BaseMessage]) -> list[BaseMessage]: ...
    async def manual_compact(self, thread_id: str,
                             instructions: str | None) -> dict: ...
```

### `build_agent_app` composition

```python
def build_agent_app(agent: Agent) -> FastAPI:
    app = FastAPI()

    checkpointer    = build_checkpointer(agent)
    user_tools      = load_user_tools(agent, Path("tools"))
    workspace_tools = build_workspace_tools(agent)
    memory_mgr      = MemoryManager(agent)

    compactor = (ThresholdCompactor(agent, ...)
                 if agent.compaction else None)
    pruner    = (PreCallPruner(agent.compaction)
                 if agent.compaction else None)

    prompt = build_prompt(agent, memory_mgr, compactor, pruner)
    graph  = build_graph(agent, prompt, user_tools + workspace_tools, checkpointer)

    a2a       = A2AHandler(agent, graph, TaskManager())
    responses = ResponsesHandler(agent, graph,
                                 store=compactor.store if compactor else None)
    chat      = ChatCompletionsHandler(agent, graph)

    app.add_api_route("/.well-known/agent.json", AgentCard(agent).render, methods=["GET"])
    app.add_api_route("/a2a", a2a.dispatch, methods=["POST"])
    app.add_api_route("/v1/chat/completions", chat.create, methods=["POST"])
    app.add_api_route("/v1/responses", responses.create, methods=["POST"])
    app.add_api_route("/v1/responses/{id}", responses.get, methods=["GET"])
    if compactor:
        app.add_api_route("/v1/sessions/{thread_id}/compact",
                          compactor.manual_compact, methods=["POST"])
        app.add_api_route("/v1/sessions/{thread_id}/compactions",
                          compactor.list_compactions, methods=["GET"])
    # ... healthz, /v1/models, etc.
    return app
```

## CLI commands

### `vystak init`

```bash
vystak init my-agent                                    # framework defaults to langchain-python
vystak init my-agent --framework langchain-python       # explicit
vystak init my-agent --framework <other> --force        # overwrite existing dir
vystak init --list-frameworks                           # prints registry
```

Behavior:
1. Resolve `--framework` value → directory in the bundled registry. Error if
   not found.
2. If target directory exists and is non-empty → error unless `--force`.
3. `shutil.copytree(bundled_template, target)`, excluding `tests/` and
   `_test_assets/`.
4. Hash every copied file under `_vystak/`. Combine with the seed
   `manifest.template.json` to write the final `_vystak/manifest.json`.
5. Print next-step hints.

### `vystak update`

```bash
vystak update                # refresh _vystak/ to bundled CLI's template version
vystak update --check        # dry-run; exit 0 if current, 1 if changes pending
vystak update --force        # overwrite even if versions match
vystak update --strict       # fail on schema major-version drift
```

Algorithm:
1. Read `./_vystak/manifest.json` → current template `name@version`.
2. Read `./vystak.yaml` → `agent.framework`. Verify it matches manifest's
   `template.name`. Mismatch → error with remediation
   (`vystak init --framework <new> --force .`).
3. Resolve bundled template version for that framework.
4. If `current_version == bundled_version` and all `_vystak/` file hashes
   match → print "current," exit 0 (unless `--force`).
5. Schema compatibility check: if installed core's version exceeds the
   bundled template's `vystak.max_compat` (or below `min_compat`), warn or
   refuse per `--strict`.
6. `shutil.rmtree(./_vystak)`, `shutil.copytree(bundled_template/_vystak, ./_vystak)`.
7. Print summary, link to `_vystak/CHANGELOG.md`.

User edits inside `_vystak/` are detected via hash mismatch and surface as
an informational warning (e.g. `Note: 2 files under _vystak/ were modified
locally; they will be overwritten.`). The update proceeds without prompting —
the warning is informational, not interactive. The contract is "don't edit
there"; we trust the user to honor it.

### `vystak apply`

1. Load `vystak.yaml` (validation, hash).
2. Verify `_vystak/` exists and `manifest.json.template.name == agent.framework`.
   Mismatch → error with remediation.
3. Build context = the user's project directory as-is. No generation.
4. `docker build` against the project dir. Hash includes:
   - `vystak.yaml` content
   - `_vystak/manifest.json.template.version` and `_vystak/manifest.json.template.name`
   - `tools/` tree
   - `Dockerfile`
   - `requirements.txt`

The `.vystak/build/` scratch directory disappears — there is nothing to
generate, nothing to scratch.

### `vystak destroy`, `vystak status`, `vystak logs`, `vystak plan`

Unchanged. They operate on deployed containers, not on local source.

### Flag summary

| Command  | Flag                  | Purpose                                   |
|----------|-----------------------|-------------------------------------------|
| `init`   | `--framework <name>`  | Select template (default: langchain-python)|
| `init`   | `--list-frameworks`   | Print bundled registry                    |
| `init`   | `--force`             | Overwrite existing dir                    |
| `update` | (none)                | Refresh `_vystak/`                        |
| `update` | `--check`             | Dry-run                                   |
| `update` | `--force`             | Re-stamp manifest unconditionally         |
| `update` | `--strict`            | Fail on schema major-version drift        |

## Test strategy

Three layers replace the codegen-string assertions outright.

### Unit (fast, in-process, mock LLM)

Lives in `vystak-template-langchain-python/tests/`. Most coverage here.

- `test_a2a.py` — feed a fake `CompiledGraph` returning canned events; assert
  `tasks/send` produces expected JSON-RPC, `tasks/sendSubscribe` emits SSE
  frames in order, `tasks/cancel` transitions state correctly.
- `test_responses.py` — assert each OpenAI event shape across stream / non-
  stream / background paths: `response.created`,
  `response.output_text.delta`, `response.function_call_arguments.delta`,
  `response.completed`, `[DONE]`.
- `test_compaction.py` — feed message lists at known token estimates; assert
  when summarize fires, when the 60s + 70%-coverage idempotency guard kicks
  in, when fail-open emits the SSE chunk.
- `test_memory.py` — ephemeral recall returns expected messages; save/forget
  sentinels round-trip through the graph.
- `test_prompt_callable.py` — prune happens, summary lookup happens, system
  message rebuilt fresh per turn.
- `test_graph.py` — `build_graph` wires checkpointer, tools, and prompt; with
  a stub model, run a turn end-to-end in-process.
- `test_app_factory.py` — `build_agent_app` produces a FastAPI app; FastAPI's
  `TestClient` hits all routes; assert 200 + payload shape for each.

### Integration (slower, real LangGraph + fake LLM)

Same `tests/` directory, marked `@pytest.mark.integration`. Spins up a real
`build_agent_app(agent)` with a stub model returning canned token streams,
verifies cross-cutting concerns (streaming through A2A, Responses event
ordering with tool calls, compaction triggering during a real conversation).

### Release-tier (existing 16-cell matrix)

Unchanged. Already exercises real LLM + Docker + Slack. Becomes the only
place we exercise the template end-to-end with real models.

### Coverage migration table

| Removed                                      | Replaced by                                  |
|----------------------------------------------|----------------------------------------------|
| `vystak-adapter-langchain/tests/test_a2a.py` | `vystak-template-langchain-python/tests/test_a2a.py` |
| `…/test_responses.py` (string asserts)       | `…/test_responses.py` (event-shape asserts)  |
| `…/test_templates.py` (~992 LOC)             | `…/test_app_factory.py` + `…/test_graph.py`  |
| `…/test_streaming_e2e.py`                    | unchanged (release-tier)                     |
| `…/test_adapter.py` (LangChainAdapter unit)  | deleted (no adapter to test)                 |
| `…/test_tools.py`, `…/test_turn_core.py`     | moved into template tests verbatim           |
| `…/test_workspace_client.py`                 | moved into template tests verbatim           |

## Migration plan

Nine vertical slices, each a separate PR. Repo stays green at every step.

| Step | What lands | Codegen path alive? | Examples deploy? |
|------|------------|---------------------|------------------|
| 0    | Scaffold `vystak-template-langchain-python/` skeleton; register in workspace; empty runtime/ + tests/ harness | Yes | Yes |
| 1    | Extract `A2AHandler` + `TaskManager` + `AgentCard` as real classes; unit tests with fake graph | Yes | Yes |
| 2    | Extract `ResponsesHandler` + `ChatCompletionsHandler`; unit tests for every OpenAI event shape | Yes | Yes |
| 3    | Extract `ThresholdCompactor` + `PreCallPruner` + `MemoryManager` | Yes | Yes |
| 4    | Extract `build_graph` + `build_checkpointer` + `attach_mcp_servers` + `load_user_tools` | Yes | Yes |
| 5    | Wire `app_factory.build_agent_app`; integration tests with `TestClient` | Yes | Yes |
| 6a   | Add `Agent.framework` (default `"langchain-python"`); include in hash; tests for default | Yes | Yes |
| 6b   | Add `vystak init --framework`, `vystak update`, manifest schema, registry, `--list-frameworks` | Yes | Yes |
| 7    | Migrate one example (`hello-agent`) to template scaffold; add a release cell exercising the template path; both paths coexist | Yes | Yes (both paths) |
| 8a   | Migrate every `examples/*` to explicit `framework: langchain-python` and template scaffolds | Yes | Yes (template path only) |
| 8b   | Drop `Agent.framework` default; field becomes required | Yes (legacy) | Yes (template path only) |
| 9    | Delete `vystak-adapter-langchain` package, `templates.py`, `a2a.py`, `responses.py`, codegen tests; remove `LangChainAdapter`; remove `_bundled_mods` entry for `vystak_adapter_langchain` in Docker provider | No | Yes (template path only) |

### Risk handling

- **A2A behavioral parity (Step 1).** Tests assert exact JSON-RPC bodies the
  codegen path emits today, so the new `A2AHandler` is provably equivalent.
- **OpenAI event-stream parity (Step 2).** Highest-risk step. Build a golden-
  file test: replay a recorded LangGraph event stream through both the old
  codegen path and the new `ResponsesHandler`; byte-compare the SSE output.
  Lock parity before the codegen path is removed.
- **Compaction parity (Step 3).** Lower risk; compaction stores already in
  core. The existing `examples/docker-compaction/` release cell continues to
  validate.
- **MCP, memory, tools (Step 4).** Codegen was already emitting the same
  Python source we want at runtime; the move is mostly cut-and-paste plus
  unit tests.
- **Hash-based change detection (Step 6+).** Today's hash is over emitted
  strings; new hash is over user-dir files. Existing deployed agents will
  diff dirty on first run after upgrade — expected, surfaces as a forced
  redeploy. Documented in upgrade notes.
- **Docker provider's `_bundled_mods` (Step 9).** Keep bundling for `vystak`,
  `vystak_transport_*`, `vystak_channel_*`. Only remove the
  `vystak_adapter_langchain` entry. The new template carries its runtime as
  ordinary copied source.

## Versioning & compatibility

Three versions move on independent cadences but coordinate at the CLI's
release boundary.

| Version             | Lives where                                              | Bumps when                              |
|---------------------|----------------------------------------------------------|-----------------------------------------|
| `vystak` (core)     | `packages/python/vystak/pyproject.toml`                  | Schema fields added/changed             |
| `vystak-cli`        | `packages/python/vystak-cli/pyproject.toml`              | CLI commands or bundled templates change|
| Template            | `packages/python/vystak-template-langchain-python/pyproject.toml` | Runtime behavior changes        |

The CLI pins exact versions of the templates it bundles. A given
`vystak-cli==1.4.0` ships exactly one `langchain-python` template version
(e.g. `0.6.2`). The user picks a CLI version; the template comes along.

### Compatibility checks at `vystak update`

1. Read installed core `vystak.__version__` (e.g. `0.7`).
2. Read bundled template's `manifest.template.json` `vystak.max_compat` (e.g.
   `0.6`) and `vystak.min_compat`.
3. **Major drift** (`installed > max_compat` and major-version bumped, or
   `installed < min_compat`): refuse to update without `--force`. Print
   `_vystak/CHANGELOG.md` upgrade notes.
4. **Minor drift**: warn and proceed.
5. **In range**: silent update.

No semver resolver, no dependency graph, no lock file. The CLI version is the
unit of release; everything else is consistency checks.

### Hash contribution summary

Inputs to the agent hash (gates `apply` redeploy):
- `Agent.framework` value
- `_vystak/manifest.json.template.version` (NEW)
- `_vystak/manifest.json.template.name` (NEW; redundant with `framework` but
  kept for clarity in audit)
- `vystak.yaml` content (existing)
- `tools/` tree (existing)
- `Dockerfile` (existing)
- `requirements.txt` (existing)

A `vystak update` that bumps template version → manifest version changes →
hash dirty → next `apply` redeploys. Correct.

## What dies

- `packages/python/vystak-adapter-langchain/` — entire package, ~3,100 LOC
- `LangChainAdapter` class
- `FrameworkAdapter.generate()` ABC method (the ABC itself stays for
  validation, but the codegen contract is removed)
- `vystak-adapter-langchain/tests/` — ~2,200 LOC of string-assertion tests
- Docker provider's `_bundled_mods` entry for `vystak_adapter_langchain` in
  `nodes/agent.py`
- `.vystak/build/` scratch directory — no generation, no scratch
- Hash inputs based on emitted string blobs

## Open questions deferred

- **Multi-framework agents in one repo.** Each agent dir gets its own
  `_vystak/`. Disk cost is ~MBs per agent, acceptable for now.
- **TypeScript template (`mastra-typescript`).** Out of scope for this
  migration. The `framework:` key is the seam that lets it land later.
- **Third-party / external templates.** Internal-only registry for now. The
  dir-based loader is forward-compatible with `pip install`able external
  templates (e.g. an entry point group that the CLI scans), but that work is
  separate.
- **Object-form `framework:` with version constraints.** Not in v1. Plain
  string is enough until multi-version-per-CLI becomes a real need.
- **Template authoring guide.** Not in v1. Only `langchain-python` exists in
  the registry at end of this work.
