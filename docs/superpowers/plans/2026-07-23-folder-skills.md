# Folder Skills Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Skills can be folders of packaged instructions (`skills/<name>/SKILL.md` + resources) declared on agents, bundled into containers, and consumed at runtime via progressive disclosure (`load_skill` / `read_skill_file` tools).

**Architecture:** Extend the existing `Skill` Pydantic model (new `description`/`path`/`content_digest` fields) — one unified skill concept. A load-time resolver (`vystak/schema/skill_resolver.py`) parses SKILL.md frontmatter and computes a folder content digest so the existing hash engine detects skill edits. A new template-runtime module (`_vystak/runtime/skills.py`, mirroring `subagents.py`) renders the system-prompt skill listing and builds the two disclosure tools, wired into `prompt_callable.py` and `app_factory.py`.

**Tech Stack:** Python 3.11+, Pydantic v2, PyYAML, LangChain `@tool`, pytest. Monorepo commands via `uv run` from repo root.

**Spec:** `docs/superpowers/specs/2026-07-23-folder-skills-design.md`

## Global Constraints

- Public repo — no real credentials anywhere; tests use obvious fakes (`mock-*`, `claude-sonnet-4-20250514` model names are fine).
- The four live CI gates must stay green: `just lint-python`, `just test-python`, `just typecheck-typescript`, `just test-typescript` (i.e. `just ci-live`). `typecheck-python` and `lint-typescript` are known-red baselines — do not try to fix them, but don't add new pyright errors knowingly.
- Run `uv run ruff format packages/python/` + `uv run ruff check packages/python/` before each commit.
- SKILL.md frontmatter allowed keys: exactly `name`, `description`, `tools`. `description` is required and non-empty. Frontmatter `name` must equal the skill name.
- Resolution is idempotent: a skill with `content_digest` already set is never re-resolved (bundled `agent.json` arrives pre-resolved in containers).
- Inline skills (any `tools` or `prompt` set, no `path`) are never touched by the resolver — declaration wins over a same-named folder.
- All tests below run from the repo root.

---

### Task 1: Schema — new Skill fields, string shorthand, duplicate-name validation

**Files:**
- Modify: `packages/python/vystak/src/vystak/schema/skill.py`
- Modify: `packages/python/vystak/src/vystak/schema/agent.py`
- Test: `packages/python/vystak/tests/test_skill.py` (append)
- Test: `packages/python/vystak/tests/test_agent.py` (append)

**Interfaces:**
- Consumes: existing `Skill(NamedModel)`, `Agent(NamedModel)`.
- Produces: `Skill.description: str | None`, `Skill.path: str | None`, `Skill.content_digest: str | None` (all default `None`); `Agent(skills=["research", ...])` string shorthand → `Skill(name="research")`; duplicate skill names on one agent raise `ValueError` at validation.

- [ ] **Step 1: Write the failing tests**

Append to `packages/python/vystak/tests/test_skill.py`:

```python
class TestFolderSkillFields:
    def test_new_fields_default_none(self):
        skill = Skill(name="research")
        assert skill.description is None
        assert skill.path is None
        assert skill.content_digest is None

    def test_folder_fields_roundtrip(self):
        skill = Skill(
            name="research",
            description="Deep-research workflow.",
            path="skills/research",
            content_digest="abc123",
        )
        restored = Skill.model_validate(skill.model_dump())
        assert restored == skill
```

Append to `packages/python/vystak/tests/test_agent.py` (self-contained — does not rely on file-local helpers):

```python
class TestSkillShorthand:
    def _make_agent(self, **overrides):
        from vystak.schema.model import Model
        from vystak.schema.provider import Provider

        anthropic = Provider(name="anthropic", type="anthropic")
        model = Model(
            name="claude", provider=anthropic, model_name="claude-sonnet-4-20250514"
        )
        defaults = {
            "name": "support",
            "framework": "langchain-python",
            "default_model": model,
        }
        defaults.update(overrides)
        from vystak.schema.agent import Agent

        return Agent(**defaults)

    def test_string_shorthand_normalizes_to_skill(self):
        from vystak.schema.skill import Skill

        agent = self._make_agent(skills=["research"])
        assert isinstance(agent.skills[0], Skill)
        assert agent.skills[0].name == "research"
        assert agent.skills[0].tools == []

    def test_mixed_shorthand_and_objects(self):
        from vystak.schema.skill import Skill

        agent = self._make_agent(
            skills=["research", Skill(name="orders", tools=["lookup_order"])]
        )
        assert [s.name for s in agent.skills] == ["research", "orders"]
        assert agent.skills[1].tools == ["lookup_order"]

    def test_duplicate_skill_names_rejected(self):
        import pytest
        from vystak.schema.skill import Skill

        with pytest.raises(Exception, match="duplicate skill name"):
            self._make_agent(
                skills=[Skill(name="research"), Skill(name="research", tools=["t"])]
            )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/python/vystak/tests/test_skill.py packages/python/vystak/tests/test_agent.py -v -k "FolderSkillFields or SkillShorthand"`
Expected: FAIL — `description` attribute errors / string not coerced to Skill.

- [ ] **Step 3: Implement schema changes**

In `packages/python/vystak/src/vystak/schema/skill.py`, replace the `Skill` class body:

```python
class Skill(NamedModel):
    """A reusable capability — tools, an inline prompt, and/or a folder of
    packaged instructions (skills/<name>/SKILL.md) loaded on demand.

    `description`, `path`, and `content_digest` are filled by
    `vystak.schema.skill_resolver.resolve_folder_skills` for folder skills;
    inline (tools/prompt-only) skills leave them None.
    """

    tools: list[str] = []
    prompt: str | None = None
    description: str | None = None
    path: str | None = None
    content_digest: str | None = None
    guardrails: dict | None = None
    requires: SkillRequirements | None = None
    version: str = "0.1.0"
    dependencies: list[str] | None = None
```

In `packages/python/vystak/src/vystak/schema/agent.py`:

1. Extend the pydantic import (line 5) to:

```python
from pydantic import field_validator, model_validator
```

2. Add these two validators inside `Agent` (after `_validate_subagents`):

```python
    @field_validator("skills", mode="before")
    @classmethod
    def _normalize_skill_shorthand(cls, v):
        """`skills: ["research"]` is shorthand for `Skill(name="research")`."""
        if not isinstance(v, list):
            return v
        return [{"name": item} if isinstance(item, str) else item for item in v]

    @model_validator(mode="after")
    def _validate_skills_unique(self) -> Self:
        seen: set[str] = set()
        for s in self.skills:
            if s.name in seen:
                raise ValueError(
                    f"Agent '{self.name}' has duplicate skill name '{s.name}'."
                )
            seen.add(s.name)
        return self
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/python/vystak/tests/test_skill.py packages/python/vystak/tests/test_agent.py -v`
Expected: PASS (all — including pre-existing tests in both files).

- [ ] **Step 5: Full package tests + lint, then commit**

