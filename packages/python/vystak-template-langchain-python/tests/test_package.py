"""Sanity check: package imports and the manifest seed is parseable JSON."""

import json
from pathlib import Path


def test_package_imports():
    import _vystak
    import _vystak.runtime  # noqa: F401


def test_manifest_template_is_valid_json():
    pkg_root = Path(__file__).parent.parent
    manifest_seed = pkg_root / "_vystak" / "manifest.template.json"
    data = json.loads(manifest_seed.read_text())
    assert data["template"]["name"] == "langchain-python"
    assert data["schema_version"] == 1
    assert "min_compat" in data["vystak"]
    assert "max_compat" in data["vystak"]
