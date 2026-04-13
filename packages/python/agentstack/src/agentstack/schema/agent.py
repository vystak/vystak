"""Agent model — the top-level composition unit."""

from typing import Self

from pydantic import model_validator

from agentstack.schema.channel import Channel
from agentstack.schema.common import NamedModel
from agentstack.schema.mcp import McpServer
from agentstack.schema.model import Model
from agentstack.schema.platform import Platform
from agentstack.schema.resource import Resource
from agentstack.schema.secret import Secret
from agentstack.schema.service import Service
from agentstack.schema.skill import Skill
from agentstack.schema.workspace import Workspace


class Agent(NamedModel):
    """An AI agent — the central deployable unit."""

    instructions: str | None = None
    model: Model
    skills: list[Skill] = []
    channels: list[Channel] = []
    mcp_servers: list[McpServer] = []
    workspace: Workspace | None = None
    guardrails: dict | None = None
    secrets: list[Secret] = []
    platform: Platform | None = None
    port: int | None = None

    # First-class agent concerns
    sessions: Service | None = None
    memory: Service | None = None

    # Additional infrastructure services
    services: list[Service] = []

    # Deprecated: kept for backward compatibility
    resources: list[Resource] = []

    @model_validator(mode="after")
    def _assign_service_names(self) -> Self:
        if self.sessions and not self.sessions.name:
            self.sessions.name = "sessions"
        if self.memory and not self.memory.name:
            self.memory.name = "memory"
        return self
