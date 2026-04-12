"""Workspace model — agent execution environment."""

from agentstack.schema.common import NamedModel, WorkspaceType
from agentstack.schema.provider import Provider


class Workspace(NamedModel):
    """Execution environment an agent operates in."""

    type: WorkspaceType
    provider: Provider | None = None
    filesystem: bool = False
    terminal: bool = False
    browser: bool = False
    network: bool = True
    gpu: bool = False
    timeout: str | None = None
    persist: bool = False
    path: str | None = None
    max_size: str | None = None
