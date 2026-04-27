# Vystak Comprehensive Test Plan

**Date:** 2026-04-23
**Scope:** End-to-end functional verification of deploy + runtime for every
supported combination of stack × secret delivery × channel × transport.

## Interpretation of the matrix

- **Stack**: where the agent runs.
  - `docker` — local Docker daemon (standalone, not Swarm).
  - `azure` — Azure Container Apps (ACA) via `vystak-provider-azure`.
- **Secrets**: how declared secrets are delivered to containers.
  - `default` — no `vault:` block. Docker uses per-container `--env-file`.
    Azure ACA uses inline `configuration.secrets[]` + `env[].secretRef`.
  - `vault` — `vault:` block declared. Docker → HashiCorp Vault server +
    per-principal AppRoles + Vault Agent sidecars. Azure → Azure Key Vault
    + per-principal UAMI + `lifecycle:None`.
- **Channel**: how users reach the agent.
  - `chat` — `ChannelType.CHAT` endpoint served by `vystak-channel-chat`,
    driven interactively by the `vystak-chat` terminal REPL.
  - `slack` — `ChannelType.SLACK` endpoint served by `vystak-channel-slack`
    (Socket Mode runner against a real Slack workspace).
- **Transport**: how channel ↔ agent messages flow.
  - `http` — `vystak-transport-http`. Channel makes HTTP calls to the agent's
    FastAPI `/a2a` endpoint.
  - `stream` — `vystak-transport-nats`. Channel and agent attach to a
    `vystak-nats` broker via subjects; message passing is pub/sub with
    streaming semantics.

## Tiers

Running all 16 cells manually is expensive. Tier into smoke (must-pass
before merge / release), integration (should-pass weekly), and edge
(nice-to-pass when reproducing a specific issue).

| Cell | Stack | Secrets | Channel | Transport | Tier |
|---|---|---|---|---|---|
| **D1** | docker | default | chat | http | **Smoke** |
| **D2** | docker | vault | chat | http | **Smoke** |
| **D3** | docker | default | slack | http | **Smoke** |
| **D4** | docker | default | chat | stream | **Smoke** |
| D5 | docker | vault | slack | http | Integration |
| D6 | docker | vault | chat | stream | Integration |
| D7 | docker | default | slack | stream | Integration |
| D8 | docker | vault | slack | stream | Edge |
| **C1** | docker | default | chat | http | Integration |
| **A1** | azure | default | chat | http | **Smoke** |
| **A2** | azure | keyvault | chat | http | **Smoke** |
| A3 | azure | default | slack | http | Integration |
| A4 | azure | keyvault | slack | http | Integration |
| A5 | azure | default | chat | stream | Integration |
| A6 | azure | keyvault | chat | stream | Edge |
| A7 | azure | default | slack | stream | Edge |
| A8 | azure | keyvault | slack | stream | Edge |

**Smoke (6 cells)**: prove each major axis works in isolation.
**Integration (6 cells)**: prove axes compose cleanly.
**Edge (4 cells)**: prove the full product has no combinatorial surprises.

**C-axis (compaction)**: orthogonal to stack × channel × transport. C1 verifies
Postgres-backed session compaction end-to-end: 30 turns trigger threshold
compaction, manual `/compact` succeeds, both rows appear in the inspection
endpoint. Requires a real `ANTHROPIC_API_KEY`; LLM-dependent steps auto-skip
on sentinel keys (infra wiring still verified).

---

## Prerequisites

**For every test:**
- Python 3.11+ via `uv`, `pnpm`, Docker daemon running.
- `./env` with at minimum `ANTHROPIC_API_KEY`, `ANTHROPIC_API_URL`.
- Clean working tree on `main` at commit `>= 257a485` (post-merge tip).

**For Slack tests (D3, D5, D7, D8, A3, A4, A7, A8):**
- A test Slack workspace.
- `SLACK_BOT_TOKEN` (xoxb-) from a Slack app with `chat:write`, `app_mentions:read`, `im:history`, `im:write` scopes.
- `SLACK_APP_TOKEN` (xapp-) with `connections:write` scope (for Socket Mode).
- A test channel the bot is added to.

