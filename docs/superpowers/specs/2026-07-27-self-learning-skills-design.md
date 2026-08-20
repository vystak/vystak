# Self-Learning Skills — Design

Date: 2026-07-27
Status: approved

## Summary

Let an agent author new skills for itself at runtime. Declarative
`skills:` stay the immutable, hash-bound seed; a new `learning:` block
enables a **learned-skill store** whose rows the agent writes via
`write_skill` / `revise_skill` / `retire_skill`, surfaces in its own
prompt, and loads on demand with the existing `load_skill`. Learned
skills live outside the agent hash, so they never cause `plan` drift and
`apply` never clobbers them. `vystak skills promote` graduates a learned
skill into a declared folder skill.

Docker provider only in this iteration; Azure is a follow-up.

## Motivation

- Folder skills (spec `2026-07-23`) made capability packageable, but only a
  human can add one. An agent that discovers a better way to do its job has
  nowhere to put that knowledge.
- Long-term memory is factual (`## Memory`); it has no shape for
  *procedural* knowledge — "when X fails, do Y" — and no progressive
  disclosure, so procedures would burn context every turn.
- The naive implementation (agent edits `skills/<name>/SKILL.md`) collides
  head-on with hash-based change detection. This spec exists mainly to give
  that collision a real answer rather than a workaround.

## Constraints that shaped the design

1. **Hash-based change detection, no state files.** `vystak plan` compares
   the definition hash to a platform label. `agent.skills` feeds the hash
   via `_hash_list` (`vystak/hash/tree.py:259`), and `Skill.content_digest`
   is a sha256 over the folder's shipped bytes
   (`skill_resolver.compute_skill_digest`). Any agent-written file under
   `skills/` therefore changes deploy identity: `plan` would report drift
   forever and the next `apply` would clobber the learning.
2. **Agent containers have no default writable durable surface.**
   `nodes/agent.py` mounts only dependency-resource volumes and the vault
   secrets volume. Skills ship inside the image bundle, so anything written
   to the container filesystem dies on restart.
3. **A learned skill is instructions the model wrote that the model will
   later follow** — a self-persisting prompt-injection channel. It needs
   hard limits, not just good intentions.
4. **Precedent exists.** Scheduled tasks (spec `2026-07-25`) already solved
   "agent mutates its own config at runtime": declarative YAML seed →
   runtime rows in a store outside the hash → CLI surface. And a `sqlite`
   service already provisions a named volume mounted at `/data` with
   connection string `/data/<name>.db` (`resources.py:110`), which
   `sessions` and `memory` both ride. This design is the third instance of
   that pattern, not a new mechanism.

## Requirements (settled in brainstorming)

1. Declarative `skills:` remain immutable and hash-bound. Learned skills
   are a separate, unhashed store.
2. Learned skills satisfy the same contract `resolve_folder_skills`
   enforces: name match, non-empty description, `tools` a list of strings.
3. A learned skill may only reference tools **already granted** to the
   agent. It composes capability; it never expands it.
4. `mode: approval` exists in v1; `auto` is the default.
5. Persistence survives container restart and `apply`. Proven by a release
   cell, not by unit tests.
6. `promote` converts a learned skill into a reviewed, declared folder
   skill — the graduation path.
7. Scope: `vystak-provider-docker`. Azure follow-up.

## Schema

New model `vystak/schema/learning.py`, wired as
`Agent.learning: Learning | None = None` beside `sessions` and `memory`.

```yaml
agents:
  - name: support-bot
    framework: langchain-python
    default_model: claude
    skills: [triage]          # declarative seed — hash-bound, immutable
    learning:
      mode: auto              # auto | approval
      max_skills: 32
      max_body_bytes: 16384
      store:
        type: sqlite          # ServiceType — sqlite | postgres
        provider: {name: docker, type: docker}
```

