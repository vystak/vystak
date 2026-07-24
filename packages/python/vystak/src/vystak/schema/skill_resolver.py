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
    if not isinstance(fm_tools, list) or not all(isinstance(t, str) for t in fm_tools):
        raise ValueError(f"{skill_md}: frontmatter 'tools' must be a list of strings")
    skill.description = description
    for t in fm_tools:
        if t not in skill.tools:
            skill.tools.append(t)
    skill.path = rel
    skill.content_digest = compute_skill_digest(folder)
