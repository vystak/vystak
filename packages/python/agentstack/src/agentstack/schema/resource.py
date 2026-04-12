"""Resource models — infrastructure backing for agents."""

from agentstack.schema.common import NamedModel
from agentstack.schema.provider import Provider


class Resource(NamedModel):
    """Base resource model. Every resource has a provider and engine."""

    provider: Provider
    engine: str
    config: dict = {}


class SessionStore(Resource):
    """Conversation state storage (redis, elasticache, dynamodb, managed)."""


class VectorStore(Resource):
    """Embeddings and RAG storage (pinecone, chroma, qdrant, pgvector)."""


class Database(Resource):
    """Structured data storage (postgres, dynamodb, mysql, sqlite)."""


class Cache(Resource):
    """Tool result caching (redis, memcached)."""


class ObjectStore(Resource):
    """File and artifact storage (s3, gcs, minio, local)."""


class Queue(Resource):
    """Async task processing (sqs, rabbitmq, redis, kafka)."""
