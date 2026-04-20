from vystak.schema import (
    Agent,
    AgentProtocol,
    Cache,
    Channel,
    ChannelType,
    Database,
    Embedding,
    McpServer,
    McpTransport,
    Model,
    NamedModel,
    ObjectStore,
    Platform,
    Postgres,
    Provider,
    Qdrant,
    Queue,
    Redis,
    Resource,
    RouteRule,
    RuntimeMode,
    Secret,
    Service,
    SessionStore,
    Skill,
    SkillRequirements,
    Sqlite,
    VectorStore,
    Workspace,
    WorkspaceType,
)


def test_all_schema_types_importable():
    types = [
        Agent,
        AgentProtocol,
        Cache,
        Channel,
        ChannelType,
        Database,
        Embedding,
        McpServer,
        McpTransport,
        Model,
        NamedModel,
        ObjectStore,
        Platform,
        Postgres,
        Provider,
        Qdrant,
        Queue,
        Redis,
        Resource,
        RouteRule,
        RuntimeMode,
        Secret,
        Service,
        SessionStore,
        Skill,
        SkillRequirements,
        Sqlite,
        VectorStore,
        Workspace,
        WorkspaceType,
    ]
    assert len(types) == 30


def test_service_types_importable_from_top_level():
    from vystak import Postgres, Qdrant, Redis, Service, Sqlite

    assert Service is not None
    assert Postgres is not None
    assert Sqlite is not None
    assert Redis is not None
    assert Qdrant is not None
