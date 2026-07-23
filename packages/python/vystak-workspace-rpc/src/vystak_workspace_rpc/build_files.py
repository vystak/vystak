"""Build-context files shipped with the package.

Providers copy the workspace-rpc source tree into Docker build contexts;
``setup_py_path()`` returns the packaged setup.py shim to copy alongside it
so ``pip install .`` works inside the workspace image.
"""

from pathlib import Path


def setup_py_path() -> Path:
    return Path(__file__).parent / "_build" / "setup.py"
