"""Secret model — credential references with progressive complexity."""

from agentstack.schema.common import NamedModel
from agentstack.schema.provider import Provider


class Secret(NamedModel):
    """A reference to a secret value.

    Simple form: Secret(name="ENV_VAR") — resolves from environment.
    Full form: Secret(name="key", provider=vault, path="secrets/x") — resolves from store.
    """

    provider: Provider | None = None
    path: str | None = None
    key: str | None = None
