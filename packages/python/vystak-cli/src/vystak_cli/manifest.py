"""Scaffold a template tree into a target dir and write manifest.json."""

import hashlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

EXCLUDED = {"tests", "_test_assets", "__pycache__"}


def scaffold_template(
    source: Path,
    target: Path,
    *,
    cli_version: str,
    force: bool = False,
) -> None:
    if target.exists():
        if not force and any(target.iterdir()):
            raise FileExistsError(f"{target} is not empty. Pass force=True or use --force.")
        if force:
            shutil.rmtree(target / "_vystak", ignore_errors=True)
    target.mkdir(parents=True, exist_ok=True)

    for entry in source.iterdir():
        if entry.name in EXCLUDED:
            continue
        dest = target / entry.name
        if entry.is_dir():
            shutil.copytree(entry, dest, dirs_exist_ok=force)
        else:
            shutil.copy2(entry, dest)

    _sanitize_pyproject(target / "pyproject.toml")

    seed = json.loads((target / "_vystak" / "manifest.template.json").read_text())
    file_hashes = _hash_tree(target / "_vystak")

    manifest = {
        "schema_version": 1,
        "template": seed["template"],
        "vystak": seed["vystak"],
        "scaffolded_at": datetime.now(UTC).isoformat(),
        "scaffolded_by_cli": cli_version,
        "files": file_hashes,
    }
    (target / "_vystak" / "manifest.json").write_text(json.dumps(manifest, indent=2))


def _hash_tree(root: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.name == "manifest.json":
            continue
        rel = path.relative_to(root.parent).as_posix()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        out[rel] = f"sha256:{digest}"
    return out


def _sanitize_pyproject(target_pyproject: Path) -> None:
    """Remove dev-only sections from a scaffolded pyproject.toml.

    The template's pyproject.toml carries [tool.uv.sources] for workspace
    development. User projects aren't in our workspace, so this section
    must not survive the scaffold copy.
    """
    if not target_pyproject.exists():
        return

    text = target_pyproject.read_text()
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    skip = False
    for line in lines:
        stripped = line.strip()
        if stripped == "[tool.uv.sources]":
            skip = True
            continue
        if skip and stripped.startswith("["):
            skip = False
        if not skip:
            out.append(line)
    target_pyproject.write_text("".join(out))
