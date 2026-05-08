"""vystak update — refresh _vystak/ to bundled CLI's template version."""

import json
import time

import pytest
from vystak_cli.commands.init import init_command
from vystak_cli.commands.update import update_command


def _scaffold(tmp_path):
    target = tmp_path / "my-agent"
    init_command(target=str(target), framework="langchain-python", force=False)
    return target


def test_update_no_change_is_noop(tmp_path, capsys):
    target = _scaffold(tmp_path)
    rc = update_command(target=str(target))
    captured = capsys.readouterr()
    assert "current" in captured.out.lower() or rc == 0


def test_update_check_returns_zero_when_current(tmp_path):
    target = _scaffold(tmp_path)
    rc = update_command(target=str(target), check=True)
    assert rc == 0


def test_update_errors_on_framework_mismatch(tmp_path):
    target = _scaffold(tmp_path)
    yaml_path = target / "vystak.yaml"
    yaml_path.write_text(
        yaml_path.read_text().replace(
            "framework: langchain-python", "framework: mastra-typescript"
        )
    )
    with pytest.raises(ValueError, match="framework"):
        update_command(target=str(target))


def test_update_force_re_stamps_manifest(tmp_path):
    target = _scaffold(tmp_path)
    manifest_path = target / "_vystak" / "manifest.json"
    before = json.loads(manifest_path.read_text())["scaffolded_at"]
    time.sleep(1)
    update_command(target=str(target), force=True)
    after = json.loads(manifest_path.read_text())["scaffolded_at"]
    assert before != after
