"""Skill model — reusable capability bundles."""

from pydantic import BaseModel

from vystak.schema.common import NamedModel


class SkillRequirements(BaseModel):
    """What a skill needs from the agent environment."""

    session_store: bool = False
    workspace: dict | None = None
    mcp_servers: list[str] | None = None


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
