# Folder Skills — Design

**Status:** approved for implementation
**Date:** 2026-07-23
**Owner:** anatoliy@ankosoftware.com

## Summary

Extend the existing `Skill` model so a skill can be a **folder of packaged
instructions** (`skills/<name>/SKILL.md` + resource files) in the user's
project, declared on an agent and bundled into its container. At runtime the
agent consumes folder skills via **progressive disclosure**: the system prompt
lists each skill's name + description, and the agent loads the full
instructions on demand through a `load_skill` tool (with a companion
`read_skill_file` tool for bundled resources).

This unifies with — not replaces — today's `Skill` (a named bundle of tool
references). One concept: a skill is a named capability that may carry tools,
an inline prompt, and/or a folder of instructions.

Along the way this implements two documented-but-missing behaviors: per-skill
`prompt` injection into the system prompt, and a real `Skill.description`
(which the A2A agent-card builder already tries to read via `getattr`).

## Goals

- Author reusable instruction bundles as `skills/<name>/SKILL.md` folders in
  the project, following the Claude/Agent Skills convention (YAML frontmatter
  with `name`, `description`, optional `tools`).
- Declare them on agents with string shorthand: `skills: ["research"]`.
- Progressive disclosure at runtime — many skills don't bloat the context;
  the agent pulls in full instructions only when relevant.
- Editing any file inside a skill folder changes the agent hash, so
  `vystak plan` shows a redeploy.
- Existing inline skills (`{name, tools}`) keep working unchanged.

## Non-goals

- Packaged/pip-distributed skills (`vystak-skill-*`), registries, marketplaces
  (PROJECT_PLAN.md aspiration — unchanged).
- Skill-local tool files (`skills/<name>/tools/*.py`). Folder skills reference
  tools from the project's `tools/` dir via frontmatter, same resolution as
  inline skills.
- `SkillRequirements` plan-time validation (stays declared-but-unenforced).
- Automatic skill invocation / relevance ranking — the LLM decides when to
  call `load_skill` based on the prompt listing.
- Executable scripts inside skill folders. Resource files are read as text;
  running them is up to tools the agent already has (e.g. workspace exec).

## Folder format

```
skills/
  research/
    SKILL.md          # required — frontmatter + instructions body
    sources.md        # optional resource files, any names/subdirs
    templates/report.md
```

`SKILL.md` uses YAML frontmatter:

```markdown
---
name: research
description: Deep-research workflow — when to search, how to cite sources.
tools: [web_search]        # optional; resolved from the project tools/ dir
---
When asked to research a topic, follow this process...
```

Frontmatter fields: `name` (required, must equal the folder name),
`description` (required — it is the only thing the LLM sees before deciding
to load the skill, so it is load-bearing for routing), `tools` (optional
list of tool names, same semantics as `Skill.tools`). Unknown frontmatter
keys are rejected at load time to catch typos.

## Schema change

`vystak.schema.skill.Skill` gains three fields:

```python
class Skill(NamedModel):
    tools: list[str] = []
    prompt: str | None = None
    description: str | None = None      # NEW — shown in prompt listing + A2A card
    path: str | None = None             # NEW — project-relative folder, e.g. "skills/research"
    content_digest: str | None = None   # NEW — sha256 over folder contents, set by resolver
    guardrails: dict | None = None
    requires: SkillRequirements | None = None
    version: str = "0.1.0"
    dependencies: list[str] | None = None
```

A skill with `path` set is a **folder skill**; without it, it's an inline
skill exactly as today.

`Agent.skills` accepts mixed entries — `str | dict | Skill`. A validator on
`Agent` normalizes a bare string `"research"` to `Skill(name="research")`.
YAML:

```yaml
agents:
  - name: support
    skills:
      - research                # folder skill, resolved from skills/research/
      - name: orders            # inline skill, unchanged
        tools: [lookup_order]
```

Python definitions (`vystak.py`) get the same shorthand:
`Agent(..., skills=["research"])`.

## Folder resolution (load time, not model time)

Pydantic models stay filesystem-free. A new module
`vystak/schema/skill_resolver.py` exposes:

```python
def resolve_folder_skills(agents: list[Agent], project_dir: Path) -> None
```

