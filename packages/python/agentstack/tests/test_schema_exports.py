from agentstack.schema import (
    Agent, Cache, Channel, ChannelType, Database, Embedding, McpServer,
    McpTransport, Model, NamedModel, ObjectStore, Platform, Provider,
    Queue, Resource, Secret, SessionStore, Skill, SkillRequirements,
    VectorStore, Workspace, WorkspaceType,
)


def test_all_schema_types_importable():
    types = [
        Agent, Cache, Channel, ChannelType, Database, Embedding, McpServer,
        McpTransport, Model, NamedModel, ObjectStore, Platform, Provider,
        Queue, Resource, Secret, SessionStore, Skill, SkillRequirements,
        VectorStore, Workspace, WorkspaceType,
    ]
    assert len(types) == 22
