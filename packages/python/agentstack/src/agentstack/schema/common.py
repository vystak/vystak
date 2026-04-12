"""Shared base classes and enums for AgentStack schema models."""

from enum import StrEnum

from pydantic import BaseModel


class NamedModel(BaseModel):
    """Base model with a required name field. All concept models inherit from this."""

    name: str


class WorkspaceType(StrEnum):
    SANDBOX = "sandbox"
    PERSISTENT = "persistent"
    MOUNTED = "mounted"


class ChannelType(StrEnum):
    API = "api"
    SLACK = "slack"
    WEBHOOK = "webhook"
    VOICE = "voice"
    CRON = "cron"
    WIDGET = "widget"


class McpTransport(StrEnum):
    STDIO = "stdio"
    SSE = "sse"
    STREAMABLE_HTTP = "streamable_http"
