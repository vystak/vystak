"""Tests for OpenAI-compatible schema models."""

import pytest

from agentstack.schema.openai import (
    ChatCompletionChunk,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatMessage,
    Choice,
    ChunkChoice,
    ChunkDelta,
    CompletionUsage,
    ContentBlock,
    CreateMessageRequest,
    CreateRunRequest,
    CreateThreadRequest,
    ErrorDetail,
    ErrorResponse,
    ModelList,
    ModelObject,
    Run,
    Thread,
    ThreadMessage,
)


class TestModelObject:
    def test_defaults(self):
        m = ModelObject(id="agentstack/test-bot", created=1000)
        assert m.id == "agentstack/test-bot"
        assert m.object == "model"
        assert m.owned_by == "agentstack"

    def test_model_list(self):
        ml = ModelList(data=[
            ModelObject(id="agentstack/a", created=1),
            ModelObject(id="agentstack/b", created=2),
        ])
        assert ml.object == "list"
        assert len(ml.data) == 2


class TestChatCompletion:
    def test_request_defaults(self):
        req = ChatCompletionRequest(
            model="agentstack/test-bot",
            messages=[ChatMessage(role="user", content="hi")],
        )
        assert req.stream is False
        assert req.session_id is None

    def test_request_with_extensions(self):
        req = ChatCompletionRequest(
            model="agentstack/test-bot",
            messages=[ChatMessage(role="user", content="hi")],
            session_id="s1",
            user_id="u1",
            project_id="p1",
        )
        assert req.session_id == "s1"

    def test_response_structure(self):
        resp = ChatCompletionResponse(
            id="chatcmpl-123",
            created=1000,
            model="agentstack/test-bot",
            choices=[Choice(message=ChatMessage(role="assistant", content="hello"))],
            usage=CompletionUsage(prompt_tokens=5, completion_tokens=3, total_tokens=8),
        )
        assert resp.object == "chat.completion"
        assert resp.choices[0].finish_reason == "stop"

    def test_chunk_structure(self):
        chunk = ChatCompletionChunk(
            id="chatcmpl-123",
            created=1000,
            model="agentstack/test-bot",
            choices=[ChunkChoice(delta=ChunkDelta(content="hi"))],
        )
        assert chunk.object == "chat.completion.chunk"
        assert chunk.choices[0].finish_reason is None


class TestThread:
    def test_create_request_optional_model(self):
        req = CreateThreadRequest()
        assert req.model is None

    def test_create_request_with_model(self):
        req = CreateThreadRequest(model="agentstack/test-bot")
        assert req.model == "agentstack/test-bot"

    def test_thread_object(self):
        t = Thread(id="thread-1", created_at=1000)
        assert t.object == "thread"

    def test_message(self):
        msg = ThreadMessage(
            id="msg-1",
            thread_id="thread-1",
            role="user",
            content=[ContentBlock(text="hello")],
            created_at=1000,
        )
        assert msg.object == "thread.message"

    def test_run(self):
        r = Run(
            id="run-1",
            thread_id="thread-1",
            model="agentstack/test-bot",
            status="completed",
            created_at=1000,
            completed_at=1001,
        )
        assert r.object == "thread.run"


class TestError:
    def test_error_response(self):
        err = ErrorResponse(error=ErrorDetail(
            message="Agent not found",
            type="invalid_request_error",
            param="model",
            code="model_not_found",
        ))
        assert err.error.code == "model_not_found"
