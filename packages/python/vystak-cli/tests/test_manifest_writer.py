"""Manifest writer — scaffold _vystak/, hash files, write manifest.json."""

import json

from vystak_cli.manifest import scaffold_template


def test_scaffold_copies_tree(tmp_path):
    src = tmp_path / "src_template"
    (src / "_vystak" / "runtime").mkdir(parents=True)
    (src / "_vystak" / "manifest.template.json").write_text(
        json.dumps({
            "schema_version": 1,
            "template": {"name": "test-tpl", "version": "0.1.0"},
            "vystak": {"schema_version": "0.5", "min_compat": "0.4", "max_compat": "0.5"},
        })
    )
    (src / "_vystak" / "runtime" / "app_factory.py").write_text("# stub")
    (src / "server.py").write_text("# stub server")
    (src / "tests").mkdir()
    (src / "tests" / "test_x.py").write_text("# excluded")

    target = tmp_path / "dest"
    scaffold_template(src, target, cli_version="1.4.0")

    assert (target / "server.py").exists()
    assert (target / "_vystak" / "runtime" / "app_factory.py").exists()
    assert not (target / "tests").exists()  # excluded


def test_scaffold_writes_manifest_with_file_hashes(tmp_path):
    src = tmp_path / "src_template"
    (src / "_vystak").mkdir(parents=True)
    (src / "_vystak" / "manifest.template.json").write_text(
        json.dumps({
            "schema_version": 1,
            "template": {"name": "test-tpl", "version": "0.1.0"},
            "vystak": {"schema_version": "0.5", "min_compat": "0.4", "max_compat": "0.5"},
        })
    )
    (src / "_vystak" / "runtime").mkdir()
    (src / "_vystak" / "runtime" / "x.py").write_text("# x")

    target = tmp_path / "dest"
    scaffold_template(src, target, cli_version="1.4.0")

    manifest = json.loads((target / "_vystak" / "manifest.json").read_text())
    assert manifest["template"]["name"] == "test-tpl"
    assert manifest["scaffolded_by_cli"] == "1.4.0"
    assert "_vystak/runtime/x.py" in manifest["files"]
    assert manifest["files"]["_vystak/runtime/x.py"].startswith("sha256:")


def test_scaffold_overwrites_when_force(tmp_path):
    src = tmp_path / "src_template"
    (src / "_vystak").mkdir(parents=True)
    (src / "_vystak" / "manifest.template.json").write_text(
        json.dumps({
            "schema_version": 1,
            "template": {"name": "test-tpl", "version": "0.2.0"},
            "vystak": {"schema_version": "0.5", "min_compat": "0.4", "max_compat": "0.5"},
        })
    )
    target = tmp_path / "dest"
    target.mkdir()
    (target / "_vystak").mkdir()
    (target / "_vystak" / "stale.py").write_text("# stale")

    scaffold_template(src, target, cli_version="1.4.0", force=True)
    assert not (target / "_vystak" / "stale.py").exists()
