"""Service models — typed infrastructure services for agents."""

from typing import Annotated, Literal

from pydantic import BaseModel, Discriminator, Tag

from vystak.schema.provider import Provider


class Service(BaseModel):
    """Base for infrastructure services an agent depends on."""

    name: str = ""
    provider: Provider | None = None
    connection_string_env: str | None = None
    config: dict = {}
    depends_on: list[str] = []

    @property
    def is_managed(self) -> bool:
        """True if Vystak should provision this service."""
        return self.provider is not None and self.connection_string_env is None


class Postgres(Service):
    """PostgreSQL database service."""

    type: Literal["postgres"] = "postgres"
    engine: str = "postgres"


class Sqlite(Service):
    """SQLite database service."""

    type: Literal["sqlite"] = "sqlite"
    engine: str = "sqlite"


class Redis(Service):
    """Redis cache/store service."""

    type: Literal["redis"] = "redis"
    engine: str = "redis"


class Qdrant(Service):
    """Qdrant vector database service."""

    type: Literal["qdrant"] = "qdrant"
    engine: str = "qdrant"


def _service_discriminator(v):
    if isinstance(v, dict):
        return v.get("type", "postgres")
    return getattr(v, "type", "postgres")


ServiceType = Annotated[
    Annotated[Postgres, Tag("postgres")]
    | Annotated[Sqlite, Tag("sqlite")]
    | Annotated[Redis, Tag("redis")]
    | Annotated[Qdrant, Tag("qdrant")],
    Discriminator(_service_discriminator),
]
