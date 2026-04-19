"""Naming helpers — canonical names and transport-independent slugs.

Every wire address on every transport is derived from an agent's canonical
name by the transport implementation. This module owns the input side of
that derivation.
"""

from __future__ import annotations

import re

SLUG_MAX = 63
_ALLOWED = re.compile(r"[^a-z0-9-]+")
_RUNS = re.compile(r"-+")


def slug(value: str) -> str:
    """Lowercase + normalise to `[a-z0-9-]`, max 63 chars.

    Matches the existing Azure ACA and Docker Compose naming conventions
    used throughout the repo.
    """
    if not value:
        raise ValueError("slug() received empty string")
    lowered = value.lower().replace("_", "-").replace(".", "-").replace(" ", "-")
    cleaned = _ALLOWED.sub("", lowered)
    collapsed = _RUNS.sub("-", cleaned).strip("-")
    if not collapsed:
        raise ValueError(f"slug({value!r}) produced empty result after cleaning")
    return collapsed[:SLUG_MAX]


def canonical_agent_name(name: str, namespace: str | None = None) -> str:
    """Build the canonical name for an agent.

    Matches `Agent.canonical_name` (`vystak/schema/agent.py:46`). Kept as a
    free function so transport code can build names without an Agent instance.
    """
    ns = namespace or "default"
    return f"{name}.agents.{ns}"


def parse_canonical_name(canonical: str) -> tuple[str, str, str]:
    """Parse `{name}.{kind}.{namespace}` into its three parts.

    Returns `(name, kind, namespace)`. Raises `ValueError` if the format is
    wrong.
    """
    parts = canonical.split(".")
    if len(parts) != 3:
        raise ValueError(
            f"canonical name must be '{{name}}.{{kind}}.{{namespace}}', "
            f"got {canonical!r}"
        )
    name, kind, namespace = parts
    if kind not in {"agents", "channels", "transports"}:
        raise ValueError(
            f"unknown kind {kind!r} in canonical name {canonical!r}"
        )
    return name, kind, namespace
