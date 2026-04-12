"""AgentStack — declarative AI agent orchestration."""

__version__ = "0.1.0"

# Schema models
from agentstack.schema import (
    Agent, Cache, Channel, ChannelType, Database, Embedding, McpServer,
    McpTransport, Model, NamedModel, ObjectStore, Platform, Provider,
    Queue, Resource, Secret, SessionStore, Skill, SkillRequirements,
    VectorStore, Workspace, WorkspaceType,
)

# Hash engine
from agentstack.hash import AgentHashTree, hash_agent, hash_dict, hash_model

# Loader
from agentstack.schema.loader import dump_agent, load_agent

# Provider ABCs and supporting types
from agentstack.providers import (
    AgentStatus, ChannelAdapter, DeployPlan, DeployResult,
    FrameworkAdapter, GeneratedCode, PlatformProvider, ValidationError,
)

__all__ = [
    "__version__",
    "Agent", "Cache", "Channel", "ChannelType", "Database", "Embedding",
    "McpServer", "McpTransport", "Model", "NamedModel", "ObjectStore",
    "Platform", "Provider", "Queue", "Resource", "Secret", "SessionStore",
    "Skill", "SkillRequirements", "VectorStore", "Workspace", "WorkspaceType",
    "AgentHashTree", "hash_agent", "hash_dict", "hash_model",
    "dump_agent", "load_agent",
    "AgentStatus", "ChannelAdapter", "DeployPlan", "DeployResult",
    "FrameworkAdapter", "GeneratedCode", "PlatformProvider", "ValidationError",
]
