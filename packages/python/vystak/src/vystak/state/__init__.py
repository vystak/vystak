"""Local state files under .vystak/ used by apply/destroy for secrets and identities."""

import datetime
import hashlib
import json
from pathlib import Path


def _load(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def _save(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True))


def load_secrets_state(path: Path) -> dict:
    """Load .vystak/secrets-state.json — per-secret metadata."""
    return _load(path)


def save_secrets_state(path: Path, data: dict) -> None:
    _save(path, data)


def record_secret_pushed(
    path: Path,
    name: str,
    *,
    value: str | None = None,
    hash_prefix: str | None = None,
) -> None:
    """Mark a secret as pushed. Computes hash_prefix from value if supplied."""
    state = load_secrets_state(path)
    if hash_prefix is None and value is not None:
        hash_prefix = hashlib.sha256(value.encode()).hexdigest()[:12]
    state[name] = {
        "pushed_at": datetime.datetime.now(datetime.UTC)
        .isoformat()
        .replace("+00:00", "Z"),
        "hash_prefix": hash_prefix or "",
    }
    save_secrets_state(path, state)


def load_identities_state(path: Path) -> dict:
    """Load .vystak/identities-state.json — per-identity metadata."""
    return _load(path)


def record_identity_created(path: Path, *, name: str, resource_id: str) -> None:
    state = load_identities_state(path)
    state[name] = {
        "resource_id": resource_id,
        "created_at": datetime.datetime.now(datetime.UTC)
        .isoformat()
        .replace("+00:00", "Z"),
    }
    _save(path, state)


__all__ = [
    "load_identities_state",
    "load_secrets_state",
    "record_identity_created",
    "record_secret_pushed",
    "save_secrets_state",
]