**For Azure tests (A1–A8):**
- `AZURE_SUBSCRIPTION_ID` in `.env`.
- `az login` completed.
- A disposable resource group the tester can create/destroy.
- ACR pull auth configured.

**For vault tests (D2, D5, D6, D8):**
- No extra prereqs — the Hashi Vault container is provisioned by vystak.

**For keyvault tests (A2, A4, A6, A8):**
- An Azure Key Vault you own (or `mode=deploy` will create one).
- Caller identity with `Key Vault Secrets Officer` role (to push values
  during apply) and grant-creation rights.

**For stream transport (D4, D6, D7, D8, A5, A6, A7, A8):**
- Docker: no extra — `vystak-nats` container is auto-provisioned.
- Azure: a separate NATS endpoint (ACA-deployed or external). Document the URL.

---

## Common verification checklist

Every test run records pass/fail on each of these. The *Per-case procedure*
section below expands each into concrete commands.

| Dim | Verify |
|---|---|
| **V1 Plan** | `vystak plan` prints the expected sections (EnvFiles: / Vault: / Identities: / Workspaces: / no orphan warnings). |
| **V2 Apply** | `vystak apply` exits 0. Containers / ACA apps report as running. Cold start time recorded. |
| **V3 Isolation** | For every principal P with declared secrets S, `S ⊂ env(P)` AND for every other principal Q, `S ∩ env(Q) = ∅`. Verified via `docker exec env` or `az containerapp exec`. |
| **V4 Health** | `GET /health` on the agent returns 200 with `{"status":"ok"}`. |
| **V5 Agent card** | `GET /.well-known/agent.json` returns a valid A2A card listing declared skills. |
| **V6 Channel I/O** | Send a message via the channel; agent responds with plausible content. Chat: via `vystak-chat`. Slack: via DM or channel mention. |
| **V7 Transport** | For stream tests, `docker exec vystak-nats nats sub 'vystak.>'` (or equivalent) shows the message pass through. For http, agent access logs show the inbound request. |
| **V8 Rotation** | Change a secret value in `.env` (default) or push via `vystak secrets set NAME=V` (vault). Restart the container. Verify new value is present via V3. |
| **V9 Destroy** | `vystak destroy` exits 0. For default-path, `.vystak/env/` and `.vystak/ssh/` cleaned. For vault-path, state preserved unless `--delete-vault`. No orphan containers/volumes/apps. |
| **V13 Subagent codegen** | If the agent declares `subagents:`, the generated `.vystak/<agent>/agent.py` contains one `async def ask_<peer>(question, config: RunnableConfig)` per peer, imports `ask_agent` from `vystak.transport`, propagates `config.configurable.thread_id` as `metadata.sessionId`, and the docstring is the peer's `instructions` first paragraph (≤200 chars). Verify by reading the generated file. |
| **V14 Restrictive routing** | `docker exec vystak-<caller> env \| grep VYSTAK_ROUTES_JSON` (or ACA equivalent) shows ONLY the caller's declared subagents — not all project agents. For an agent with no subagents, the table is empty (`{}`). Calling `ask_agent("undeclared", ...)` from inside the container raises an "unknown peer" error from the transport client. |
| **V15 Session continuity** | From a single chat or Slack session, ask the coordinator two questions that delegate to the same peer (e.g., "weather in Tokyo?" then "what about Osaka?"). Inspect `docker logs vystak-<peer>` — both inbound calls carry the same `sessionId` in the A2A envelope's `metadata`. The peer's LangGraph checkpointer threads the messages under one id, so the second call sees the first as part of its own (peer-private) history. The coordinator's session does NOT contain the peer's chain of thought. |

---

## Per-case procedure — Smoke tier (must pass)

### D1 — docker × default × chat × http

**Config (`vystak.yaml`):**
```yaml
providers:
  docker: {type: docker}
  anthropic: {type: anthropic}
platforms:
  local: {type: docker, provider: docker}
models:
  sonnet: {provider: anthropic, model_name: claude-sonnet-4-20250514}
channels:
  - name: chat
    type: chat
    platform: local
agents:
  - name: assistant
    model: sonnet
    platform: local
    secrets: [{name: ANTHROPIC_API_KEY}, {name: ANTHROPIC_API_URL}]
```

