"""Transport abstraction for east-west A2A traffic."""

from vystak.transport.naming import (
    canonical_agent_name,
    parse_canonical_name,
    slug,
)
from vystak.transport.types import (
    A2AEvent,
    A2AMessage,
    A2AResult,
    AgentRef,
)

__all__ = [
    "A2AEvent",
    "A2AMessage",
    "A2AResult",
    "AgentRef",
    "canonical_agent_name",
    "parse_canonical_name",
    "slug",
]
