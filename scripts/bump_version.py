#!/usr/bin/env python3
"""Bump every package version to match the top-level VERSION file.

Single source of truth: ``./VERSION`` at the repo root. Running this
script rewrites:

- ``pyproject.toml`` for every workspace member under ``packages/python/``
  (including the umbrella ``vystak`` package).
- ``package.json`` for every workspace member under ``packages/typescript/``.
- The root ``pyproject.toml`` (workspace marker version, kept in sync).

Usage:

    # Set a new version
    echo "0.2.0" > VERSION
    uv run python scripts/bump_version.py

    # Or pass a version on the command line
    uv run python scripts/bump_version.py 0.2.0

The script is idempotent — re-running with the same VERSION is a no-op.
Exit code 0 on success, 1 on any IO / parse failure.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERSION_FILE = ROOT / "VERSION"


def read_version() -> str:
    """Read the canonical version, optionally overridden by argv[1]."""
    if len(sys.argv) > 1:
        return sys.argv[1].strip()
    if not VERSION_FILE.exists():
        print(f"VERSION file not found at {VERSION_FILE}", file=sys.stderr)
        sys.exit(1)
    return VERSION_FILE.read_text().strip()


_PYPROJECT_RE = re.compile(r'^(version\s*=\s*)"[^"]*"', re.MULTILINE)


def bump_pyproject(path: Path, version: str) -> bool:
    text = path.read_text()
    new = _PYPROJECT_RE.sub(rf'\1"{version}"', text, count=1)
    if new == text:
        return False
    path.write_text(new)
    return True


def bump_package_json(path: Path, version: str) -> bool:
    data = json.loads(path.read_text())
    if data.get("version") == version:
        return False
    data["version"] = version
    path.write_text(json.dumps(data, indent=2) + "\n")
    return True


def main() -> int:
    version = read_version()
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][\w.]+)?", version):
        print(f"Refusing non-semver version: {version!r}", file=sys.stderr)
        return 1

    if not (VERSION_FILE.exists() and VERSION_FILE.read_text().strip() == version):
        VERSION_FILE.write_text(version + "\n")

    changed: list[Path] = []

    for pyproj in (ROOT / "packages" / "python").glob("*/pyproject.toml"):
        if bump_pyproject(pyproj, version):
            changed.append(pyproj)

    if bump_pyproject(ROOT / "pyproject.toml", version):
        changed.append(ROOT / "pyproject.toml")

    for pkg in (ROOT / "packages" / "typescript").glob("*/package.json"):
        if bump_package_json(pkg, version):
            changed.append(pkg)

    if not changed:
        print(f"Already at v{version}; nothing to do.")
        return 0

    print(f"Bumped to v{version}:")
    for path in sorted(changed):
        print(f"  {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