**`.env`:** `ANTHROPIC_API_KEY=...`, `ANTHROPIC_API_URL=...`.

**Commands:**
```bash
vystak plan                        # V1
vystak apply                       # V2
docker ps --filter name=vystak-    # expect: assistant + channel-chat
docker exec vystak-assistant env | grep ANTHROPIC_API_KEY   # V3
curl http://localhost:$(docker port vystak-assistant 8000 | awk -F: '{print $2}')/health   # V4
curl http://localhost:.../.well-known/agent.json            # V5
vystak-chat --agent assistant      # V6: send "hi", expect a response
vystak destroy                     # V9
ls .vystak/env .vystak/ssh 2>&1    # expect cleaned
```

**Pass gate:** every V1–V9 row above green.

---

### D2 — docker × vault × chat × http

Same as D1 plus:
```yaml
vault:
  name: vystak-vault
  provider: docker
  type: vault
  mode: deploy
  config: {}
```

**Commands (delta from D1):**
```bash
vystak plan                   # V1: expect Vault:, AppRoles:, Policies: sections
vystak apply                  # V2: ~15–30s cold start (includes Vault init + unseal)
docker ps --filter name=vystak-   # expect: vystak-vault, 2x vault-agent sidecars, assistant, channel-chat
ls .vystak/vault/init.json    # V2: 0600 perms, contains unseal_keys_b64 and root_token
docker exec vystak-assistant cat /shared/secrets.env | grep ANTHROPIC   # V3 (via shim-rendered file)
vystak secrets set ANTHROPIC_API_KEY=new-value    # V8 knob
docker restart vystak-assistant
docker exec vystak-assistant env | grep ANTHROPIC_API_KEY  # V8 verify
vystak destroy                # V9: Vault + init.json preserved
vystak destroy --delete-vault # tear down Vault too
```

---

### D3 — docker × default × slack × http

Add a slack channel; drop the chat channel.
```yaml
channels:
  - name: slack
    type: slack
    platform: local
    secrets:
      - {name: SLACK_BOT_TOKEN}
      - {name: SLACK_APP_TOKEN}
```

`.env` must include `SLACK_BOT_TOKEN` and `SLACK_APP_TOKEN`.

**Commands (delta):**
```bash
vystak apply
docker ps --filter name=vystak-        # expect: assistant + channel-slack
docker logs vystak-channel-slack | grep "Connected to Slack"   # V6 precondition
# In Slack DM to the bot: "hello"
# Observe response appear in Slack within ~5s. V6 pass.
# Repeat V3/V4/V5 on agent container and channel container.
```

**V3 detail for slack channel:** `docker exec vystak-channel-slack env | grep SLACK_BOT_TOKEN` should succeed; `docker exec vystak-assistant env | grep SLACK` should return nothing (cross-principal scoping).

---

### D4 — docker × default × chat × stream

Declare NATS transport on the platform:
```yaml
platforms:
  local:
    type: docker
    provider: docker
    transport:
      type: nats
      config: {subject_prefix: "vystak"}
```

**Commands (delta):**
```bash
vystak apply
docker ps --filter name=vystak-    # expect: vystak-nats + assistant + channel-chat
docker exec vystak-assistant env | grep VYSTAK_TRANSPORT_TYPE   # expect nats
docker exec vystak-assistant env | grep VYSTAK_NATS_URL          # expect nats://vystak-nats:4222
# In a second terminal:
docker exec vystak-nats nats sub 'vystak.>'   # V7
# In the first: send a message via vystak-chat.
# Expect subjects like "vystak.assistant.request" / "vystak.chat.response" on the subscription.
```

---

### A1 — azure × default × chat × http

Azure provider + no vault block.
```yaml
providers:
  azure: {type: azure, config: {location: eastus2, resource_group: vystak-test-rg}}
  anthropic: {type: anthropic}
platforms:
  aca: {type: container-apps, provider: azure}
channels:
  - name: chat
    type: chat
    platform: aca
agents:
  - name: assistant
    model: sonnet
    platform: aca
    secrets: [{name: ANTHROPIC_API_KEY}, {name: ANTHROPIC_API_URL}]
```

