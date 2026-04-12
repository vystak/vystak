"""Model and Embedding — AI model configuration."""

from agentstack.schema.common import NamedModel
from agentstack.schema.provider import Provider


class Model(NamedModel):
    """LLM connection configuration."""

    provider: Provider
    model_name: str
    parameters: dict = {}


class Embedding(NamedModel):
    """Embedding model configuration."""

    provider: Provider
    model_name: str
    dimensions: int | None = None
