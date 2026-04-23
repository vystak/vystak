"""Shared base classes and enums for Vystak schema models."""

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
    CHAT = "chat"


class McpTransport(StrEnum):
    STDIO = "stdio"
    SSE = "sse"
    STREAMABLE_HTTP = "streamable_http"


class RuntimeMode(StrEnum):
    SHARED = "shared"
    DEDICATED = "dedicated"
    PER_SESSION = "per-session"


class AgentProtocol(StrEnum):
    A2A_TURN = "a2a-turn"
    A2A_STREAM = "a2a-stream"
    MEDIA_BRIDGE = "media-bridge"


class VaultType(StrEnum):
    KEY_VAULT = "key-vault"
    VAULT = "vault"


class VaultMode(StrEnum):
    DEPLOY = "deploy"
    EXTERNAL = "external"
