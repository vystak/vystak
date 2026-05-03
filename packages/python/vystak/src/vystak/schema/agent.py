"""Agent model — the top-level composition unit."""

from typing import Self

from pydantic import model_validator

from vystak.schema.common import NamedModel
from vystak.schema.compaction import Compaction
from vystak.schema.mcp import McpServer
from vystak.schema.model import Model
from vystak.schema.platform import Platform
from vystak.schema.resource import Resource
from vystak.schema.secret import Secret
from vystak.schema.service import ServiceType
from vystak.schema.skill import Skill
from vystak.schema.workspace import Workspace


class Agent(NamedModel):
    """An AI agent — the central deployable unit.

    Agents are pure computational units addressable by `canonical_name`. They
    do not own channels; channels declare routes to agents (see schema.channel).
    """

    instructions: str | None = None
    model: Model
    skills: list[Skill] = []
    mcp_servers: list[McpServer] = []
    workspace: Workspace | None = None
    guardrails: dict | None = None
    secrets: list[Secret] = []
    platform: Platform | None = None
    port: int | None = None

    # First-class agent concerns
    sessions: ServiceType | None = None
    memory: ServiceType | None = None

    # Additional infrastructure services
    services: list[ServiceType] = []

    # Deprecated: kept for backward compatibility
    resources: list[Resource] = []

    subagents: list["Agent"] = []

    compaction: Compaction | None = None

    @property
    def canonical_name(self) -> str:
        ns = self.platform.namespace if self.platform else "default"
        return f"{self.name}.agents.{ns}"

    @model_validator(mode="after")
    def _assign_service_names(self) -> Self:
        if self.sessions and not self.sessions.name:
            self.sessions.name = "sessions"
        if self.memory and not self.memory.name:
            self.memory.name = "memory"
        return self

    @model_validator(mode="after")
    def _validate_subagents(self) -> Self:
        names = [s.name for s in self.subagents]
        if self.name in names:
            raise ValueError(
                f"Agent '{self.name}' cannot list itself in subagents."
            )
        seen: set[str] = set()
        for n in names:
            if n in seen:
                raise ValueError(
                    f"Agent '{self.name}' has duplicate subagent name '{n}'."
                )
            seen.add(n)
        return self


Agent.model_rebuild()
