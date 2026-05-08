"""TemplateManifest — schema for _vystak/manifest.json."""

from datetime import datetime

from pydantic import BaseModel, Field


class TemplateRef(BaseModel):
    name: str
    version: str


class VystakCompat(BaseModel):
    schema_version: str
    min_compat: str
    max_compat: str


class TemplateManifest(BaseModel):
    schema_version: int = 1
    template: TemplateRef
    vystak: VystakCompat
    scaffolded_at: datetime
    scaffolded_by_cli: str
    files: dict[str, str] = Field(default_factory=dict)