**Commands:**
```bash
vystak plan      # V1: expect EnvFiles: section (no Vault:/Identities:/Grants:)
vystak apply    # V2: ~3–5 min (RG + Log Analytics + ACR + ACA env + image build/push + app create)
az containerapp list -g vystak-test-rg -o table   # expect: assistant + channel-chat as separate apps
az containerapp exec -n vystak-assistant -g vystak-test-rg --command "env | grep ANTHROPIC"   # V3
curl https://$(az containerapp show -n vystak-assistant -g vystak-test-rg --query properties.configuration.ingress.fqdn -o tsv)/health   # V4
# V6: vystak-chat --agent assistant --base https://<fqdn>
vystak destroy --include-resources
az group exists -n vystak-test-rg    # expect false
```

**Known gap (ACA multi-container deploy plumbing — see "Known gaps" below):**
this test currently deploys a **single-container ACA app** per principal.
Per-principal isolation still holds because each principal = separate ACA
app, but the "multi-container per app" path that
`build_revision_default_path` targets is not yet wired.

---

### A2 — azure × keyvault × chat × http

Add a vault block; Azure provider runs the KV-backed subgraph.
```yaml
vault:
  name: vystak-test-kv
  provider: azure
  type: key-vault
  mode: deploy
  config: {vault_name: vystak-test-kv-abc}
```

**Commands (delta):**
```bash
vystak plan       # V1: Vault:, Identities:, Secrets:, Grants: sections
vystak apply     # V2: +1–2 min over A1 (KV create + UAMI provisioning + grant assignment with RBAC propagation wait)
az keyvault show -n vystak-test-kv-abc -o table      # expect: exists
az keyvault secret show --vault-name vystak-test-kv-abc -n ANTHROPIC-API-KEY   # expect: value present (name normalized)
az identity list -g vystak-test-rg -o table           # expect: assistant-agent UAMI
az role assignment list --scope <kv-resource-id>       # expect: UAMI granted Key Vault Secrets User on specific secret
az containerapp show -n vystak-assistant -g vystak-test-rg --query "properties.configuration.identitySettings"
# Expect lifecycle: "None" on agent-uami.
# V6 proceeds as A1.
vystak secrets push --force    # V8: rotate by overwriting
az containerapp revision restart -n vystak-assistant -g vystak-test-rg   # pick up new value
# V9: vystak destroy preserves KV + secret values by design
vystak destroy --delete-vault --include-resources   # tear KV too
```

---

## Per-case procedure — Integration tier

Each integration cell follows the same V1–V9 pattern; differences from
smoke tier are deltas only. Concrete commands elided for brevity — they're
combinations of the smoke-tier procedures above.

| Cell | Key deltas vs related smoke case |
|---|---|
| **D5** — docker × vault × slack × http | D2 + D3. Verify slack-channel principal has its own AppRole + sidecar; `vystak-channel-slack` container has SLACK_* in its env only. |
| **D6** — docker × vault × chat × stream | D2 + D4. Verify NATS subjects prefixed correctly; `vystak-nats` runs alongside Vault stack. |
| **D7** — docker × default × slack × stream | D3 + D4. |
| **A3** — azure × default × slack × http | A1 + D3. Slack channel deploys as its own ACA app. |
| **A4** — azure × keyvault × slack × http | A2 + D3. Slack channel has its own UAMI + KV grant. |
| **A5** — azure × default × chat × stream | A1 + NATS endpoint (external URL). Test also: NATS URL override via platform.transport.config. |

---

## Per-case procedure — Edge tier

Same V1–V9 pattern, combining prior deltas. Execute only when
debugging a specific interaction.

| Cell | Triggers this to run |
|---|---|
| **D8** — docker × vault × slack × stream | Vault + Slack + NATS combined; verifies per-principal AppRoles × per-channel NATS subjects don't cross-contaminate. |
| **A6** — azure × keyvault × chat × stream | Debug NATS-on-Azure; requires external NATS service. |
| **A7** — azure × default × slack × stream | Same. |
| **A8** — azure × keyvault × slack × stream | Full stack edge — everything opt-in. |

---

## Dimensions that do NOT vary by cell

