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


def test_update_warns_on_minor_version_drift(tmp_path, capsys, monkeypatch):
    target = _scaffold(tmp_path)
    # Pretend installed core is 0.5.5 but bundled template caps at 0.5.0.
    monkeypatch.setattr(
        "vystak_cli.commands.update._installed_vystak_version", lambda: "0.5.5"
    )
    monkeypatch.setattr(
        "vystak_cli.commands.update._max_compat_for", lambda info: "0.5.0"
    )
    update_command(target=str(target), force=True)
    captured = capsys.readouterr()
    assert (
        "compat" in captured.out.lower()
        or "warn" in captured.out.lower()
        or "note" in captured.out.lower()
    )


def test_update_strict_refuses_on_major_drift(tmp_path, monkeypatch):
    target = _scaffold(tmp_path)
    monkeypatch.setattr(
        "vystak_cli.commands.update._installed_vystak_version", lambda: "1.0.0"
    )
    monkeypatch.setattr(
        "vystak_cli.commands.update._max_compat_for", lambda info: "0.5.0"
    )
    with pytest.raises(RuntimeError, match="incompatible"):
        update_command(target=str(target), strict=True)
