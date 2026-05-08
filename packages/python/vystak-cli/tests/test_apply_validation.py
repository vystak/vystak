"""vystak apply — validates _vystak/ exists and framework matches manifest."""

import json

import pytest
from vystak_cli.commands.apply import _validate_template_for_apply


def test_apply_errors_when_vystak_dir_missing(tmp_path):
    (tmp_path / "vystak.yaml").write_text(
        "name: t\nframework: langchain-python\n"
        "model:\n  name: m\n  provider:\n    name: anthropic\n"
        "    type: anthropic\n  model_name: claude-sonnet-4-6\n"
    )
    with pytest.raises(FileNotFoundError, match="_vystak"):
        _validate_template_for_apply(tmp_path)


def test_apply_errors_when_framework_mismatch(tmp_path):
    (tmp_path / "vystak.yaml").write_text(
        "name: t\nframework: mastra-typescript\n"
        "model:\n  name: m\n  provider:\n    name: anthropic\n"
        "    type: anthropic\n  model_name: claude-sonnet-4-6\n"
    )
    (tmp_path / "_vystak").mkdir()
    (tmp_path / "_vystak" / "manifest.json").write_text(
        json.dumps({
            "schema_version": 1,
            "template": {"name": "langchain-python", "version": "0.1.0"},
            "vystak": {"schema_version": "0.5", "min_compat": "0.4", "max_compat": "0.5"},
            "scaffolded_at": "2026-05-02T15:30:00Z",
            "scaffolded_by_cli": "1.4.0",
            "files": {},
        })
    )
    with pytest.raises(ValueError, match="framework"):
        _validate_template_for_apply(tmp_path)


def test_apply_passes_when_framework_matches(tmp_path):
    (tmp_path / "vystak.yaml").write_text(
        "name: t\nframework: langchain-python\n"
        "model:\n  name: m\n  provider:\n    name: anthropic\n"
        "    type: anthropic\n  model_name: claude-sonnet-4-6\n"
    )
    (tmp_path / "_vystak").mkdir()
    (tmp_path / "_vystak" / "manifest.json").write_text(
        json.dumps({
            "schema_version": 1,
            "template": {"name": "langchain-python", "version": "0.1.0"},
            "vystak": {"schema_version": "0.5", "min_compat": "0.4", "max_compat": "0.5"},
            "scaffolded_at": "2026-05-02T15:30:00Z",
            "scaffolded_by_cli": "1.4.0",
            "files": {},
        })
    )
    _validate_template_for_apply(tmp_path)  # no exception
