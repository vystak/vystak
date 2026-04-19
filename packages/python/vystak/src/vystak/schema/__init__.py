"""Vystak schema models — all seven concepts plus supporting types."""

from vystak.schema.agent import Agent
from vystak.schema.channel import Channel, RouteRule
from vystak.schema.common import (
    AgentProtocol,
    ChannelType,
    McpTransport,
    NamedModel,
    RuntimeMode,
    WorkspaceType,
)
from vystak.schema.mcp import McpServer
from vystak.schema.model import Embedding, Model
from vystak.schema.openai import (
    ChatCompletionChunk,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatMessage,
    Choice,
    ChunkChoice,
    ChunkDelta,
    CompletionUsage,
    CreateResponseRequest,
    ErrorDetail,
    ErrorResponse,
    InputMessage,
    ModelList,
    ModelObject,
    ResponseObject,
    ResponseOutput,
    ResponseUsage,
)
from vystak.schema.platform import Platform
from vystak.schema.provider import Provider
from vystak.schema.resource import (
    Cache,
    Database,
    ObjectStore,
    Queue,
    Resource,
    SessionStore,
    VectorStore,
)
from vystak.schema.secret import Secret
from vystak.schema.service import Postgres, Qdrant, Redis, Service, Sqlite
from vystak.schema.skill import Skill, SkillRequirements
from vystak.schema.transport import (
    HttpConfig,
    NatsConfig,
    ServiceBusConfig,
    Transport,
    TransportConfig,
    TransportConnection,
    TransportType,
)
from vystak.schema.workspace import Workspace

__all__ = [
    "Agent",
    "AgentProtocol",
    "Cache",
    "Channel",
    "ChannelType",
    "Database",
    "Embedding",
    "McpServer",
    "McpTransport",
    "Model",
    "NamedModel",
    "ObjectStore",
    "Platform",
    "Postgres",
    "Provider",
    "Qdrant",
    "Queue",
    "Redis",
    "Resource",
    "RouteRule",
    "RuntimeMode",
    "Secret",
    "Service",
    "SessionStore",
    "Skill",
    "SkillRequirements",
    "Sqlite",
    "Transport",
    "TransportConfig",
    "TransportConnection",
    "TransportType",
    "HttpConfig",
    "NatsConfig",
    "ServiceBusConfig",
    "VectorStore",
    "Workspace",
    "WorkspaceType",
    # OpenAI-compatible API models
    "ChatCompletionChunk",
    "ChatCompletionRequest",
    "ChatCompletionResponse",
    "ChatMessage",
    "Choice",
    "ChunkChoice",
    "ChunkDelta",
    "CompletionUsage",
    "CreateResponseRequest",
    "ErrorDetail",
    "ErrorResponse",
    "InputMessage",
    "ModelList",
    "ModelObject",
    "ResponseObject",
    "ResponseOutput",
    "ResponseUsage",
]
