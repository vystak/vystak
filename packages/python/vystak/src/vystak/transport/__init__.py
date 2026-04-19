"""Transport abstraction for east-west A2A traffic."""

from vystak.transport.base import Transport
from vystak.transport.handler import A2AHandler
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
    "A2AHandler",
    "A2AMessage",
    "A2AResult",
    "AgentRef",
    "Transport",
    "canonical_agent_name",
    "parse_canonical_name",
    "slug",
]