```bash
uv run pytest packages/python/vystak/ -q
uv run ruff format packages/python/vystak/ && uv run ruff check packages/python/vystak/
git add packages/python/vystak/src/vystak/schema/skill.py packages/python/vystak/src/vystak/schema/agent.py packages/python/vystak/tests/test_skill.py packages/python/vystak/tests/test_agent.py
git commit -m "feat(schema): folder-skill fields on Skill + skills string shorthand"
```

---

### Task 2: Skill resolver — SKILL.md parsing, content digest, folder resolution

**Files:**
- Create: `packages/python/vystak/src/vystak/schema/skill_resolver.py`
- Test: `packages/python/vystak/tests/test_skill_resolver.py` (create)
- Test: `packages/python/vystak/tests/test_tree.py` (append hash tests)

**Interfaces:**
- Consumes: `Skill` fields from Task 1; `Agent.skills`, `Agent.subagents`.
- Produces (used by Task 3 loaders and Task 4 runtime):
  - `parse_skill_md(text: str) -> tuple[dict, str]` — (frontmatter dict, body); raises `ValueError` on malformed/unknown keys.
  - `compute_skill_digest(folder: Path) -> str` — sha256 hex over sorted relative paths + bytes.
  - `resolve_folder_skills(agents: list[Agent], project_dir: Path) -> None` — fills `description`/`tools`/`path`/`content_digest` in place; recurses into subagents; idempotent; raises `ValueError` with the spec's error messages.

- [ ] **Step 1: Write the failing tests**

Create `packages/python/vystak/tests/test_skill_resolver.py`:

```python
"""resolve_folder_skills — SKILL.md parsing, digest, and error cases."""

import pytest

from vystak.schema.agent import Agent
from vystak.schema.model import Model
from vystak.schema.provider import Provider
from vystak.schema.skill import Skill
from vystak.schema.skill_resolver import (
    compute_skill_digest,
    parse_skill_md,
    resolve_folder_skills,
)


def make_agent(**overrides):
    anthropic = Provider(name="anthropic", type="anthropic")
    model = Model(
        name="claude", provider=anthropic, model_name="claude-sonnet-4-20250514"
    )
    defaults = {
        "name": "support",
        "framework": "langchain-python",
        "default_model": model,
    }
    defaults.update(overrides)
    return Agent(**defaults)


SKILL_MD = (
    "---\n"
    "name: research\n"
    "description: Deep-research workflow.\n"
    "tools: [web_search]\n"
    "---\n"
    "When asked to research, follow this process.\n"
)


def write_skill(root, name="research", text=SKILL_MD):
    folder = root / "skills" / name
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text(text)
    return folder


class TestParseSkillMd:
    def test_happy_path(self):
        meta, body = parse_skill_md(SKILL_MD)
        assert meta["name"] == "research"
        assert meta["description"] == "Deep-research workflow."
        assert meta["tools"] == ["web_search"]
        assert body.startswith("When asked to research")

    def test_missing_frontmatter_raises(self):
        with pytest.raises(ValueError, match="frontmatter"):
            parse_skill_md("no frontmatter here\n")

    def test_unclosed_frontmatter_raises(self):
        with pytest.raises(ValueError, match="not closed"):
            parse_skill_md("---\nname: x\n")

    def test_unknown_keys_rejected(self):
        text = "---\nname: x\ndescription: d\nbogus: 1\n---\nbody\n"
        with pytest.raises(ValueError, match="bogus"):
            parse_skill_md(text)


class TestComputeSkillDigest:
    def test_deterministic(self, tmp_path):
        folder = write_skill(tmp_path)
        assert compute_skill_digest(folder) == compute_skill_digest(folder)

    def test_edit_changes_digest(self, tmp_path):
        folder = write_skill(tmp_path)
        d1 = compute_skill_digest(folder)
        (folder / "SKILL.md").write_text(SKILL_MD + "more\n")
        assert compute_skill_digest(folder) != d1

    def test_added_resource_changes_digest(self, tmp_path):
        folder = write_skill(tmp_path)
        d1 = compute_skill_digest(folder)
        (folder / "sources.md").write_text("some sources\n")
        assert compute_skill_digest(folder) != d1

    def test_rename_changes_digest(self, tmp_path):
        folder = write_skill(tmp_path)
        (folder / "a.md").write_text("x\n")
        d1 = compute_skill_digest(folder)
        (folder / "a.md").rename(folder / "b.md")
        assert compute_skill_digest(folder) != d1


class TestResolveFolderSkills:
    def test_shorthand_resolves_folder(self, tmp_path):
        write_skill(tmp_path)
        agent = make_agent(skills=["research"])
        resolve_folder_skills([agent], tmp_path)
        skill = agent.skills[0]
        assert skill.description == "Deep-research workflow."
        assert skill.tools == ["web_search"]
        assert skill.path == "skills/research"
        assert skill.content_digest

    def test_missing_folder_raises(self, tmp_path):
        agent = make_agent(skills=["research"])
        with pytest.raises(ValueError, match="skills/research/SKILL.md"):
            resolve_folder_skills([agent], tmp_path)

    def test_frontmatter_name_mismatch_raises(self, tmp_path):
        write_skill(tmp_path, name="other", text=SKILL_MD)
        agent = make_agent(skills=["other"])
        with pytest.raises(ValueError, match="does not match"):
            resolve_folder_skills([agent], tmp_path)

    def test_missing_description_raises(self, tmp_path):
        write_skill(tmp_path, text="---\nname: research\n---\nbody\n")
        agent = make_agent(skills=["research"])
        with pytest.raises(ValueError, match="description"):
            resolve_folder_skills([agent], tmp_path)

    def test_explicit_path(self, tmp_path):
        folder = tmp_path / "shared" / "deep-research"
        folder.mkdir(parents=True)
        (folder / "SKILL.md").write_text(SKILL_MD)
        agent = make_agent(
            skills=[Skill(name="research", path="shared/deep-research")]
        )
        resolve_folder_skills([agent], tmp_path)
        assert agent.skills[0].description == "Deep-research workflow."
        assert agent.skills[0].path == "shared/deep-research"

    def test_explicit_path_missing_raises(self, tmp_path):
        agent = make_agent(skills=[Skill(name="research", path="nope/research")])
        with pytest.raises(ValueError, match="nope/research"):
            resolve_folder_skills([agent], tmp_path)

    def test_inline_skill_untouched_even_with_matching_folder(self, tmp_path):
        write_skill(tmp_path)
        agent = make_agent(skills=[Skill(name="research", tools=["my_tool"])])
        resolve_folder_skills([agent], tmp_path)
        assert agent.skills[0].description is None
        assert agent.skills[0].path is None
        assert agent.skills[0].tools == ["my_tool"]

    def test_inline_prompt_skill_untouched(self, tmp_path):
        agent = make_agent(skills=[Skill(name="ops", prompt="Verify orders.")])
        resolve_folder_skills([agent], tmp_path)  # no folder needed, no error
        assert agent.skills[0].content_digest is None

    def test_idempotent(self, tmp_path):
        write_skill(tmp_path)
        agent = make_agent(skills=["research"])
        resolve_folder_skills([agent], tmp_path)
        digest = agent.skills[0].content_digest
        tools = list(agent.skills[0].tools)
        resolve_folder_skills([agent], tmp_path)
        assert agent.skills[0].content_digest == digest
        assert agent.skills[0].tools == tools  # no duplicate merge

    def test_subagents_resolved(self, tmp_path):
        write_skill(tmp_path)
        sub = make_agent(name="researcher", skills=["research"])
        agent = make_agent(subagents=[sub])
        resolve_folder_skills([agent], tmp_path)
        assert agent.subagents[0].skills[0].content_digest
```

