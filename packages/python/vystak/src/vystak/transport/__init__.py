"""Transport abstraction for east-west A2A traffic.

`TransportContract` is a pytest-based test helper and lives at
`vystak.transport.contract`. It is intentionally NOT re-exported here so
that importing `vystak.transport` from a production container (which has
no pytest) works.
"""

from vystak.transport.base import ServerDispatcherProtocol, Transport
from vystak.transport.client import AgentClient, ask_agent
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
    "AgentClient",
    "AgentRef",
    "ServerDispatcherProtocol",
    "Transport",
    "ask_agent",
    "canonical_agent_name",
    "parse_canonical_name",
    "slug",
]
