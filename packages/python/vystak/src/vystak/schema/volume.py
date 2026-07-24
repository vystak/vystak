"""Volume model — named workspace persistence (Phase 1).

See docs/superpowers/specs/2026-07-23-workspace-volume-design.md.
The volume declares intent; providers map it to a backend:
Docker named volume / Azure Files SMB (standard) / Azure Files NFS (premium).
"""

import re
from typing import Literal, Self

from pydantic import model_validator

from vystak.schema.common import NamedModel

_NAME_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")
_NAME_MAX_LEN = 49  # Azure share names cap at 63; "vystak-volume-" prefix is 14 chars.


class Volume(NamedModel):
    """Named persistence for workspaces. Referenced by Workspace.volume."""

    mode: Literal["persistent", "ephemeral", "bind"] = "persistent"
    performance: Literal["standard", "premium"] = "standard"
    retention: Literal["retain", "delete"] = "retain"
    path: str | None = None  # bind mode only

    @model_validator(mode="after")
    def _validate_name(self) -> Self:
        if not _NAME_RE.fullmatch(self.name) or len(self.name) > _NAME_MAX_LEN:
            raise ValueError(
                f"Volume name '{self.name}' must be lowercase alphanumerics "
                f"and hyphens, must not start or end with a hyphen, and "
                f"must be at most {_NAME_MAX_LEN} characters (it becomes a "
                f"Docker volume / Azure Files share name)."
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
