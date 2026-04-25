"""Tests for single-document agent loader (loader.py)."""
import pytest
import yaml
from vystak.schema.loader import load_agent


def test_single_doc_yaml_rejects_subagents(tmp_path):
    yaml_path = tmp_path / "vystak.yaml"
    yaml_path.write_text(yaml.safe_dump({
        "name": "lonely",
        "model": {
            "name": "m",
            "provider": {"name": "p", "type": "anthropic"},
            "model_name": "claude-sonnet-4-20250514",
        },
        "subagents": ["weather-agent"],
    }))
    with pytest.raises(ValueError, match="subagents.*multi-document"):
        load_agent(yaml_path)
