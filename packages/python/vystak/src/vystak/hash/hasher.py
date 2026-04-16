"""Leaf-level hashing for Pydantic models and dicts."""

import hashlib
import json

from pydantic import BaseModel


def hash_model(model: BaseModel) -> str:
    """SHA-256 of canonical JSON representation of a Pydantic model."""
    canonical = json.dumps(model.model_dump(mode="python"), sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def hash_dict(data: dict) -> str:
    """SHA-256 of canonical JSON representation of a dict."""
    canonical = json.dumps(data, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()