For each agent skill that has no `path` and no `tools`/`prompt` (i.e. came
from string shorthand or is otherwise "empty"), it looks for
`<project_dir>/skills/<name>/SKILL.md`:

- **Found** → parse frontmatter, set `description`, merge frontmatter `tools`
  into `skill.tools`, set `path = "skills/<name>"`, compute `content_digest`.
- **Not found** → error: `Skill 'research' on agent 'support' has no tools,
  prompt, or skills/research/SKILL.md. Create the folder or declare tools.`
- Frontmatter `name` ≠ folder name → error.
- Missing `description` in frontmatter → error (it's load-bearing).

A skill declared with an explicit `path:` is resolved from that path (still
project-relative) — this covers folders whose name differs from the skill
name and is the escape hatch for shared locations.

Inline skills (`tools`/`prompt` present, no `path`) are never touched — an
inline skill named `research` coexisting with a `skills/research/` folder
resolves as inline (declaration wins); no implicit merging.

Callers: `vystak_cli.loader.load_definitions` (all three convention-file
paths), `vystak.schema.multi_loader.load_multi_yaml`, and
`vystak.schema.loader.load_agent` — each already knows the project/file dir.
Resolution recurses into `agent.subagents` (nested `Agent`s can declare
skills too). The template runtime does **not** re-resolve; it receives the
resolved model.

### Content digest

`content_digest = sha256` over the skill folder: sorted project-relative file
paths, each contributing `path\0bytes\0`. Deterministic across platforms
(paths use `/`). Any file edit, add, rename, or delete inside the folder
changes the digest.

## Hashing / redeploy detection

No change to `vystak/hash/tree.py`. `hash_agent` already does
`_hash_list(agent.skills)` with a full `model_dump`, so `description`,
`path`, and `content_digest` automatically contribute. Editing
`skills/research/sources.md` → new `content_digest` → new agent hash →
`vystak plan` reports a redeploy.

## Bundling

`vystak apply` bundles the project dir verbatim (`_bundle_project_dir`), so
`skills/` already lands in the agent image at the same relative location the
resolver recorded in `skill.path`. This design adds a test asserting the
bundle includes `skills/`, but no bundling code changes are expected.

## Runtime — progressive disclosure

New module `vystak-template-langchain-python/_vystak/runtime/skills.py`,
mirroring the `subagents.py` pattern, with two entry points wired in
`app_factory.py`:

**1. `skills_prompt_section(agent) -> str`** — consumed by `build_prompt`
(`prompt_callable.py`). Appended to the system prompt after
`agent.instructions`:

- For every skill with a `description` (folder or inline), one listing line:
  `- research: Deep-research workflow — when to search, how to cite sources.`
- If any folder skills exist, a preamble: *"You have the following skills.
  Before doing work that matches a skill's description, call
  `load_skill(name)` and follow its instructions."*
- Additionally — implementing the long-documented behavior — each **inline**
  skill's `prompt` field is appended verbatim (small inline skills stay
  eager; folder skill bodies stay lazy).

**2. `build_skill_tools(agent, project_root) -> list`** — returns two
LangChain tools, only when at least one folder skill exists (agents without
folder skills get zero new tools and an unchanged prompt except for the
listing/prompt-append above):

- `load_skill(name: str) -> str` — validates `name` against the agent's
  declared folder skills, reads `SKILL.md`, strips frontmatter, and returns
  the body followed by a listing of the folder's other files (relative
  paths), e.g. `Resource files: sources.md, templates/report.md — read them
  with read_skill_file.` Unknown name → error string listing valid names.
- `read_skill_file(skill: str, path: str) -> str` — reads a resource file
  from the named skill's folder. Guard: the resolved absolute path must stay
  inside the skill folder (reject `..`, absolute paths, and symlink escapes
  via `Path.resolve()` containment check). Missing file → error string
  listing available files.

Both tools read from disk on every call — no caching — so behavior is
obvious and the container filesystem is the single source of truth.

`load_user_tools` (`tools.py`) is unchanged: frontmatter `tools` were merged
into `skill.tools` at resolution, so tool loading works exactly as today.

