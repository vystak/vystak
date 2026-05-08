"""vystak init --framework — scaffolds template into target dir."""

import json

import pytest
from vystak_cli.commands.init import init_command, list_frameworks_command


def test_init_with_framework_scaffolds_template(tmp_path):
    target = tmp_path / "my-agent"
    init_command(target=str(target), framework="langchain-python", force=False)

    assert (target / "vystak.yaml").exists()
    assert (target / "server.py").exists()
    assert (target / "Dockerfile").exists()
    assert (target / "_vystak" / "manifest.json").exists()

    manifest = json.loads((target / "_vystak" / "manifest.json").read_text())
    assert manifest["template"]["name"] == "langchain-python"


def test_init_default_framework_is_langchain_python(tmp_path):
    target = tmp_path / "my-agent"
    init_command(target=str(target), framework=None, force=False)
    manifest = json.loads((target / "_vystak" / "manifest.json").read_text())
    assert manifest["template"]["name"] == "langchain-python"


def test_init_unknown_framework_errors(tmp_path):
    target = tmp_path / "my-agent"
    with pytest.raises(ValueError, match="Unknown framework"):
        init_command(target=str(target), framework="nonexistent", force=False)


def test_init_existing_dir_without_force_errors(tmp_path):
    target = tmp_path / "my-agent"
    target.mkdir()
    (target / "existing.txt").write_text("don't clobber me")
    with pytest.raises(FileExistsError):
        init_command(target=str(target), framework="langchain-python", force=False)


def test_init_list_frameworks(capsys):
    list_frameworks_command()
    captured = capsys.readouterr()
    assert "langchain-python" in captured.out