Append to `packages/python/vystak/tests/test_tree.py` (module level, end of file — uses the file's existing `make_agent` helper):

```python
def test_folder_skill_file_edit_changes_root_hash(tmp_path):
    from vystak.schema.skill_resolver import resolve_folder_skills

    folder = tmp_path / "skills" / "research"
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text(
        "---\nname: research\ndescription: Research workflow.\n---\nBody v1.\n"
    )
    agent1 = make_agent(skills=[Skill(name="research")])
    resolve_folder_skills([agent1], tmp_path)
    tree1 = hash_agent(agent1)

    (folder / "SKILL.md").write_text(
        "---\nname: research\ndescription: Research workflow.\n---\nBody v2.\n"
    )
    agent2 = make_agent(skills=[Skill(name="research")])
    resolve_folder_skills([agent2], tmp_path)
    tree2 = hash_agent(agent2)

    assert tree1.skills != tree2.skills
    assert tree1.root != tree2.root


def test_folder_skill_unchanged_folder_same_hash(tmp_path):
    from vystak.schema.skill_resolver import resolve_folder_skills

    folder = tmp_path / "skills" / "research"
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text(
        "---\nname: research\ndescription: Research workflow.\n---\nBody.\n"
    )
    agent1 = make_agent(skills=[Skill(name="research")])
    resolve_folder_skills([agent1], tmp_path)
    agent2 = make_agent(skills=[Skill(name="research")])
    resolve_folder_skills([agent2], tmp_path)
    assert hash_agent(agent1).root == hash_agent(agent2).root
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/python/vystak/tests/test_skill_resolver.py packages/python/vystak/tests/test_tree.py -v`
Expected: FAIL — `ModuleNotFoundError: vystak.schema.skill_resolver`.

- [ ] **Step 3: Implement the resolver**

Create `packages/python/vystak/src/vystak/schema/skill_resolver.py`:

```python
"""Resolve folder skills (skills/<name>/SKILL.md) into Skill models.

Folder resolution happens at load time — Pydantic models stay
filesystem-free. Callers pass the project directory that skill paths are
relative to. Resolution is idempotent: a skill whose `content_digest` is
already set is left untouched (the CLI-bundled agent.json arrives
pre-resolved inside containers).
"""

import hashlib
from pathlib import Path

import yaml

from vystak.schema.agent import Agent
from vystak.schema.skill import Skill

ALLOWED_FRONTMATTER_KEYS = {"name", "description", "tools"}


def parse_skill_md(text: str) -> tuple[dict, str]:
    """Split SKILL.md into (frontmatter dict, body)."""
    if not text.startswith("---"):
        raise ValueError("SKILL.md must start with '---' YAML frontmatter")
    parts = text.split("---", 2)
    if len(parts) < 3:
        raise ValueError("SKILL.md frontmatter is not closed with '---'")
    meta = yaml.safe_load(parts[1]) or {}
    if not isinstance(meta, dict):
        raise ValueError("SKILL.md frontmatter must be a YAML mapping")
    unknown = sorted(set(meta) - ALLOWED_FRONTMATTER_KEYS)
    if unknown:
        raise ValueError(
            f"Unknown SKILL.md frontmatter keys: {unknown}. "
            f"Allowed: {sorted(ALLOWED_FRONTMATTER_KEYS)}"
        )
    return meta, parts[2].lstrip("\n")


def compute_skill_digest(folder: Path) -> str:
    """sha256 over sorted relative paths + file bytes. Any edit changes it."""
    h = hashlib.sha256()
    for f in sorted(folder.rglob("*")):
        if not f.is_file():
            continue
        h.update(f.relative_to(folder).as_posix().encode())
        h.update(b"\0")
        h.update(f.read_bytes())
        h.update(b"\0")
    return h.hexdigest()


def resolve_folder_skills(agents: list[Agent], project_dir: Path) -> None:
    """Fill folder-skill fields in place for agents and their subagents."""
    for agent in agents:
        for skill in agent.skills:
            _resolve_one(agent, skill, project_dir)
        resolve_folder_skills(agent.subagents, project_dir)


def _resolve_one(agent: Agent, skill: Skill, project_dir: Path) -> None:
    if skill.content_digest is not None:
        return  # already resolved (e.g. bundled agent.json)
    if skill.path is None and (skill.tools or skill.prompt):
        return  # inline skill — declaration wins over a same-named folder
    rel = skill.path or f"skills/{skill.name}"
    folder = project_dir / rel
    skill_md = folder / "SKILL.md"
    if not skill_md.exists():
        if skill.path is not None:
            raise ValueError(
                f"Skill '{skill.name}' on agent '{agent.name}' declares "
                f"path '{rel}' but {skill_md} does not exist."
            )
        raise ValueError(
            f"Skill '{skill.name}' on agent '{agent.name}' has no tools, "
            f"prompt, or {rel}/SKILL.md. Create the folder or declare tools."
        )
    meta, _body = parse_skill_md(skill_md.read_text())
    if meta.get("name") != skill.name:
        raise ValueError(
            f"{skill_md}: frontmatter name '{meta.get('name')}' does not "
            f"match skill name '{skill.name}'."
        )
    description = (meta.get("description") or "").strip()
    if not description:
        raise ValueError(
            f"{skill_md}: frontmatter must include a non-empty description "
            f"— the agent uses it to decide when to load the skill."
        )
    fm_tools = meta.get("tools") or []
    if not isinstance(fm_tools, list) or not all(
        isinstance(t, str) for t in fm_tools
    ):
        raise ValueError(f"{skill_md}: frontmatter 'tools' must be a list of strings")
    skill.description = description
    for t in fm_tools:
        if t not in skill.tools:
            skill.tools.append(t)
    skill.path = rel
    skill.content_digest = compute_skill_digest(folder)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/python/vystak/tests/test_skill_resolver.py packages/python/vystak/tests/test_tree.py -v`
Expected: PASS.

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff format packages/python/vystak/ && uv run ruff check packages/python/vystak/
git add packages/python/vystak/src/vystak/schema/skill_resolver.py packages/python/vystak/tests/test_skill_resolver.py packages/python/vystak/tests/test_tree.py
git commit -m "feat(schema): skill_resolver — SKILL.md frontmatter + folder content digest"
```

---

### Task 3: Loader integration — schema loader, CLI loader, template config

**Files:**
- Modify: `packages/python/vystak/src/vystak/schema/loader.py`
- Modify: `packages/python/vystak-cli/src/vystak_cli/loader.py`
- Modify: `packages/python/vystak-template-langchain-python/_vystak/runtime/config.py`
- Test: `packages/python/vystak/tests/test_skill_resolver.py` (append)
- Test: `packages/python/vystak-cli/tests/test_loader.py` (append)

**Interfaces:**
- Consumes: `resolve_folder_skills(agents, project_dir)` from Task 2.
- Produces: `vystak.schema.loader.load_agent(path)` returns a folder-resolved Agent (resolved against `path.parent`); `vystak_cli.loader.load_definitions(paths)` resolves every loaded agent against its definition file's parent dir; `_vystak/runtime/config.py::load_agent` resolves the `.py` dev path (`.yaml` goes through the schema loader, `agent.json` is pre-resolved).

- [ ] **Step 1: Write the failing tests**

Append to `packages/python/vystak/tests/test_skill_resolver.py`:

```python
class TestLoaderIntegration:
    def test_load_agent_resolves_folder_skills(self, tmp_path):
        from vystak.schema.loader import load_agent

        write_skill(tmp_path)
        (tmp_path / "agent.yaml").write_text(
            "name: support\n"
            "framework: langchain-python\n"
            "default_model:\n"
            "  name: claude\n"
            "  provider: {name: anthropic, type: anthropic}\n"
            "  model_name: claude-sonnet-4-20250514\n"
            "skills: [research]\n"
        )
        agent = load_agent(tmp_path / "agent.yaml")
        assert agent.skills[0].description == "Deep-research workflow."
        assert agent.skills[0].content_digest
```

Append to `packages/python/vystak-cli/tests/test_loader.py`:

```python
class TestFolderSkillResolution:
    SKILL_MD = (
        "---\n"
        "name: research\n"
        "description: Deep-research workflow.\n"
        "---\n"
        "When asked to research, follow this process.\n"
    )

    def _write_skill(self, root):
        folder = root / "skills" / "research"
        folder.mkdir(parents=True)
        (folder / "SKILL.md").write_text(self.SKILL_MD)

    def test_python_definitions_resolve_folder_skills(self, tmp_path):
        from vystak_cli.loader import load_definitions

        self._write_skill(tmp_path)
        (tmp_path / "vystak.py").write_text(
            "import vystak as ast\n"
            "anthropic = ast.Provider(name='anthropic', type='anthropic')\n"
            "model = ast.Model(name='m', provider=anthropic,"
            " model_name='claude-sonnet-4-20250514')\n"
            "agent = ast.Agent(name='support', framework='langchain-python',"
            " default_model=model, skills=['research'])\n"
        )
        defs = load_definitions([tmp_path / "vystak.py"])
        assert defs.agents[0].skills[0].description == "Deep-research workflow."
        assert defs.agents[0].skills[0].content_digest

    def test_multi_yaml_resolves_folder_skills(self, tmp_path):
        from vystak_cli.loader import load_definitions

        self._write_skill(tmp_path)
        (tmp_path / "vystak.yaml").write_text(
            "providers:\n"
            "  anthropic: {type: anthropic}\n"
            "models:\n"
            "  m:\n"
            "    provider: anthropic\n"
            "    model_name: claude-sonnet-4-20250514\n"
            "agents:\n"
            "  - name: support\n"
            "    framework: langchain-python\n"
            "    default_model: m\n"
            "    skills: [research]\n"
        )
        defs = load_definitions([tmp_path / "vystak.yaml"])
        assert defs.agents[0].skills[0].content_digest

    def test_bundle_includes_skills_dir(self, tmp_path):
        from vystak_cli.commands.apply import _bundle_project_dir

        self._write_skill(tmp_path)
        (tmp_path / "server.py").write_text("app = None\n")
        bundle = _bundle_project_dir(tmp_path)
        assert "skills/research/SKILL.md" in bundle.files
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/python/vystak/tests/test_skill_resolver.py::TestLoaderIntegration packages/python/vystak-cli/tests/test_loader.py::TestFolderSkillResolution -v`
Expected: FAIL — `content_digest` is `None` / `description` is `None`.

- [ ] **Step 3: Implement loader hooks**

In `packages/python/vystak/src/vystak/schema/loader.py`, add to imports:

```python
from vystak.schema.skill_resolver import resolve_folder_skills
```

and change the end of `load_agent` from `return Agent.model_validate(data)` to:

```python
    agent = Agent.model_validate(data)
    resolve_folder_skills([agent], path.parent)
    return agent
```

In `packages/python/vystak-cli/src/vystak_cli/loader.py`, add inside the protected import block (alongside the other `vystak.schema` imports):

```python
    from vystak.schema.skill_resolver import resolve_folder_skills
```

In `load_definitions`, capture the agent count after the dir→convention-file resolution and resolve newly loaded agents at the end of each loop iteration. The loop becomes:

```python
    for path in paths:
        path = Path(path)

        if path.is_dir():
            found = None
            for conv in CONVENTION_FILES:
                candidate = path / conv
                if candidate.exists():
                    found = candidate
                    break
            if found is None:
                raise FileNotFoundError(f"No agent definition found in {path}")
            path = found

        before = len(defs.agents)

        if path.suffix in (".yaml", ".yml"):
            ...  # existing body unchanged
        elif path.suffix == ".py":
            defs.extend(_load_definitions_from_python(path))
        else:
            raise ValueError(f"Unsupported file type: {path.suffix}")

        resolve_folder_skills(defs.agents[before:], path.parent)
```

(Only the `before = len(defs.agents)` line and the trailing `resolve_folder_skills(...)` line are new; re-resolution of single-doc YAML agents already resolved by `load_agent` is a no-op by idempotency.)

In `packages/python/vystak-template-langchain-python/_vystak/runtime/config.py`, add the import:

```python
from vystak.schema.skill_resolver import resolve_folder_skills
```

and in `_load_py`, before `return agent`:

```python
    resolve_folder_skills([agent], path.parent)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/python/vystak/tests/test_skill_resolver.py packages/python/vystak-cli/tests/ -v`
Expected: PASS (all — including pre-existing CLI loader tests).

- [ ] **Step 5: Guard against regressions in both packages, lint, commit**

```bash
uv run pytest packages/python/vystak/ packages/python/vystak-cli/ -q
uv run ruff format packages/python/ && uv run ruff check packages/python/
git add packages/python/vystak/src/vystak/schema/loader.py packages/python/vystak-cli/src/vystak_cli/loader.py packages/python/vystak-template-langchain-python/_vystak/runtime/config.py packages/python/vystak/tests/test_skill_resolver.py packages/python/vystak-cli/tests/test_loader.py
git commit -m "feat(loader): resolve folder skills at definition load time"
```

---

### Task 4: Runtime skills module — prompt section + disclosure tools

**Files:**
- Create: `packages/python/vystak-template-langchain-python/_vystak/runtime/skills.py`
- Test: `packages/python/vystak-template-langchain-python/tests/test_skills.py` (create)

**Interfaces:**
- Consumes: resolved `Skill` objects (`name`, `description`, `prompt`, `path` attributes; duck-typed via `getattr` like the rest of the runtime).
- Produces (used by Task 5 wiring):
  - `skills_prompt_section(agent) -> str` — "## Skills" listing (+ `load_skill` preamble when folder skills exist) + inline-skill `prompt` appends; `""` when nothing to surface.
  - `build_skill_tools(agent, project_root: Path) -> list` — `[load_skill, read_skill_file]` LangChain tools when the agent has folder skills, else `[]`.

- [ ] **Step 1: Write the failing tests**

Create `packages/python/vystak-template-langchain-python/tests/test_skills.py`:

```python
"""Folder-skill runtime — prompt section + load_skill / read_skill_file."""

import os
from pathlib import Path

from _vystak.runtime.skills import build_skill_tools, skills_prompt_section
from vystak.schema.skill import Skill


def _agent(skills):
    class _A:
        name = "support"

    a = _A()
    a.skills = skills
    return a


def _folder_skill(name="research", path=None, description="Deep-research workflow."):
    return Skill(
        name=name,
        description=description,
        path=path or f"skills/{name}",
        content_digest="abc",
    )


def _write_skill_folder(root, name="research", body="Research like this.\n"):
    folder = root / "skills" / name
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: Deep-research workflow.\n---\n{body}"
    )
    return folder


