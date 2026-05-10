"""Heartbeat utilities used by the v2 vystak-heartbeat service.

`HEARTBEAT_OK`, `DEFAULT_PROMPT`, and `is_heartbeat_ok` are the stable public
symbols. `vystak-heartbeat` imports them directly.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("vystak.channel.runtime.heartbeat")

HEARTBEAT_OK = "HEARTBEAT_OK"

DEFAULT_PROMPT = (
    "Read HEARTBEAT.md if it exists in your workspace. Follow it strictly. "
    "If nothing needs attention, reply with only HEARTBEAT_OK. "
    "Otherwise, reply with a short message describing what needs attention "
    "— do not include HEARTBEAT_OK in that case."
)


def is_heartbeat_ok(text: str, max_chars: int) -> bool:
    """Return True iff `text` should be treated as a silent heartbeat ack.

    Rules (matches OpenClaw's behaviour):

    * Whitespace-only / empty text → False (do not silently swallow real bugs).
    * Stripped text longer than `max_chars` → False (always deliver long replies).
    * Otherwise → True iff `HEARTBEAT_OK` appears anywhere in the text.
    """
    stripped = text.strip()
    if not stripped:
        return False
    if len(stripped) > max_chars:
        return False
    return HEARTBEAT_OK in stripped


