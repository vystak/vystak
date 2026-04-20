"""Workspace model — agent execution environment."""

from vystak.schema.common import NamedModel, WorkspaceType
from vystak.schema.provider import Provider
from vystak.schema.secret import Secret


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

    # v1 Secret Manager additions
    secrets: list[Secret] = []
    identity: str | None = None  # Existing UAMI resource ID; auto-created if None.
    # Cross-object validation (secrets require Azure provider) lives in
    # `vystak/schema/multi_loader.py` — Workspace.provider may be None at
    # construction time if inherited from the Agent's platform.
