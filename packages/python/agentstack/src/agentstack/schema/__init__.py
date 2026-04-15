"""AgentStack schema models — all seven concepts plus supporting types."""

from agentstack.schema.agent import Agent
from agentstack.schema.channel import Channel, SlackChannel
from agentstack.schema.common import ChannelType, McpTransport, NamedModel, WorkspaceType
from agentstack.schema.gateway import ChannelProvider, Gateway
from agentstack.schema.mcp import McpServer
from agentstack.schema.model import Embedding, Model
from agentstack.schema.platform import Platform
from agentstack.schema.provider import Provider
from agentstack.schema.resource import (
    Cache,
    Database,
    ObjectStore,
    Queue,
    Resource,
    SessionStore,
    VectorStore,
)
from agentstack.schema.secret import Secret
from agentstack.schema.service import Postgres, Qdrant, Redis, Service, Sqlite
from agentstack.schema.skill import Skill, SkillRequirements
from agentstack.schema.workspace import Workspace
from agentstack.schema.openai import (
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

__all__ = [
    "Agent", "Cache", "Channel", "ChannelProvider", "ChannelType", "Database",
    "Embedding", "Gateway", "McpServer", "McpTransport", "Model", "NamedModel",
    "ObjectStore", "Platform", "Postgres", "Provider", "Qdrant", "Queue",
    "Redis", "Resource", "Secret", "Service", "SessionStore", "Skill",
    "SkillRequirements", "SlackChannel", "Sqlite", "VectorStore",
    "Workspace", "WorkspaceType",
    # OpenAI-compatible API models
    "ChatCompletionChunk", "ChatCompletionRequest", "ChatCompletionResponse",
    "ChatMessage", "Choice", "ChunkChoice", "ChunkDelta", "CompletionUsage",
    "CreateResponseRequest", "ErrorDetail", "ErrorResponse", "InputMessage",
    "ModelList", "ModelObject", "ResponseObject", "ResponseOutput", "ResponseUsage",
]
