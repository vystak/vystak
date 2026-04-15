"""OpenAI-compatible API schema models.

Shared Pydantic types used by both agent servers and the gateway
to implement OpenAI Chat Completions, Models, and Threads APIs.
"""

from pydantic import BaseModel


# === Models Resource ===

class ModelObject(BaseModel):
    id: str
    object: str = "model"
    created: int
    owned_by: str = "agentstack"


class ModelList(BaseModel):
    object: str = "list"
    data: list[ModelObject]


# === Chat Completions ===

class ChatMessage(BaseModel):
    role: str
    content: str | None = None


class ChatCompletionRequest(BaseModel):
    model: str
    messages: list[ChatMessage]
    stream: bool = False
    # Extension fields
    session_id: str | None = None
    user_id: str | None = None
    project_id: str | None = None


class CompletionUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class Choice(BaseModel):
    index: int = 0
    message: ChatMessage
    finish_reason: str = "stop"


class ChatCompletionResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: list[Choice]
    usage: CompletionUsage | None = None


class ChunkDelta(BaseModel):
    role: str | None = None
    content: str | None = None


class ChunkChoice(BaseModel):
    index: int = 0
    delta: ChunkDelta
    finish_reason: str | None = None


class ChatCompletionChunk(BaseModel):
    id: str
    object: str = "chat.completion.chunk"
    created: int
    model: str
    choices: list[ChunkChoice]
    x_agentstack: dict | None = None


# === Threads API ===

class CreateThreadRequest(BaseModel):
    model: str | None = None
    metadata: dict = {}


class Thread(BaseModel):
    id: str
    object: str = "thread"
    created_at: int
    metadata: dict = {}


class ContentBlock(BaseModel):
    type: str = "text"
    text: str


class CreateMessageRequest(BaseModel):
    role: str
    content: str


class ThreadMessage(BaseModel):
    id: str
    object: str = "thread.message"
    thread_id: str
    role: str
    content: list[ContentBlock]
    created_at: int


class CreateRunRequest(BaseModel):
    model: str
    stream: bool = False


class Run(BaseModel):
    id: str
    object: str = "thread.run"
    thread_id: str
    model: str
    status: str
    created_at: int
    completed_at: int | None = None


# === Error Response ===

class ErrorDetail(BaseModel):
    message: str
    type: str
    param: str | None = None
    code: str


class ErrorResponse(BaseModel):
    error: ErrorDetail