**Workspace** — a separate orthogonal dimension we recommend testing once
per stack. If a cell includes a workspace, apply **all** V1–V9 checks plus:

- **V10 Workspace isolation**: `docker exec vystak-<agent>-workspace env`
  contains workspace-declared secrets only. Agent container contains
  agent-declared secrets only. Zero overlap.
- **V11 Workspace SSH RPC**: agent can call `fs.listDir` / `exec.run` /
  `git.status` built-in tools against the workspace. Failure mode: missing
  `known_hosts` — documented gap below.
- **V12 Workspace persistence**: with `persistence: volume`, write a file
  via `exec.run "echo test > /workspace/test.txt"`, destroy without
  `--delete-workspace-data`, re-apply, read back — expect `test`.

**Recommended once-per-stack:** run D2 + workspace (docker × vault ×
workspace) and A2 + workspace (azure × keyvault × workspace). For default
path: D1 + workspace and A1 + workspace.

**Rotation & migration** — a full migration test is worth one pass per
release:

1. Deploy with `vault:` declared (D2 or A2).
2. Remove `vault:` from config.
3. `vystak plan` — expect orphan detection + migration guidance printed.
4. `vystak destroy --delete-vault`.
5. `vystak apply` — expect default path stands up cleanly.
6. Re-add `vault:` — expect vault path stands back up.

**Channel routing** — one agent serving multiple channels, one channel
fanning to multiple agents. Add to integration runs of A3/A4.

**Multi-agent (subagents)** — orthogonal dimension. The `Agent.subagents:
list[Agent]` field auto-generates one `ask_<peer>` LangChain tool per
declared peer, restricts the caller's `VYSTAK_ROUTES_JSON` to its declared
subagents (so unauthorised peer calls fail at the transport client), and
propagates the active LangGraph `thread_id` as A2A `metadata.sessionId`
across hops. Test once per **stack** and once per **transport**:

- **D-multi-http**: D1 + multi-agent (docker × default × chat × http × multi).
  Three agents: `assistant-agent` with `subagents: [weather-agent, time-agent]`,
  the two specialists with no subagents. Chat channel routes to all three.
- **D-multi-nats**: D4 + multi-agent (docker × default × chat × stream × multi).
  Same topology, NATS transport — exercises sessionId propagation over NATS
  subjects rather than HTTP.