class TestSkillsPromptSection:
    def test_empty_without_skills(self):
        assert skills_prompt_section(_agent([])) == ""

    def test_lists_described_skills_with_preamble(self):
        section = skills_prompt_section(_agent([_folder_skill()]))
        assert "## Skills" in section
        assert "load_skill" in section
        assert "- research: Deep-research workflow." in section

    def test_inline_skill_without_description_not_listed(self):
        section = skills_prompt_section(
            _agent([Skill(name="ops", tools=["lookup_order"])])
        )
        assert section == ""

    def test_inline_prompt_appended(self):
        section = skills_prompt_section(
            _agent([Skill(name="ops", tools=["t"], prompt="Always verify orders.")])
        )
        assert "Always verify orders." in section

    def test_no_preamble_without_folder_skills(self):
        inline = Skill(name="ops", tools=["t"], description="Order handling.")
        section = skills_prompt_section(_agent([inline]))
        assert "- ops: Order handling." in section
        assert "load_skill" not in section


class TestBuildSkillTools:
    def test_no_folder_skills_no_tools(self):
        agent = _agent([Skill(name="ops", tools=["t"])])
        assert build_skill_tools(agent, Path(".")) == []

    def test_load_skill_returns_body_and_resources(self, tmp_path):
        folder = _write_skill_folder(tmp_path)
        (folder / "sources.md").write_text("List of sources.\n")
        tools = build_skill_tools(_agent([_folder_skill()]), tmp_path)
        assert sorted(t.name for t in tools) == ["load_skill", "read_skill_file"]
        load_skill = next(t for t in tools if t.name == "load_skill")
        out = load_skill.invoke({"name": "research"})
        assert "Research like this." in out
        assert "---" not in out  # frontmatter stripped
        assert "sources.md" in out

    def test_load_skill_unknown_name(self, tmp_path):
        _write_skill_folder(tmp_path)
        tools = build_skill_tools(_agent([_folder_skill()]), tmp_path)
        load_skill = next(t for t in tools if t.name == "load_skill")
        out = load_skill.invoke({"name": "nope"})
        assert "Unknown skill" in out
        assert "research" in out

    def test_read_skill_file(self, tmp_path):
        folder = _write_skill_folder(tmp_path)
        (folder / "sources.md").write_text("List of sources.\n")
        tools = build_skill_tools(_agent([_folder_skill()]), tmp_path)
        read = next(t for t in tools if t.name == "read_skill_file")
        out = read.invoke({"skill": "research", "path": "sources.md"})
        assert out == "List of sources.\n"

    def test_read_skill_file_missing_lists_available(self, tmp_path):
        folder = _write_skill_folder(tmp_path)
        (folder / "sources.md").write_text("x\n")
        tools = build_skill_tools(_agent([_folder_skill()]), tmp_path)
        read = next(t for t in tools if t.name == "read_skill_file")
        out = read.invoke({"skill": "research", "path": "nope.md"})
        assert "not found" in out
        assert "sources.md" in out

    def test_read_skill_file_rejects_traversal(self, tmp_path):
        _write_skill_folder(tmp_path)
        (tmp_path / "secret.txt").write_text("secret\n")
        tools = build_skill_tools(_agent([_folder_skill()]), tmp_path)
        read = next(t for t in tools if t.name == "read_skill_file")
        assert "Invalid path" in read.invoke(
            {"skill": "research", "path": "../../secret.txt"}
        )
        assert "Invalid path" in read.invoke(
            {"skill": "research", "path": str(tmp_path / "secret.txt")}
        )

    def test_read_skill_file_rejects_symlink_escape(self, tmp_path):
        folder = _write_skill_folder(tmp_path)
        (tmp_path / "secret.txt").write_text("secret\n")
        os.symlink(tmp_path / "secret.txt", folder / "link.md")
        tools = build_skill_tools(_agent([_folder_skill()]), tmp_path)
        read = next(t for t in tools if t.name == "read_skill_file")
        assert "Invalid path" in read.invoke(
            {"skill": "research", "path": "link.md"}
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/python/vystak-template-langchain-python/tests/test_skills.py -v`
Expected: FAIL — `ModuleNotFoundError: _vystak.runtime.skills`.

- [ ] **Step 3: Implement the runtime module**

Create `packages/python/vystak-template-langchain-python/_vystak/runtime/skills.py`:

```python
"""Folder-skill runtime: prompt listing + progressive-disclosure tools.

Folder skills (skills/<name>/SKILL.md bundled with the project) surface in
two stages: the system prompt lists each skill's name + description, and
the `load_skill` / `read_skill_file` tools fetch full instructions and
resource files on demand.
"""

from pathlib import Path
from typing import Any

from langchain_core.tools import tool


def _folder_skills(agent: Any) -> list[Any]:
    return [s for s in getattr(agent, "skills", []) if getattr(s, "path", None)]


def skills_prompt_section(agent: Any) -> str:
    """Skill listing + inline-skill prompt appends for the system prompt.

    Returns "" when the agent has nothing to surface.
    """
    skills = list(getattr(agent, "skills", []))
    folder = [s for s in skills if getattr(s, "path", None)]
    described = [
        s for s in skills if (getattr(s, "description", None) or "").strip()
    ]
    inline_prompts = [
        s.prompt.strip()
        for s in skills
        if not getattr(s, "path", None) and (getattr(s, "prompt", None) or "").strip()
    ]

    parts: list[str] = []
    if described:
        lines = "\n".join(f"- {s.name}: {s.description.strip()}" for s in described)
        if folder:
            parts.append(
                "## Skills\n"
                "You have the following skills. Before doing work that matches "
                "a skill's description, call load_skill(name) and follow its "
                "instructions.\n" + lines
            )
        else:
            parts.append("## Skills\n" + lines)
    parts.extend(inline_prompts)
    return "\n\n".join(parts)


def build_skill_tools(agent: Any, project_root: Path) -> list[Any]:
    """Return [load_skill, read_skill_file] when the agent has folder skills."""
    folder_skills = _folder_skills(agent)
    if not folder_skills:
        return []

    root = project_root.resolve()
    by_name = {s.name: root / s.path for s in folder_skills}
    valid = ", ".join(sorted(by_name))

    @tool
    def load_skill(name: str) -> str:
        """Load a skill's full instructions. Call this before doing work that
        matches a skill's description in your system prompt."""
        folder = by_name.get(name)
        if folder is None:
            return f"Unknown skill '{name}'. Available skills: {valid}"
        skill_md = folder / "SKILL.md"
        if not skill_md.is_file():
            return f"Skill '{name}' is missing SKILL.md at {skill_md}."
        body = _strip_frontmatter(skill_md.read_text())
        resources = _resource_files(folder)
        if resources:
            body += (
                "\n\nResource files: "
                + ", ".join(resources)
                + " — read them with read_skill_file."
            )
        return body

    @tool
    def read_skill_file(skill: str, path: str) -> str:
        """Read a resource file bundled with a skill. `path` is relative to
        the skill's folder, e.g. 'sources.md' or 'templates/report.md'."""
        folder = by_name.get(skill)
        if folder is None:
            return f"Unknown skill '{skill}'. Available skills: {valid}"
        folder = folder.resolve()
        target = (folder / path).resolve()
        if folder not in target.parents:
            return f"Invalid path '{path}': must stay inside the skill folder."
        if not target.is_file():
            available = ", ".join(_resource_files(folder)) or "none"
            return (
                f"File '{path}' not found in skill '{skill}'. "
                f"Available: {available}"
            )
        return target.read_text()

    return [load_skill, read_skill_file]


def _strip_frontmatter(text: str) -> str:
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            return parts[2].lstrip("\n")
    return text


def _resource_files(folder: Path) -> list[str]:
    return sorted(
        f.relative_to(folder).as_posix()
        for f in folder.rglob("*")
        if f.is_file() and f.name != "SKILL.md"
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/python/vystak-template-langchain-python/tests/test_skills.py -v`
Expected: PASS.

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff format packages/python/vystak-template-langchain-python/ && uv run ruff check packages/python/vystak-template-langchain-python/
git add packages/python/vystak-template-langchain-python/_vystak/runtime/skills.py packages/python/vystak-template-langchain-python/tests/test_skills.py
git commit -m "feat(runtime): folder-skill prompt section + load_skill/read_skill_file tools"
```

---

### Task 5: Wire skills into prompt_callable + app_factory; pin A2A card description

**Files:**
- Modify: `packages/python/vystak-template-langchain-python/_vystak/runtime/prompt_callable.py`
- Modify: `packages/python/vystak-template-langchain-python/_vystak/runtime/app_factory.py`
- Test: `packages/python/vystak-template-langchain-python/tests/test_skills.py` (append)

**Interfaces:**
- Consumes: `skills_prompt_section` / `build_skill_tools` from Task 4; resolved agents from Task 3.
- Produces: system prompt = instructions + skills section + memory + summary; graph tool list includes skill tools in both the initial build and the lifespan rebuild; `build_agent_card` skills carry real descriptions (no card code change — behavior test only).

- [ ] **Step 1: Write the failing tests**

Append to `packages/python/vystak-template-langchain-python/tests/test_skills.py`:

```python
import pytest
from langchain_core.messages import HumanMessage


class TestPromptWiring:
    @pytest.mark.asyncio
    async def test_prompt_includes_skills_section(self):
        from _vystak.runtime.prompt_callable import build_prompt

        agent = _agent([_folder_skill()])
        agent.instructions = "You are helpful."
        agent.compaction = None
        agent.memory = None
        fn = build_prompt(agent, memory_mgr=None, compactor=None, pruner=None)
        msgs = await fn({"messages": [HumanMessage(content="hi")]})
        assert "You are helpful." in msgs[0].content
        assert "- research: Deep-research workflow." in msgs[0].content
        assert "load_skill" in msgs[0].content

    @pytest.mark.asyncio
    async def test_prompt_appends_inline_skill_prompt(self):
        from _vystak.runtime.prompt_callable import build_prompt

        agent = _agent(
            [Skill(name="ops", tools=["t"], prompt="Always verify orders.")]
        )
        agent.instructions = "You are helpful."
        agent.compaction = None
        agent.memory = None
        fn = build_prompt(agent, memory_mgr=None, compactor=None, pruner=None)
        msgs = await fn({"messages": [HumanMessage(content="hi")]})
        assert "Always verify orders." in msgs[0].content


class TestAppFactoryWiring:
    def test_config_load_resolves_and_app_builds_with_skill_tools(
        self, tmp_path, monkeypatch
    ):
        from _vystak.runtime.config import load_agent

        _write_skill_folder(tmp_path)
        (tmp_path / "vystak.yaml").write_text(
            "name: support\n"
            "framework: langchain-python\n"
            "default_model:\n"
            "  name: claude\n"
            "  provider: {name: anthropic, type: anthropic}\n"
            "  model_name: claude-sonnet-4-20250514\n"
            "skills: [research]\n"
        )
        agent = load_agent(str(tmp_path / "vystak.yaml"))
        assert agent.skills[0].content_digest

        tools = build_skill_tools(agent, tmp_path)
        assert sorted(t.name for t in tools) == ["load_skill", "read_skill_file"]

        monkeypatch.chdir(tmp_path)
        from _vystak.runtime.app_factory import build_agent_app

        app = build_agent_app(agent)
        assert len(app.routes) >= 7


class TestAgentCard:
    def test_card_carries_skill_description(self):
        from _vystak.runtime.a2a_native.card import build_agent_card

        agent = _agent([_folder_skill()])
        agent.instructions = "You are helpful."
        card = build_agent_card(agent, base_url="http://agent:8000")
        assert card.skills[0].description == "Deep-research workflow."
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/python/vystak-template-langchain-python/tests/test_skills.py -v`
Expected: `TestPromptWiring` FAILS (skills section absent). `TestAgentCard` passes already (schema field landed in Task 1). `TestAppFactoryWiring` may pass on route count alone — the load-bearing assertions are the resolver + tool ones, which must pass, and the prompt tests, which must fail before wiring.

- [ ] **Step 3: Wire the runtime**

In `packages/python/vystak-template-langchain-python/_vystak/runtime/prompt_callable.py`, add the import:

```python
from _vystak.runtime.skills import skills_prompt_section
```

and in `build_prompt`, after `instructions = (agent.instructions or "").strip()`:

```python
    skills_section = skills_prompt_section(agent)
```

then inside `_prompt`, replace `sys_parts = [instructions] if instructions else []` with:

```python
        sys_parts = [instructions] if instructions else []
        if skills_section:
            sys_parts.append(skills_section)
```

In `packages/python/vystak-template-langchain-python/_vystak/runtime/app_factory.py`:

1. Add the import (alphabetical with the other `_vystak.runtime` imports):

```python
from _vystak.runtime.skills import build_skill_tools
```

2. After `subagent_tools = build_subagent_tools(agent)` (line 86), add:

```python
    skill_tools = build_skill_tools(agent, Path("."))
```

3. Change both `build_graph` tool lists:
   - Initial build (line 115): `tools=user_tools + workspace_tools + subagent_tools + skill_tools,`
   - Lifespan rebuild (line 161): `tools=user_tools + workspace_tools + subagent_tools + skill_tools + mcp_tools,`

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/python/vystak-template-langchain-python/tests/ -v`
Expected: PASS (all — including pre-existing prompt/app_factory/tools tests).

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff format packages/python/vystak-template-langchain-python/ && uv run ruff check packages/python/vystak-template-langchain-python/
git add packages/python/vystak-template-langchain-python/_vystak/runtime/prompt_callable.py packages/python/vystak-template-langchain-python/_vystak/runtime/app_factory.py packages/python/vystak-template-langchain-python/tests/test_skills.py
git commit -m "feat(runtime): wire skill prompt section + disclosure tools into app factory"
```

---

### Task 6: Example — examples/docker-skills

**Files:**
- Create: `examples/docker-skills/` (scaffolded via `vystak init`, then customized)
- Create: `examples/docker-skills/vystak.yaml` (multi-doc, replaces starter)
- Create: `examples/docker-skills/skills/research/SKILL.md`
- Create: `examples/docker-skills/skills/research/sources.md`
- Create: `examples/docker-skills/tools/lookup_order.py`
- Create: `examples/docker-skills/README.md`

**Interfaces:**
- Consumes: everything from Tasks 1–5; `vystak init --framework langchain-python` scaffolding.
- Produces: a deployable example exercising both skill forms (folder + inline); Task 7's release cell loads it by path `examples/docker-skills` with `vystak.yaml` as the definition file.

- [ ] **Step 1: Scaffold the project**

```bash
uv run vystak init examples/docker-skills --framework langchain-python
```

Expected: `examples/docker-skills/` contains `server.py`, `Dockerfile`, `_vystak/`, `vystak.yaml`, `requirements.txt`.

- [ ] **Step 2: Write the definition and skill files**

Replace `examples/docker-skills/vystak.yaml` with:

```yaml
providers:
  docker: {type: docker}
  anthropic: {type: anthropic}

platforms:
  local: {type: docker, provider: docker, namespace: dev}

models:
  sonnet:
    provider: anthropic
    model_name: claude-sonnet-4-20250514

agents:
  - name: shop-agent
    framework: langchain-python
    instructions: |
      You are a helpful assistant for a small e-commerce shop.
    default_model: sonnet
    platform: local
    skills:
      - research                    # folder skill: skills/research/
      - name: orders                # inline skill: tools only
        tools: [lookup_order]
    secrets:
      - {name: ANTHROPIC_API_KEY}

channels:
  - name: chat
    type: chat
    platform: local
    config: {port: 8080}
    agents: [shop-agent]
```

Create `examples/docker-skills/skills/research/SKILL.md`:

```markdown
---
name: research
description: Product-research workflow — how to compare products, weigh reviews, and cite sources.
---
When the user asks you to research or compare products, follow this process:

1. Identify the 2-4 candidate products the user cares about.
2. For each candidate, note price range, key specs, and common complaints.
3. Weigh reviews by recency — discount anything older than two years.
4. Present a comparison table followed by a single recommendation.
5. Cite where each claim comes from, using the source conventions in
   `sources.md` (read it with read_skill_file).
```

Create `examples/docker-skills/skills/research/sources.md`:

```markdown
# Source conventions

- Prefer manufacturer spec sheets for hard numbers.
- Label every third-party claim with its origin, e.g. "(user reviews)".
- If two sources disagree, say so explicitly rather than averaging.
```

Create `examples/docker-skills/tools/lookup_order.py`:

```python
from langchain_core.tools import tool

_ORDERS = {"1001": "shipped", "1002": "processing", "1003": "delivered"}


@tool
def lookup_order(order_id: str) -> str:
    """Look up an order's status by its id."""
    status = _ORDERS.get(order_id)
    if status is None:
        return f"Order {order_id} not found."
    return f"Order {order_id}: {status}"
```

Create `examples/docker-skills/README.md`:

```markdown
# docker-skills — folder skills + inline skills

One agent (`shop-agent`) demonstrating both skill forms:

- **Folder skill** `research` — packaged instructions in
  `skills/research/SKILL.md` (+ `sources.md` resource file). The agent's
  system prompt lists the skill's name and description; the full
  instructions load on demand via the `load_skill` tool, and resource
  files via `read_skill_file` (progressive disclosure).
- **Inline skill** `orders` — a tool bundle pointing at
  `tools/lookup_order.py`.

## Deploy

```bash
export ANTHROPIC_API_KEY=sk-ant-your-key-here
vystak apply
```

## Try it

```bash
curl -X POST http://localhost:8080/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"vystak/shop-agent","messages":[{"role":"user","content":"Research the best budget mechanical keyboard for me."}]}'
```

The agent calls `load_skill("research")`, follows the packaged workflow,
and reads `sources.md` for citation conventions. Ask "where is order 1001?"
to exercise the inline `orders` skill instead.

Edit any file under `skills/research/` and run `vystak plan` — the content
digest changes the agent hash, so the plan shows a redeploy.

## Tear down

```bash
vystak destroy
```
```

- [ ] **Step 3: Verify the example loads through the CLI loader**

```bash
uv run python -c "
from pathlib import Path
from vystak_cli.loader import load_definitions
defs = load_definitions([Path('examples/docker-skills/vystak.yaml')])
a = defs.agents[0]
print(a.name, [s.name for s in a.skills])
assert a.skills[0].description, 'folder skill not resolved'
assert a.skills[0].content_digest
assert a.skills[1].tools == ['lookup_order']
print('OK')
"
```

Expected output ends with `OK`.

- [ ] **Step 4: Run the examples regression test**

Run: `uv run pytest packages/python/vystak/tests/test_examples.py -v`
Expected: PASS (the new example must not break example-wide invariants; if this test enumerates examples, `docker-skills` is now included).

- [ ] **Step 5: Commit**

```bash
git add examples/docker-skills/
git commit -m "feat(examples): docker-skills — folder skill + inline skill example"
```

---

### Task 7: Release cell — folder-skills load smoke

**Files:**
- Create: `packages/python/vystak-provider-docker/tests/release/test_skills_folder.py`

**Interfaces:**
- Consumes: `examples/docker-skills` from Task 6; runtime modules from Tasks 4–5.
- Produces: a `release_smoke` cell verifying the example resolves, builds skill tools, and constructs the FastAPI app (V1/V2-level, modeled on `test_template_smoke.py`'s load-only pattern).

- [ ] **Step 1: Write the release cell**

Create `packages/python/vystak-provider-docker/tests/release/test_skills_folder.py`:

```python
"""Release cell: folder skills — example resolves, skill tools build, app loads.

Load-only smoke modeled on test_template_smoke.py: verifies the
examples/docker-skills project resolves its folder skill (description +
content digest), produces the load_skill / read_skill_file tools, renders
the prompt section, and constructs the FastAPI app. Full Docker lifecycle
coverage comes from the existing D-cells; this cell gates the skills
surface itself.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.release_smoke


def _repo_root() -> Path:
    # packages/python/vystak-provider-docker/tests/release/test_skills_folder.py
    return Path(__file__).resolve().parents[5]


def test_docker_skills_example_loads_and_builds_skill_tools():
    example = _repo_root() / "examples" / "docker-skills"
    smoke = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys\n"
                "sys.path.insert(0, '.')\n"
                "from pathlib import Path\n"
                "from vystak_cli.loader import load_definitions\n"
                "from _vystak.runtime.skills import build_skill_tools, skills_prompt_section\n"
                "from _vystak.runtime.app_factory import build_agent_app\n"
                "defs = load_definitions([Path('vystak.yaml')])\n"
                "agent = defs.agents[0]\n"
                "assert agent.skills[0].content_digest, 'folder skill not resolved'\n"
                "tools = build_skill_tools(agent, Path('.'))\n"
                "print(sorted(t.name for t in tools))\n"
                "section = skills_prompt_section(agent)\n"
                "assert 'research' in section and 'load_skill' in section\n"
                "app = build_agent_app(agent)\n"
                "print(len(app.routes))\n"
            ),
        ],
        cwd=example,
        capture_output=True,
        text=True,
    )
    if smoke.returncode != 0:
        pytest.fail(
            f"Skills smoke failed: STDOUT={smoke.stdout!r}\nSTDERR={smoke.stderr!r}"
        )
    lines = smoke.stdout.strip().splitlines()
    assert "['load_skill', 'read_skill_file']" in lines[0]
    assert int(lines[-1]) >= 7
```

- [ ] **Step 2: Run the cell**

Run: `uv run pytest packages/python/vystak-provider-docker/tests/release/test_skills_folder.py -v -m release_smoke`
Expected: PASS.

- [ ] **Step 3: Confirm default test run still excludes it**

Run: `uv run pytest packages/python/vystak-provider-docker/tests/release/test_skills_folder.py -q`
Expected: test deselected (gated marker), 0 failures.

- [ ] **Step 4: Commit**

```bash
git add packages/python/vystak-provider-docker/tests/release/test_skills_folder.py
git commit -m "test(release): folder-skills load smoke cell"
```

---

### Task 8: Docs — agents.md Skills section + README

**Files:**
- Modify: `website/docs/concepts/agents.md` (the "## Adding skills (tools)" section, ~lines 154–195)
- Modify: `README.md` (the skills mention around line 96)
- Modify: `docs/superpowers/specs/2026-07-23-folder-skills-design.md` (no change — reference only)

**Interfaces:**
- Consumes: final behavior from Tasks 1–7.
- Produces: user-facing docs that match actual behavior (no more false claims about apply-time stub scaffolding or unimplemented prompt injection).

- [ ] **Step 1: Rewrite the Skills section in `website/docs/concepts/agents.md`**

Replace the section starting at `## Adding skills (tools)` through the paragraph ending `...when this skill's tools are in use.` with:

````markdown
## Adding skills

A **skill** is a named capability. It comes in two forms:

- a **folder skill** — packaged instructions in `skills/<name>/SKILL.md`
  next to your `vystak.yaml`, loaded by the agent on demand
- an **inline skill** — a named bundle of tools (Python functions the
  agent can call), optionally with a short prompt

<Tabs groupId="config-format">
<TabItem value="yaml" label="YAML" default>

```yaml
skills:
  - research                 # folder skill: skills/research/SKILL.md
  - name: ops                # inline skill: tool bundle
    tools:
      - lookup_order
      - process_refund
    prompt: Always verify the order before processing refunds.
```

</TabItem>
<TabItem value="python" label="Python">

```python
skills = [
    "research",              # folder skill: skills/research/SKILL.md
    vystak.Skill(
        name="ops",
        tools=["lookup_order", "process_refund"],
        prompt="Always verify the order before processing refunds.",
    ),
]
```

</TabItem>
</Tabs>

### Folder skills

A folder skill lives at `skills/<name>/SKILL.md` with YAML frontmatter:

```markdown
---
name: research
description: Product-research workflow — how to compare and cite sources.
tools: [web_search]        # optional, resolved from tools/
---
When asked to research a topic, follow this process...
```

`description` is required — it is the only thing the agent sees before
deciding to use the skill. The folder can hold extra resource files
(reference docs, templates) alongside SKILL.md.

At runtime the agent gets **progressive disclosure**: its system prompt
lists each skill's name and description, and two auto-provided tools —
`load_skill(name)` and `read_skill_file(skill, path)` — fetch the full
instructions and resource files only when needed. Editing any file in the
skill folder changes the agent's content hash, so `vystak plan` shows a
redeploy.

### Inline skills and tools

Tools are Python functions that live in a `tools/` directory next to your
`vystak.yaml`; each tool name maps to `tools/<name>.py` exporting a
function of the same name.

```python
# tools/lookup_order.py
from langchain_core.tools import tool

@tool
def lookup_order(order_id: str) -> str:
    """Look up an order by ID."""
    return f"Order {order_id}: shipped"
```

An inline skill's `prompt` field is appended to the agent's system prompt.

See `examples/docker-skills/` for a working project using both forms.
````

- [ ] **Step 2: Update the README skills snippet**

In `README.md`, find the skills snippet near line 96 (the `Skill(name="support", ...)` / skills YAML mention) and extend it to mention folder skills — after the existing inline-skill illustration, add one sentence:

```markdown
Skills can also be **folders of packaged instructions** — put a
`skills/<name>/SKILL.md` (with a `description` in its frontmatter) next to
your `vystak.yaml` and declare `skills: [<name>]`; the agent loads the full
instructions on demand. See `examples/docker-skills/`.
```

- [ ] **Step 3: Build the docs site to verify MDX validity**

Run: `just docs-build`
Expected: build succeeds (no broken MDX from the edited section).

- [ ] **Step 4: Commit**

```bash
git add website/docs/concepts/agents.md README.md
git commit -m "docs: folder skills — concepts + README"
```

---

### Task 9: Full-gate verification

**Files:** none new.

- [ ] **Step 1: Run the live CI gates**

Run: `just ci-live`
Expected: all four gates pass (`lint-python`, `typecheck-typescript`, `test-python`, `test-typescript`).

- [ ] **Step 2: Run the release smoke cells**

Run: `uv run pytest packages/python/vystak-provider-docker/tests/release/test_skills_folder.py packages/python/vystak-provider-docker/tests/release/test_template_smoke.py -v -m release_smoke`
Expected: PASS.

- [ ] **Step 3: Confirm pyright didn't regress on touched files**

Run: `uv run pyright packages/python/vystak/src/vystak/schema/skill_resolver.py packages/python/vystak-template-langchain-python/_vystak/runtime/skills.py`
Expected: 0 errors in the two new modules (the repo-wide baseline of ~370 pre-existing errors is out of scope).

- [ ] **Step 4: Final commit if any stragglers**

```bash
git status --short   # expect clean; commit anything intentional that remains
```
