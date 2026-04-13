from agentstack.schema import (
    Agent, Cache, Channel, ChannelType, Database, Embedding, McpServer,
    McpTransport, Model, NamedModel, ObjectStore, Platform, Postgres,
    Provider, Qdrant, Queue, Redis, Resource, Secret, Service, SessionStore,
    Skill, SkillRequirements, SlackChannel, Sqlite, VectorStore, Workspace,
    WorkspaceType,
)


def test_all_schema_types_importable():
    types = [
        Agent, Cache, Channel, ChannelType, Database, Embedding, McpServer,
        McpTransport, Model, NamedModel, ObjectStore, Platform, Postgres,
        Provider, Qdrant, Queue, Redis, Resource, Secret, Service, SessionStore,
        Skill, SkillRequirements, SlackChannel, Sqlite, VectorStore, Workspace,
        WorkspaceType,
    ]
    assert len(types) == 28


def test_service_types_importable_from_top_level():
    from agentstack import Postgres, Qdrant, Redis, Service, Sqlite
    assert Service is not None
    assert Postgres is not None
    assert Sqlite is not None
    assert Redis is not None
    assert Qdrant is not None