- **A-multi-http**: A1 + multi-agent (azure × default × chat × http × multi).
  Same topology on ACA. Per-agent UAMI on the keyvault path is out of scope
  here (covered separately when ACA multi-container plumbing lands — see
  Known gap #1).

Each multi cell adds **V13–V15** to the V1–V9 checklist.

**Canary — collision detection.** A regression-prevention micro-test you
should run once on each stack: declare `subagents: [weather-agent]` AND
drop a `tools/ask_weather_agent.py` next to `vystak.yaml`. Expect
`vystak apply` to fail at codegen time with a clear `ValueError: Tool
name conflict: ['ask_weather_agent'] are auto-generated for subagents
but also defined as user tools.` If this passes silently, the collision
guard in `vystak-adapter-langchain/templates.py` regressed.

**Reference example:** `examples/multi-agent/vystak.yaml` is the canonical
shape — three agents in one multi-document YAML, coordinator declaring
`subagents: [weather-agent, time-agent]`, shared `tools/` directory with
`get_weather.py` and `get_time.py` (no manual `ask_*_agent.py` files).

---

## Known gaps (tests to defer)

Per `CHANGELOG.md` Unreleased / "Known follow-up work":

1. **Azure multi-container workspace deploy** — `build_revision_for_vault`
   and `build_revision_default_path` are unit-tested but neither is wired
   into `ContainerAppNode.provision` yet. **Workspace tests A1/A2 + workspace
   will currently deploy a single-container agent app without the workspace
   sidecar.** Track in follow-up spec; do not block this plan.
2. **Default-path agent→workspace SSH RPC** — `known_hosts` not generated
   for the default path. **V11 will fail** on D1/A1 + workspace. Track
   separately; V10 (env isolation) still passes.
3. **`DockerProvider.destroy()` programmatic cleanup** — if a test harness
   calls the provider directly (bypassing `vystak destroy` CLI), the
   default-path state files are not cleaned. Use the CLI.
4. **`_ResolvedPassthroughNode` design** — no functional impact; design
   debt noted.
5. **Vault path + channels with secrets — ~~silent security hole~~ FIXED.**
   Previously `_add_vault_nodes` enumerated only agent + workspace
   principals, so channel secrets pushed to Vault KV had no per-channel
   AppRole or sidecar and `DockerChannelNode` silently fell back to
   `os.environ` passthrough. Fixed: `_add_vault_nodes` now enumerates
   channel principals alongside agent + workspace; `apply_channel`
   wires the channel container to its pre-provisioned sidecar volume;
   `DockerChannelNode` skips the `os.environ` passthrough when a vault
   context is set. `vystak plan` output gains `<channel>-channel` rows
   in the AppRoles/Policies sections. Cells D5 and D8 now pass
   (previously xfail).
   Azure equivalent not verified — channel-principal UAMIs on Azure
   Vault path likely have the same gap but can't be tested until the
   multi-container ACA deploy plumbing (gap #1) lands.

---

## Results tracking template

Copy this table into the test run document. Fill one row per cell executed.

```
| Cell | V1 | V2 | V3 | V4 | V5 | V6 | V7 | V8 | V9 | Notes |
|------|----|----|----|----|----|----|----|----|----|-------|
| D1   |    |    |    |    |    |    |    |    |    |       |
| D2   |    |    |    |    |    |    |    |    |    |       |
| ...  |    |    |    |    |    |    |    |    |    |       |
```

Legend: `✓` pass, `✗` fail (open issue), `—` not applicable, `skip` deferred.

**Release gate:** all six smoke cells pass all V1–V7 and V9 (V8 optional).
Integration and edge tiers are diagnostic; failures open issues but don't
block the release by themselves.

---

## Execution order

1. **Day 1 AM**: D1, D2 (fastest cells, full Docker stack shakedown). If
   either fails, stop and triage before proceeding — they share the most
   surface with every other docker cell.
2. **Day 1 PM**: D3, D4 (smoke channel + transport variants on docker).
3. **Day 2 AM**: A1 (first Azure cell; account for 3–5 min cold starts).
4. **Day 2 PM**: A2 (keyvault on Azure — confirms the Vault-on-Azure path).
5. **Day 3**: Integration tier (D5–D7, A3–A5). Run in parallel across
   separate resource groups / docker contexts if possible.
6. **Post-release / as-needed**: edge tier.

**Total estimated wall time for smoke tier:** ~3 hours (most is Azure
provisioning waits). Docker-only smoke (D1–D4) is ~20 minutes.

---

## Automation hooks

A future iteration should convert the smoke tier into `-m release_smoke`
pytest markers that drive the above via real daemons. Structure per cell:

- `tests/release/test_cell_D1.py` — applies D1, runs assertions, destroys.
- Fixtures handle `.env` setup, Azure resource group creation, Slack
  workspace auth.
- Skip markers auto-detect missing prereqs (no Azure login → skip Azure
  cells).

For now, this plan is a **manual runbook**. Record results per run in a
dated markdown under `docs/test-plans/YYYY-MM-DD-results.md`.

---

## Update log

- **2026-04-23** — Initial plan written alongside the secret-manager
  simplification merge. Covers post-merge state: default path works
  on both docker and azure; vault path preserved as opt-in.
- **2026-04-25** — Added multi-agent (subagents) as an orthogonal
  dimension. New verification rows V13 (subagent codegen), V14
  (restrictive routing), V15 (session continuity). Three recommended
  multi-agent cells (D-multi-http, D-multi-nats, A-multi-http) plus a
  collision-detection canary. Reference example:
  `examples/multi-agent/vystak.yaml`.
- **2026-04-25** — Added C-axis (compaction). C1 cell: Postgres-backed
  agent with `mode=aggressive, trigger_pct=0.05`; 30-turn conversation
  triggers threshold compaction; manual `/compact` succeeds; both rows
  appear in the inspection endpoint. `release_integration` + `docker`
  markers; LLM-dependent steps auto-skip on sentinel keys.
