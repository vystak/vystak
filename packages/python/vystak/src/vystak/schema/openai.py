"""OpenAI-compatible API schema models.

Shared Pydantic types used by both agent servers and the gateway
to implement OpenAI Chat Completions, Models, and Responses APIs.
"""

from pydantic import BaseModel


# === Models Resource ===

class ModelObject(BaseModel):
    id: str
    object: str = "model"
    created: int
    owned_by: str = "vystak"


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
    x_vystak: dict | None = None


# === Responses API ===

class InputMessage(BaseModel):
    role: str
    content: str


class CreateResponseRequest(BaseModel):
    model: str
    input: str | list[InputMessage]
    previous_response_id: str | None = None
    store: bool = True
    stream: bool = False
    background: bool = False
    user_id: str | None = None
    project_id: str | None = None


class ResponseOutput(BaseModel):
    type: str = "message"
    role: str = "assistant"
    content: str


class ResponseUsage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


class ResponseObject(BaseModel):
    id: str
    object: str = "response"
    created_at: int
    model: str
    output: list[ResponseOutput]
    status: str = "completed"
    previous_response_id: str | None = None
    usage: ResponseUsage | None = None
    store: bool = True


# === Error Response ===

class ErrorDetail(BaseModel):
    message: str
    type: str
    param: str | None = None
    code: str


class ErrorResponse(BaseModel):
    error: ErrorDetail
