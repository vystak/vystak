"""Tests for Spec 1 additions to the Workspace schema."""

import pytest
from pydantic import ValidationError as PydanticValidationError
from vystak.schema.workspace import Workspace


def test_workspace_image_and_provision():
    ws = Workspace(
        name="dev",
        image="python:3.12-slim",
        provision=["apt-get update", "pip install ruff"],
    )
    assert ws.image == "python:3.12-slim"
    assert ws.provision == ["apt-get update", "pip install ruff"]
    assert ws.persistence == "volume"  # default


def test_workspace_copy_field():
    ws = Workspace(
        name="dev",
        image="python:3.12-slim",
        copy={"./config.toml": "/workspace/config.toml"},
    )
    assert ws.copy == {"./config.toml": "/workspace/config.toml"}


def test_workspace_persistence_bind_requires_path():
    with pytest.raises(PydanticValidationError, match="persistence='bind' requires path"):
        Workspace(name="dev", image="python:3.12-slim", persistence="bind")


def test_workspace_persistence_bind_with_path_valid():
    ws = Workspace(name="dev", image="python:3.12-slim", persistence="bind", path="/tmp/proj")
    assert ws.persistence == "bind"
    assert ws.path == "/tmp/proj"


def test_workspace_dockerfile_mutually_exclusive_with_image():
    with pytest.raises(PydanticValidationError, match="mutually exclusive"):
        Workspace(name="dev", dockerfile="./Dockerfile", image="python:3.12-slim")


def test_workspace_ssh_requires_authorized_keys():
    with pytest.raises(PydanticValidationError, match="ssh=True requires ssh_authorized_keys"):
        Workspace(name="dev", image="python:3.12-slim", ssh=True)


def test_workspace_ssh_with_keys_valid():
    ws = Workspace(
        name="dev",
        image="python:3.12-slim",
        ssh=True,
        ssh_authorized_keys=["ssh-ed25519 AAA alice@laptop"],
    )
    assert ws.ssh is True
    assert len(ws.ssh_authorized_keys) == 1


def test_workspace_legacy_type_maps_to_persistence():
    # Legacy: type="persistent" + no image should still load
    from vystak.schema.common import WorkspaceType

    ws = Workspace(name="dev", type=WorkspaceType.PERSISTENT)
    # When type is set and persistence not explicitly set, persistence is derived
    assert ws.persistence == "volume"  # persistent → volume


def test_workspace_legacy_type_sandbox_maps_to_ephemeral():
    from vystak.schema.common import WorkspaceType

    ws = Workspace(name="dev", type=WorkspaceType.SANDBOX)
    assert ws.persistence == "ephemeral"


def test_workspace_legacy_type_mounted_maps_to_bind_needs_path():
    from vystak.schema.common import WorkspaceType

    # type=mounted requires path (same as persistence=bind)
    with pytest.raises(PydanticValidationError, match="bind.*path"):
        Workspace(name="dev", type=WorkspaceType.MOUNTED)
