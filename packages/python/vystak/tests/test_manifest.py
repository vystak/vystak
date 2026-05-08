"""TemplateManifest schema validation."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError
from vystak.schema.manifest import TemplateManifest


def _ok_payload():
    return {
        "schema_version": 1,
        "template": {"name": "langchain-python", "version": "0.1.0"},
        "vystak": {"schema_version": "0.5", "min_compat": "0.4", "max_compat": "0.5"},
        "scaffolded_at": datetime.now(UTC).isoformat(),
        "scaffolded_by_cli": "1.4.0",
        "files": {"_vystak/runtime/app_factory.py": "sha256:abc"},
    }


def test_valid_manifest_parses():
    m = TemplateManifest(**_ok_payload())
    assert m.template.name == "langchain-python"
    assert m.schema_version == 1


def test_missing_required_field_raises():
    bad = _ok_payload()
    del bad["template"]
    with pytest.raises(ValidationError):
        TemplateManifest(**bad)


def test_files_dict_required():
    bad = _ok_payload()
    bad["files"] = "not-a-dict"
    with pytest.raises(ValidationError):
        TemplateManifest(**bad)
