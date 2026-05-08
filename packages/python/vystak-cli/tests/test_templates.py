"""Template registry discovery — bundled and dev-fallback paths."""

import pytest
from vystak_cli.templates import TemplateInfo, list_templates, resolve_template


def test_list_templates_returns_langchain_python_in_dev_workspace():
    infos = list_templates()
    names = [i.name for i in infos]
    assert "langchain-python" in names


def test_resolve_template_returns_path():
    info = resolve_template("langchain-python")
    assert isinstance(info, TemplateInfo)
    assert info.path.exists()
    assert (info.path / "_vystak" / "manifest.template.json").exists()


def test_resolve_unknown_raises():
    with pytest.raises(ValueError, match="Unknown framework"):
        resolve_template("nonexistent-framework")