| Field | Type | Default | Notes |
|---|---|---|---|
| `mode` | `"auto" \| "approval"` | `"auto"` | `approval` writes new skills as `pending`. |
| `max_skills` | int > 0 | 32 | Active + pending rows. `write_skill` fails past it. |
| `max_body_bytes` | int > 0 | 16384 | Per-skill body cap. |
| `store` | `ServiceType` | `sqlite` | Same union `sessions`/`memory` use. |

`store` defaults to a managed sqlite service named `<agent>-learning`,
provisioned through the existing path: a dependency edge in
`AgentNode.depends_on`, a volume `vystak-data-<agent>-learning` mounted at
`/data`, and `LEARNING_STORE_URL` in the container env. No new provider
node.

### Hash contribution

`learning` is **configuration** and hashes: `mode`, both caps, and the
store type all affect deploy identity, and go into `AgentHashTree`
alongside the existing `skills` component. The learned rows themselves
contribute **nothing**. `vystak plan` stays clean no matter how much the
agent learns; `apply` replaces the container while the volume — and the
learning — survives, exactly as sessions do today.

### LearnedSkill row

| Column | Notes |
|---|---|
| `name` | Unique per agent. Reconciliation identity. |
| `description` | Non-empty. What the prompt listing shows. |
| `body` | The instructions. `load_skill` returns this. |
| `status` | `active` \| `pending` \| `retired`. |
| `tools` | JSON list. Validated against granted tools at write time. |
| `revision` | Integer, bumped by `revise_skill`. |
| `created_by` | `agent:<canonical>` or `operator:<user>`. |
| `source_thread` | Thread the skill was written in, for provenance. |
| `created_at` / `revised_at` | Timestamps. |

Retired rows are kept, not deleted, so a bad lesson can be audited and
un-retired. `vystak skills remove` is the hard delete.

### Write-time validation (store layer, not the prompt)

- Frontmatter contract as `resolve_folder_skills` enforces it.
- Every named tool already in the agent's granted tool set.
- `name` not present in `agent.skills` — a learned skill can never shadow a
  declared one.
- `max_skills` and `max_body_bytes`.
- `guardrails` are untouchable from a learned skill.

## Runtime

### Prompt assembly

`build_prompt` currently computes `skills_section` once, outside the async
closure (`prompt_callable.py:17`) — correct for bundle skills, which cannot
change. Learned skills can, so their listing moves *inside* `_prompt`,
beside the memory recall already there:

```
## Skills            ← bundle skills, static
## Learned skills    ← store, status=active, refreshed per turn
- retry-flaky-deploys: How to recover when a deploy fails on a transient
  registry timeout.
```

Progressive disclosure is unchanged: the listing carries name +
description only; the body arrives via `load_skill(name)`.

### LearnedSkillManager

Mirrors `MemoryManager` — constructed in `app_factory` when
`agent.learning` is set, holding the store plus an in-process snapshot of
active skills. The prompt callable refreshes the snapshot once per turn;
`load_skill` reads it synchronously, so `skills.py`'s existing sync `@tool`
signature is untouched. Writes hit the store and invalidate the snapshot.
Name collisions resolve **bundle-wins**.

### Tools

`build_learning_tools(agent)` follows the `build_schedule_tools` shape:
returns `[]` when learning isn't wired (env unset), and tools return error
strings rather than raising, so a store outage doesn't kill the turn.

- `write_skill(name, description, body)` — validates, writes `active`
  under `mode: auto` or `pending` under `mode: approval`, and returns which
  happened so the model can tell the user its skill awaits review.
- `revise_skill(name, description?, body?)` — bumps `revision`. This is how
  learning compounds: a skill that failed gets sharpened, not duplicated.
- `retire_skill(name, reason)` — sets `status=retired`. Rejects bundle
  skill names; the agent cannot retire what a human declared.

### HTTP surface

`GET/POST/PATCH/DELETE /learned-skills` on the agent's own FastAPI app,
beside `/healthz` and `/v1/models`. No new container. Reachability is the
story that already exists: published host port under Docker, ACA ingress on
Azure — how `vystak-chat` and A2A reach an agent today.

