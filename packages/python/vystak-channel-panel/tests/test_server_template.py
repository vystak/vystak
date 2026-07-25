"""Pin the emitted container REQUIREMENTS against the package's real imports.

The channel image installs REQUIREMENTS, not pyproject.toml — a dependency
added only to pyproject deploys as a crash-looping container (bcrypt did
exactly this: ModuleNotFoundError at import, found only on live deploy).
"""

from __future__ import annotations

from vystak_channel_panel.server_template import REQUIREMENTS


def test_requirements_cover_store_runtime_imports() -> None:
    pinned = {
        line.split(">=")[0].split("[")[0]
        for line in REQUIREMENTS.strip().splitlines()
    }
    # Third-party modules imported at module level by the package's runtime
    # path (app/store/routes). Extend when adding a dependency to
    # pyproject.toml — and add it to REQUIREMENTS at the same time.
    for required in ("fastapi", "aiosqlite", "bcrypt", "httpx", "pydantic"):
        assert required in pinned, (
            f"{required} is imported by vystak_channel_panel but missing from "
            "server_template.REQUIREMENTS — the container image would crash "
            "on import"
        )
