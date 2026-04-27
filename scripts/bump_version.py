#!/usr/bin/env python3
"""Sync TypeScript package.json versions from a git-derived version.

Python packages use ``hatch-vcs`` and read the version from git tags
directly — no script needed there. TypeScript / npm has no native
git-tag versioning, so this script rewrites ``packages/typescript/*/package.json``
to a target version (the latest ``v*.*.*`` tag, the value of ``$VERSION``,
or argv[1] if provided).

Used by ``.github/workflows/release.yml`` between the tag-checkout
and the ``pnpm publish`` step. Locally:

    just sync-ts-version           # syncs to latest git tag
    just sync-ts-version 0.2.0     # syncs to an explicit version
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _from_argv() -> str | None:
    if len(sys.argv) > 1 and sys.argv[1].strip():
        return sys.argv[1].strip()
    return None


def _from_env() -> str | None:
    return os.environ.get("VYSTAK_RELEASE_VERSION") or None


def _from_git_tag() -> str | None:
    """Latest reachable v*.*.* tag, with the leading ``v`` stripped."""
    try:
        out = subprocess.run(
            ["git", "describe", "--tags", "--abbrev=0", "--match", "v*.*.*"],
            cwd=ROOT, check=True, text=True, capture_output=True,
        )
    except subprocess.CalledProcessError:
        return None
    tag = out.stdout.strip()
    return tag.removeprefix("v") if tag else None


def resolve_version() -> str:
    for source in (_from_argv, _from_env, _from_git_tag):
        v = source()
        if v:
            return v
    print(
        "No version available — pass argv[1], set VYSTAK_RELEASE_VERSION, "
        "or create a v*.*.* git tag.",
        file=sys.stderr,
    )
    sys.exit(1)


def bump_package_json(path: Path, version: str) -> bool:
    data = json.loads(path.read_text())
    if data.get("version") == version:
        return False
    data["version"] = version
    path.write_text(json.dumps(data, indent=2) + "\n")
    return True


def main() -> int:
    version = resolve_version()
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][\w.]+)?", version):
        print(f"Refusing non-semver version: {version!r}", file=sys.stderr)
        return 1

    changed: list[Path] = []
    for pkg in (ROOT / "packages" / "typescript").glob("*/package.json"):
        if bump_package_json(pkg, version):
            changed.append(pkg)

    if not changed:
        print(f"All TypeScript packages already at v{version}.")
        return 0

    print(f"Synced TypeScript packages to v{version}:")
    for path in sorted(changed):
        print(f"  {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
