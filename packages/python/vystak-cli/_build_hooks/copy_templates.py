"""Hatchling build hook — copy bundled templates into the wheel at build time.

Reads `packages/python/vystak-template-langchain-python/` (and any other
sibling `vystak-template-*` packages) and writes them into the CLI's
`src/vystak_cli/templates/<name>/` directory before the wheel is sealed.
"""

import shutil
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CopyTemplatesHook(BuildHookInterface):
    PLUGIN_NAME = "custom"

    def initialize(self, version, build_data):  # noqa: ANN001, ARG002
        cli_root = Path(self.root)
        workspace = cli_root.parent  # packages/python/
        target = cli_root / "src" / "vystak_cli" / "templates"

        if target.exists():
            shutil.rmtree(target)
        target.mkdir(parents=True)

        for entry in workspace.iterdir():
            if not entry.is_dir() or not entry.name.startswith("vystak-template-"):
                continue
            template_name = entry.name.replace("vystak-template-", "")
            dest = target / template_name
            shutil.copytree(
                entry,
                dest,
                ignore=shutil.ignore_patterns(
                    "tests", "_test_assets", "__pycache__", "*.pyc"
                ),
            )
