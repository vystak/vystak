"""Tests for the Volume model (workspace persistence, Phase 1)."""

import pytest
from pydantic import ValidationError as PydanticValidationError
from vystak.schema.volume import Volume


def test_volume_defaults():
    vol = Volume(name="team-code")
    assert vol.mode == "persistent"
    assert vol.performance == "standard"
    assert vol.retention == "retain"
    assert vol.path is None


def test_volume_bind_requires_path():
    with pytest.raises(PydanticValidationError, match="mode='bind' requires path"):
        Volume(name="local-src", mode="bind")


def test_volume_bind_with_path_valid():
    vol = Volume(name="local-src", mode="bind", path="~/code")
    assert vol.path == "~/code"


def test_volume_non_bind_rejects_path():
    with pytest.raises(PydanticValidationError, match="path= is only valid"):
        Volume(name="team-code", mode="persistent", path="~/code")


def test_volume_invalid_mode_rejected():
    with pytest.raises(PydanticValidationError):
        Volume(name="x", mode="shared")


def test_volume_name_must_be_resource_safe():
    # Azure Files share names: lowercase alphanumerics + hyphens.
    with pytest.raises(PydanticValidationError, match="lowercase alphanumerics"):
        Volume(name="Team_Code")


def test_volume_importable_from_schema_package():
    from vystak.schema import Volume as V

    assert V is Volume


def test_volume_name_rejects_trailing_newline():
    with pytest.raises(PydanticValidationError, match="lowercase alphanumerics"):
        Volume(name="team\n")


def test_volume_name_rejects_trailing_hyphen():
    with pytest.raises(PydanticValidationError, match="lowercase alphanumerics"):
        Volume(name="team-")


def test_volume_name_rejects_too_long():
    with pytest.raises(PydanticValidationError, match="lowercase alphanumerics"):
        Volume(name="a" * 50)


def test_volume_name_single_char_accepted():
    vol = Volume(name="a")
    assert vol.name == "a"
