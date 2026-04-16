"""Tests for OpenAI-compatible schema models."""

import pytest

from vystak.schema.openai import (
    ChatCompletionChunk,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatMessage,
    Choice,
    ChunkChoice,
    ChunkDelta,
    CompletionUsage,
    CreateResponseRequest,
    ErrorDetail,
    ErrorResponse,
    InputMessage,
    ModelList,
    ModelObject,
    ResponseObject,
    ResponseOutput,
    ResponseUsage,
)


class TestModelObject:
    def test_defaults(self):
        m = ModelObject(id="vystak/test-bot", created=1000)
        assert m.id == "vystak/test-bot"
        assert m.object == "model"
        assert m.owned_by == "vystak"

    def test_model_list(self):
        ml = ModelList(data=[
            ModelObject(id="vystak/a", created=1),
            ModelObject(id="vystak/b", created=2),
        ])
        assert ml.object == "list"
        assert len(ml.data) == 2


class TestChatCompletion:
    def test_request_defaults(self):
        req = ChatCompletionRequest(
            model="vystak/test-bot",
            messages=[ChatMessage(role="user", content="hi")],
        )
        assert req.stream is False

    def test_request_with_extensions(self):
        req = ChatCompletionRequest(
            model="vystak/test-bot",
            messages=[ChatMessage(role="user", content="hi")],
            user_id="u1",
            project_id="p1",
        )
        assert req.user_id == "u1"

    def test_response_structure(self):
        resp = ChatCompletionResponse(
            id="chatcmpl-123",
            created=1000,
            model="vystak/test-bot",
            choices=[Choice(message=ChatMessage(role="assistant", content="hello"))],
            usage=CompletionUsage(prompt_tokens=5, completion_tokens=3, total_tokens=8),
        )
        assert resp.object == "chat.completion"
        assert resp.choices[0].finish_reason == "stop"

    def test_chunk_structure(self):
        chunk = ChatCompletionChunk(
            id="chatcmpl-123",
            created=1000,
            model="vystak/test-bot",
            choices=[ChunkChoice(delta=ChunkDelta(content="hi"))],
        )
        assert chunk.object == "chat.completion.chunk"
        assert chunk.choices[0].finish_reason is None


class TestResponse:
    def test_create_request_string_input(self):
        req = CreateResponseRequest(
            model="vystak/test-bot",
            input="hello",
        )
        assert req.store is True
        assert req.stream is False
        assert req.background is False
        assert req.previous_response_id is None

    def test_create_request_array_input(self):
        req = CreateResponseRequest(
            model="vystak/test-bot",
            input=[
                InputMessage(role="user", content="hi"),
                InputMessage(role="assistant", content="hello"),
                InputMessage(role="user", content="how are you"),
            ],
        )
        assert len(req.input) == 3

    def test_create_request_with_chaining(self):
        req = CreateResponseRequest(
            model="vystak/test-bot",
            input="follow up",
            previous_response_id="resp-abc123",
            store=True,
        )
        assert req.previous_response_id == "resp-abc123"

    def test_create_request_stateless(self):
        req = CreateResponseRequest(
            model="vystak/test-bot",
            input="one-shot",
            store=False,
        )
        assert req.store is False

    def test_response_object(self):
        resp = ResponseObject(
            id="resp-123",
            created_at=1000,
            model="vystak/test-bot",
            output=[ResponseOutput(content="hello")],
        )
        assert resp.object == "response"
        assert resp.status == "completed"
        assert resp.store is True

    def test_response_in_progress(self):
        resp = ResponseObject(
            id="resp-123",
            created_at=1000,
            model="vystak/test-bot",
            output=[],
            status="in_progress",
        )
        assert resp.status == "in_progress"

    def test_response_usage(self):
        usage = ResponseUsage(input_tokens=10, output_tokens=5, total_tokens=15)
        assert usage.total_tokens == 15

    def test_input_message(self):
        msg = InputMessage(role="user", content="hello")
        assert msg.role == "user"


class TestError:
    def test_error_response(self):
        err = ErrorResponse(error=ErrorDetail(
            message="Agent not found",
            type="invalid_request_error",
            param="model",
            code="model_not_found",
        ))
        assert err.error.code == "model_not_found"
