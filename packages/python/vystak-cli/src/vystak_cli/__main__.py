"""Module entry point: `python -m vystak_cli`.

When invoked via `-m`, Python prepends the caller's cwd (absolute path) to
sys.path. If the caller sits in a directory that contains `vystak.py` (the
user's agent definition), that file shadows the `vystak` library package.
Strip the shadowing entry before any vystak imports happen.
"""

import os
import sys

_cwd_abs = os.path.abspath(os.getcwd())
_shadow = {"", ".", _cwd_abs}
sys.path[:] = [p for p in sys.path if p not in _shadow]

from vystak_cli.cli import cli  # noqa: E402 — must follow sys.path cleanup

if __name__ == "__main__":
    cli()
