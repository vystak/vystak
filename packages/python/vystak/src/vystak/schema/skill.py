"""Skill model — reusable capability bundles."""

from pydantic import BaseModel

from vystak.schema.common import NamedModel


class SkillRequirements(BaseModel):
    """What a skill needs from the agent environment."""

    session_store: bool = False
    workspace: dict | None = None
    mcp_servers: list[str] | None = None


class Skill(NamedModel):
    """A reusable bundle of tools, prompts, guardrails, and requirements."""

    tools: list[str] = []
    prompt: str | None = None
    guardrails: dict | None = None
    requires: SkillRequirements | None = None
    version: str = "0.1.0"
    dependencies: list[str] | None = None
