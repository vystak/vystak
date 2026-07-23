"""``${secret.NAME}`` interpolation over arbitrary str/dict/list/tuple values.

Not MCP-specific: any consumer with a ``name -> value`` lookup can use it.
Names follow the existing ``Secret`` naming convention (``[A-Z][A-Z0-9_]*``);
refs that don't match the pattern (e.g. lowercase names) are left as
literals rather than raising.
"""

import re
from collections.abc import Callable
from typing import TypeVar

from vystak.secrets import get as _get_secret

SECRET_RE = re.compile(r"\$\{secret\.([A-Z][A-Z0-9_]*)\}")

T = TypeVar("T")


def interpolate(value: T, lookup: Callable[[str], str] | None = None) -> T:
    """Substitute ``${secret.NAME}`` refs in ``value`` via ``lookup``.

    Recurses through dicts, lists, and tuples; other types pass through
    unchanged. ``lookup`` defaults to :func:`vystak.secrets.get` (container
    env) and must raise ``KeyError`` on a missing name — the error
    propagates so a missing secret fails loudly at startup.
    """
    if lookup is None:
        lookup = _get_secret

    if isinstance(value, str):
        return SECRET_RE.sub(lambda m: lookup(m.group(1)), value)
    if isinstance(value, dict):
        return {k: interpolate(v, lookup) for k, v in value.items()}
    if isinstance(value, list):
        return [interpolate(v, lookup) for v in value]
    if isinstance(value, tuple):
        return tuple(interpolate(v, lookup) for v in value)
    return value


__all__ = ["SECRET_RE", "interpolate"]