### Deliberate omission: resource files

Bundle skills support `read_skill_file` over a folder; a learned skill is a
single `body` string. Agent-authored resource files would need a blob store
and a second tool for marginal gain. `promote` is where a skill graduates
into a real folder that can hold resources. YAGNI until asked.

## Operator surface

`vystak skills`, alongside `vystak schedules`:

| Command | Effect |
|---|---|
| `list [--agent A] [--status …]` | name, status, revision, created_by, age. |
| `show <name>` | Full body plus provenance. |
| `approve <name>` / `retire <name>` | Flip `status`. `approve` is the `mode: approval` gate. |
| `promote <name>` | Graduate into a declared skill. |
| `remove <name>` | Hard delete. Retire is the soft default. |

### promote

Closes the loop. It writes `skills/<name>/SKILL.md` with valid
frontmatter, retires the store row so the skill isn't listed twice, and
then **prints the one-line `skills:` addition rather than editing
`vystak.yaml` itself** — the user's YAML carries comments and formatting no
round-tripper in this repo preserves, and silently rewriting a
hand-authored config erodes trust in the tool. After the user makes that
edit, the next `vystak plan` shows a real hash change, because a promoted
skill genuinely *is* a deploy change.

That asymmetry is the design in one line: **learning is unhashed and
disposable; promotion is reviewed and permanent.**

## Testing

Unit:

- `vystak` — schema validation and hash contribution: `learning` config
  hashes, learned rows do not.
- `vystak-template-langchain-python` — `LearnedSkillManager`, the learned
  prompt section, tool contract enforcement (ungranted tool, oversized
  body, shadowed bundle name, cap exceeded).
- `vystak-cli` — `vystak skills` verbs, including `promote`'s file output
  and printed YAML snippet.

Release cell — the durability claim is the one that needs a live deploy.
New `packages/python/vystak-provider-docker/tests/release/test_learned_skills.py`
(`release_integration`), with a `learning_clean` fixture in the vein of
`postgres_clean`, since `vystak-data-*-learning` outlives the project:

1. Deploy an agent with `learning: {mode: auto}`.
2. `write_skill` via A2A.
3. Restart the agent container.
4. Assert the skill is still listed and `load_skill` returns the body.
5. `vystak skills promote`; assert the file lands.
6. Destroy.

Volume-survives-restart is the load-bearing architectural assertion;
nothing short of a real container proves it.

## Definition of done

Following the schema-contract checklist in CLAUDE.md:

1. `Learning` model under `vystak/schema/`, wired into `Agent`.
2. Hash contribution in `vystak/hash/tree.py`.
3. Template runtime consumption (`prompt_callable`, `skills`,
   `app_factory`, new `learning.py`).
4. `multi_loader` validation for the `store` reference.
5. Test fixtures updated across packages.
6. Docker provider: dependency edge, volume mount, `LEARNING_STORE_URL`.
7. `vystak skills` CLI command group.
8. `examples/docker-self-learning/` — one seed skill,
   `learning: {mode: auto}`, sqlite store, README walking write → restart →
   promote.
9. `docs/self-learning.md` and a website concept page, matching how
   `docs/schedules.md` shipped.

## Out of scope

- **The missing memory write path.** `MemoryManager.handle_tool_output`
  consumes `__SAVE_MEMORY__|` / `__FORGET_MEMORY__|`, but nothing in the
  template emits them — there is no `save_memory` tool, and
  `examples/memory-agent/vystak.yaml` instructs the model to call one that
  doesn't exist. A real bug, found while researching this feature, but a
  separate one. Filed in `todos.md`.
- Learned-skill resource files (see above).
- Cross-agent skill sharing — one agent learning from another's skills.
- Azure provider support.
- Automatic learning (the agent deciding *unprompted* to write a skill
  after a task). v1 gives it the tools and describes them; when to use them
  is the agent's instructions' business.
