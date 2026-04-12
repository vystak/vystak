"""Agent model — the top-level composition unit."""

from agentstack.schema.channel import Channel
from agentstack.schema.common import NamedModel
from agentstack.schema.mcp import McpServer
from agentstack.schema.model import Model
from agentstack.schema.platform import Platform
from agentstack.schema.resource import Resource
from agentstack.schema.secret import Secret
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
    resources: list[Resource] = []
    secrets: list[Secret] = []
    platform: Platform | None = None
    port: int | None = None
