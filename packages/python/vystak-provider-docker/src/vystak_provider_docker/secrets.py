"""Local secrets storage for provisioned resource credentials."""

import json
import secrets
from pathlib import Path


def generate_password(length: int = 32) -> str:
    """Generate a secure random password."""
    return secrets.token_urlsafe(length)


def load_secrets(secrets_path: Path) -> dict:
    """Load secrets from .vystak/secrets.json."""
    if not secrets_path.exists():
        return {"resources": {}}
    return json.loads(secrets_path.read_text())


def save_secrets(secrets_path: Path, data: dict) -> None:
    """Save secrets to .vystak/secrets.json."""
    secrets_path.parent.mkdir(parents=True, exist_ok=True)
    secrets_path.write_text(json.dumps(data, indent=2))


def get_resource_password(resource_name: str, secrets_path: Path) -> str:
    """Get or create a password for a resource."""
    data = load_secrets(secrets_path)
    resources = data.setdefault("resources", {})
    resource = resources.setdefault(resource_name, {})

    if "password" not in resource:
        resource["password"] = generate_password()
        save_secrets(secrets_path, data)

    return resource["password"]
