"""Service models — typed infrastructure services for agents."""

from pydantic import BaseModel

from agentstack.schema.provider import Provider


class Service(BaseModel):
    """Base for infrastructure services an agent depends on."""

    name: str = ""
    provider: Provider | None = None
    connection_string_env: str | None = None
    config: dict = {}

    @property
    def is_managed(self) -> bool:
        """True if AgentStack should provision this service."""
        return self.provider is not None and self.connection_string_env is None


class Postgres(Service):
    """PostgreSQL database service."""

    engine: str = "postgres"


class Sqlite(Service):
    """SQLite database service."""

    engine: str = "sqlite"


class Redis(Service):
    """Redis cache/store service."""

    engine: str = "redis"


class Qdrant(Service):
    """Qdrant vector database service."""

    engine: str = "qdrant"
