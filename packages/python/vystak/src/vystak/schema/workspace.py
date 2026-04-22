"""Workspace model — agent execution environment."""

from typing import Self

from pydantic import model_validator

from vystak.schema.common import NamedModel, WorkspaceType
from vystak.schema.provider import Provider
from vystak.schema.secret import Secret


class Workspace(NamedModel):
    """Execution environment an agent operates in.

    When set on an Agent and a Vault is declared, deploys as a separate
    container with its own lifecycle. See Spec 1:
    docs/superpowers/specs/2026-04-22-workspace-compute-design.md
    """

    # Image + provisioning
    image: str | None = None
    provision: list[str] = []
    copy: dict[str, str] = {}
    dockerfile: str | None = None
    tool_deps_manager: str | None = None

    # Filesystem / persistence
    persistence: str = "volume"  # "volume" | "bind" | "ephemeral"
    path: str | None = None

    # Network / resources
    network: bool = True
    gpu: bool = False
    timeout: str | None = None

    # Provider (legacy — inherited from Agent.platform.provider in v1)
    provider: Provider | None = None

    # Secrets (from v1 secret-manager)
    secrets: list[Secret] = []
    identity: str | None = None

    # Human SSH (opt-in)
    ssh: bool = False
    ssh_authorized_keys: list[str] = []
    ssh_authorized_keys_file: str | None = None
    ssh_host_port: int | None = None

    # Legacy / deprecated
    type: WorkspaceType | None = None
    # Legacy no-ops (accepted for schema compatibility, now have no effect):
    filesystem: bool = False
    terminal: bool = False
    browser: bool = False
    persist: bool = False
    max_size: str | None = None

    @model_validator(mode="after")
    def _apply_legacy_type(self) -> Self:
        """If persistence wasn't explicitly set and type= is set, map it."""
        # Pydantic v2 field-default detection: compare to default
        # If user didn't pass persistence, self.persistence == "volume" (default).
        # We want to distinguish "default value" from "explicitly set to volume".
        # Use model_fields_set which Pydantic v2 exposes.
        if "persistence" not in self.model_fields_set and self.type is not None:
            mapping = {
                WorkspaceType.PERSISTENT: "volume",
                WorkspaceType.SANDBOX: "ephemeral",
                WorkspaceType.MOUNTED: "bind",
            }
            self.persistence = mapping.get(self.type, "volume")
        return self

    @model_validator(mode="after")
    def _validate_bind_path(self) -> Self:
        if self.persistence == "bind" and not self.path:
            raise ValueError(
                f"Workspace '{self.name}' has persistence='bind' requires path= "
                f"to specify the host directory to mount."
            )
        return self

    @model_validator(mode="after")
    def _validate_dockerfile_exclusivity(self) -> Self:
        if self.dockerfile is not None:
            conflicts = []
            if self.image:
                conflicts.append("image")
            if self.provision:
                conflicts.append("provision")
            if self.copy:
                conflicts.append("copy")
            if conflicts:
                raise ValueError(
                    f"Workspace '{self.name}': dockerfile= is mutually exclusive "
                    f"with {', '.join(conflicts)}."
                )
        return self

    @model_validator(mode="after")
    def _validate_ssh_config(self) -> Self:
        if self.ssh and not (self.ssh_authorized_keys or self.ssh_authorized_keys_file):
            raise ValueError(
                f"Workspace '{self.name}' has ssh=True requires ssh_authorized_keys "
                f"or ssh_authorized_keys_file to grant human access."
            )
        return self
