"""Vystak channel runtime — shared base for channel containers."""

from importlib.metadata import version as _pkg_version

from vystak_channel_runtime.agent_client import A2AAgentClient, AgentClient
from vystak_channel_runtime.launcher import build_runtime, launch
from vystak_channel_runtime.runtime import ChannelRuntime
from vystak_channel_runtime.store import (
    ChannelStore,
    MemoryChannelStore,
    PostgresChannelStore,
    SqliteChannelStore,
    make_channel_store,
)
from vystak_channel_runtime.test_endpoint import build_test_app, is_test_endpoint_enabled
from vystak_channel_runtime.types import (
    AgentCallError,
    AgentChunk,
    AgentReply,
    InboundEvent,
    Message,
    SkipEvent,
    ThreadBinding,
)


def runtime_version() -> str:
    """Return the installed version of vystak-channel-runtime."""
    try:
        return _pkg_version("vystak-channel-runtime")
    except Exception:
        return "0.1.0"


def channel_package_version(name: str) -> str:
    """Return the installed version of the named channel package."""
    try:
        return _pkg_version(name)
    except Exception:
        return "0.1.0"


__all__ = [
    "A2AAgentClient",
    "build_runtime",
    "build_test_app",
    "channel_package_version",
    "is_test_endpoint_enabled",
    "launch",
    "AgentCallError",
    "AgentChunk",
    "AgentClient",
    "AgentReply",
    "ChannelRuntime",
    "ChannelStore",
    "InboundEvent",
    "MemoryChannelStore",
    "Message",
    "PostgresChannelStore",
    "runtime_version",
    "SkipEvent",
    "SqliteChannelStore",
    "ThreadBinding",
    "make_channel_store",
]