**A2A agent card** (`a2a_native/card.py`): no code change needed — its
existing `getattr(skill, "description", "")` starts returning real values
once the field exists. A test pins this.

## Validation & CLI

- All folder-skill errors (missing folder, missing/mismatched frontmatter,
  empty description, unknown frontmatter keys) surface at load time —
  `vystak plan`/`apply` fail fast before any provisioning.
- Duplicate skill names on one agent are rejected at load time (they would
  collide in the prompt listing and `load_skill` namespace).
- Two agents may share the same folder skill; the digest is computed per
  declaration (identical value).
- No new CLI commands. `vystak plan` shows the redeploy via the existing
  hash diff.

## Example (definition of done)

New `examples/docker-skills/`:

- `vystak.yaml` — one agent on the Docker provider with
  `skills: ["research", {name: orders, tools: [lookup_order]}]` showing both
  forms, plus a chat channel.
- `skills/research/SKILL.md` — realistic frontmatter + instructions,
  `tools: []`, and one resource file (`sources.md`) so `read_skill_file` is
  exercised.
- `tools/lookup_order.py` — trivial tool for the inline skill.
- `README.md` — deploy + "ask it to research X and watch it load the skill"
  walkthrough.

## Test plan

- **`vystak` (schema/resolver/hash):**
  - `tests/schema/test_skill.py` — new fields default correctly; existing
    inline construction unaffected.
  - `tests/schema/test_agent.py` — string shorthand normalizes to `Skill`;
    mixed lists; duplicate skill names rejected.
  - `tests/schema/test_skill_resolver.py` — happy path (frontmatter parsed,
    tools merged, digest set); each error case (missing folder, name
    mismatch, missing description, unknown keys); explicit `path:` override;
    inline skill with matching folder is left alone.
  - `tests/hash/test_tree.py` — editing a skill file changes the agent hash;
    unchanged folder → unchanged hash.
- **`vystak-cli`:** loader integration — YAML and Python convention files
  resolve folder skills against the project dir; bundle includes `skills/`.
- **`vystak-template-langchain-python`:**
  - `tests/test_skills.py` — prompt section rendering (listing, preamble
    only with folder skills, inline `prompt` append); `load_skill` happy
    path + unknown name; `read_skill_file` happy path, missing file, and
    traversal guard (`../`, absolute, symlink escape).
  - `tests/test_app_factory.py` — agent with no folder skills gets no skill
    tools and no preamble.
- **Release tier (Docker):** one new cell exercising
  `examples/docker-skills` end-to-end — deploy, chat request that triggers
  `load_skill`, destroy. Marked `release_integration`.

## Docs

- `website/docs/concepts/agents.md` — rewrite the Skills section: folder
  skills lead, inline tool bundles second; remove the false claim that
  per-skill `prompt` injection already works (it becomes true, but describe
  the actual behavior).
- `README.md` skills mention updated with the folder form.

## Open questions

None — brainstorming locked in: unified `Skill` model, Claude-convention
`SKILL.md` frontmatter, frontmatter-declared tools resolved from `tools/`,
progressive disclosure with `load_skill` + `read_skill_file`.

## Rollout

One PR — schema + resolver + hash test + runtime + example + docs. Additive:
new optional fields, new tools only for agents that declare folder skills.

Upgrading causes a **one-time redeploy** of existing agents: the new `Skill`
fields appear in `hash_model`'s full `model_dump` (changing every skill's
canonical JSON), and the updated template runtime changes the template digest
anyway. This is normal for a version upgrade and `vystak plan` surfaces it.
The only behavior change for existing configs is the newly implemented
inline-`prompt` append, which affects only users who set `prompt` expecting
the documented behavior.

## See also

- `docs/superpowers/specs/2026-04-25-subagents-design.md` — the
  declare-in-schema → build-tools-at-runtime pattern this mirrors.
- `docs/superpowers/specs/2026-05-02-framework-template-design.md` — the
  no-codegen template runtime this plugs into.
- `website/docs/concepts/agents.md` — user-facing Skills narrative.
- PROJECT_PLAN.md "Shared skill library" — the pip-packaging aspiration this
  deliberately does not tackle.
