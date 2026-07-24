"""Volume model — named workspace persistence (Phase 1).

See docs/superpowers/specs/2026-07-23-workspace-volume-design.md.
The volume declares intent; providers map it to a backend:
Docker named volume / Azure Files SMB (standard) / Azure Files NFS (premium).
"""

import re
from typing import Literal, Self

from pydantic import model_validator

from vystak.schema.common import NamedModel

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


class Volume(NamedModel):
    """Named persistence for workspaces. Referenced by Workspace.volume."""

    mode: Literal["persistent", "ephemeral", "bind"] = "persistent"
    performance: Literal["standard", "premium"] = "standard"
    retention: Literal["retain", "delete"] = "retain"
    path: str | None = None  # bind mode only

    @model_validator(mode="after")
    def _validate_name(self) -> Self:
        if not _NAME_RE.match(self.name):
            raise ValueError(
                f"Volume name '{self.name}' must be lowercase alphanumerics "
                f"and hyphens (it becomes a Docker volume / Azure Files "
                f"share name)."
            )
        return self

    @model_validator(mode="after")
    def _validate_path(self) -> Self:
        if self.mode == "bind" and not self.path:
            raise ValueError(
                f"Volume '{self.name}' has mode='bind' requires path= "
                f"to specify the host directory to mount."
            )
        if self.mode != "bind" and self.path:
            raise ValueError(
                f"Volume '{self.name}': path= is only valid with mode='bind'."
            )
        return self
