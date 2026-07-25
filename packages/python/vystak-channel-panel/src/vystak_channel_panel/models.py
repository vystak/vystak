"""Panel domain models."""

from __future__ import annotations

from pydantic import BaseModel


class PanelUser(BaseModel):
    id: str
    email: str
    name: str = ""
    image: str = ""
    role: str  # "admin" | "member"
    status: str = "active"  # "active" | "deactivated"
    created_at: str


class Project(BaseModel):
    id: str
    name: str
    owner_id: str
    is_default: bool = False
    created_at: str


class Conversation(BaseModel):
    id: str
    project_id: str
    creator_id: str
    agent_name: str
    title: str = ""
    last_response_id: str | None = None
    created_at: str
    updated_at: str


class PanelMessage(BaseModel):
    id: str
    conversation_id: str
    role: str  # "user" | "assistant"
    content: str
    response_id: str | None = None
    created_at: str
    parts: list[dict] | None = None
