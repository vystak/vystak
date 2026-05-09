"""Tests for the GenAI token-usage callback's metadata extraction."""

from __future__ import annotations

from types import SimpleNamespace

import pytest


def _make_response(usage_metadata, model_name=None, response_metadata=None):
    """Build an LLMResult-shaped object the way LangChain v1 surfaces it."""
    message = SimpleNamespace(
        usage_metadata=usage_metadata,
        response_metadata=response_metadata or {},
    )
    generation = SimpleNamespace(message=message)
    return SimpleNamespace(
        generations=[[generation]],
        llm_output={"model_name": model_name} if model_name else {},
    )


def test_extract_usage_reads_langchain_v1_metadata():
    """LangChain v1 standard shape: usage_metadata on AIMessage."""
    pytest.importorskip("opentelemetry")
    from _vystak.runtime.token_usage import _extract_usage

    response = _make_response(
        usage_metadata={
            "input_tokens": 100,
            "output_tokens": 25,
            "input_token_details": {"cache_read": 80, "cache_creation": 0},
        },
        response_metadata={"model": "claude-haiku-4-5-20251001"},
    )
    usage, model = _extract_usage(response)
    assert usage["input_tokens"] == 100
    assert usage["output_tokens"] == 25
    assert usage["input_token_details"]["cache_read"] == 80
    assert model == "claude-haiku-4-5-20251001"


def test_extract_usage_falls_back_to_llm_output_token_usage():
    """Older OpenAI-style shape: llm_output.token_usage with prompt/completion."""
    from _vystak.runtime.token_usage import _extract_usage

    response = SimpleNamespace(
        generations=[[SimpleNamespace(message=SimpleNamespace())]],
        llm_output={
            "model_name": "gpt-4o-mini",
            "token_usage": {
                "prompt_tokens": 50,
                "completion_tokens": 10,
            },
        },
    )
    usage, model = _extract_usage(response)
    assert usage["input_tokens"] == 50
    assert usage["output_tokens"] == 10
    assert model == "gpt-4o-mini"


def test_extract_usage_returns_empty_when_no_usage():
    """No usage data → empty dict, no crash."""
    from _vystak.runtime.token_usage import _extract_usage

    response = SimpleNamespace(generations=[[]], llm_output={})
    usage, model = _extract_usage(response)
    assert usage == {}
    assert model is None


def test_build_callback_returns_noop_without_otel(monkeypatch):
    """OTel unavailable → silent no-op handler with the right surface."""
    from _vystak.runtime import token_usage

    # Force the import-check shim to return None.
    monkeypatch.setattr(token_usage, "_try_import_otel", lambda: (None, None))
    cb = token_usage.build_token_usage_callback()
    # Quack-test the no-op: the surface methods should exist and be no-ops.
    cb.on_chat_model_start({}, [])
    cb.on_llm_end(SimpleNamespace())


def test_build_callback_returns_handler_when_otel_available():
    """OTel + LangChain available → real BaseCallbackHandler subclass."""
    pytest.importorskip("opentelemetry")
    pytest.importorskip("langchain_core.callbacks")
    from _vystak.runtime.token_usage import build_token_usage_callback
    from langchain_core.callbacks import BaseCallbackHandler

    cb = build_token_usage_callback()
    assert isinstance(cb, BaseCallbackHandler)
