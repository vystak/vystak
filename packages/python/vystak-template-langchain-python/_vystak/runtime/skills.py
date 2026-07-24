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
    described = [s for s in skills if (getattr(s, "description", None) or "").strip()]
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
                "\n\nResource files: " + ", ".join(resources) + " — read them with read_skill_file."
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
            return f"File '{path}' not found in skill '{skill}'. Available: {available}"
        try:
            return target.read_text()
        except UnicodeDecodeError:
            return f"File '{path}' in skill '{skill}' is not readable text."

    return [load_skill, read_skill_file]


def _strip_frontmatter(text: str) -> str:
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            return parts[2].lstrip("\n")
    return text


def _bundled_file(folder: Path, f: Path) -> bool:
    """Mirror vystak_cli's _bundle_project_dir rules: what actually ships in
    the deploy bundle. Kept as a small local copy (not imported from vystak)
    because the template runtime must not grow new deps on vystak internals.
    """
    rel_parts = f.relative_to(folder).parts
    if any(p.startswith(".") for p in rel_parts) or "__pycache__" in rel_parts:
        return False
    if f.suffix == ".pyc":
        return False
    try:
        f.read_text()
    except UnicodeDecodeError:
        return False
    return True


def _resource_files(folder: Path) -> list[str]:
    return sorted(
        f.relative_to(folder).as_posix()
        for f in folder.rglob("*")
        if f.is_file() and f.name != "SKILL.md" and _bundled_file(folder, f)
    )
