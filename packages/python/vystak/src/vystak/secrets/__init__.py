"""Runtime SDK for reading secrets from the container environment.

Secret values are materialized into the container's env at start by the
platform (ACA secretRef for vault-backed deployments, direct os.environ
for env-passthrough). This module wraps os.environ with a clearer error
when the secret is missing.

This is a thin wrapper — it carries no security guarantee. Its existence
makes audits easier (a lint rule can flag raw os.environ[name] reads on
declared secret names in workspace/skill tool code).
"""

import os


class SecretNotAvailableError(KeyError):
    """Raised when a secret is not available in the current container env."""


def get(name: str) -> str:
    """Return the value of the named secret from the container's environment.

    Raises SecretNotAvailableError with actionable guidance if the secret
    is not present — typically because it was not declared on the
    Agent/Workspace/Channel that this container is serving.
    """
    try:
        return os.environ[name]
    except KeyError:
        raise SecretNotAvailableError(
            f"Secret {name!r} is not available in this container. "
            f"Declare it on the Agent / Workspace / Channel that uses it."
        ) from None


__all__ = ["SecretNotAvailableError", "get"]
