"""Tests for turn_core.py — emitter for the shared one-shot/streaming cores."""

from __future__ import annotations

import ast


def test_emit_turn_core_helpers_returns_str():
    from vystak_adapter_langchain.turn_core import emit_turn_core_helpers

    src = emit_turn_core_helpers()
    assert isinstance(src, str)
    assert src.strip() != ""


def test_emit_turn_core_helpers_is_syntactically_valid_python():
    from vystak_adapter_langchain.turn_core import emit_turn_core_helpers

    src = emit_turn_core_helpers()
    ast.parse(src)


def test_emit_turn_core_defines_expected_names():
    """The emitted source must define the expected top-level symbols."""
    from vystak_adapter_langchain.turn_core import emit_turn_core_helpers

    src = emit_turn_core_helpers()
    tree = ast.parse(src)
    top_level_names = {
        node.name for node in tree.body
        if isinstance(node, (ast.ClassDef, ast.AsyncFunctionDef, ast.FunctionDef))
    }
    assert "TurnResult" in top_level_names
    assert "TurnEvent" in top_level_names
    assert "_flatten_message_content" in top_level_names
    assert "_build_turn_config" in top_level_names
    assert "process_turn" in top_level_names
    assert "process_turn_streaming" in top_level_names


def test_process_turn_signature():
    """process_turn(text, metadata, *, resume_text=None, task_id=None, messages=None)."""
    from vystak_adapter_langchain.turn_core import emit_turn_core_helpers

    src = emit_turn_core_helpers()
    tree = ast.parse(src)
    fn = next(
        n for n in tree.body
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "process_turn"
    )
    arg_names = [a.arg for a in fn.args.args]
    kwonly = [a.arg for a in fn.args.kwonlyargs]
    assert arg_names == ["text", "metadata"]
    assert kwonly == ["resume_text", "task_id", "messages"]


def test_process_turn_streaming_signature():
    """process_turn_streaming(text, metadata, *, resume_text=None, task_id=None, messages=None)."""
    from vystak_adapter_langchain.turn_core import emit_turn_core_helpers

    src = emit_turn_core_helpers()
    tree = ast.parse(src)
    fn = next(
        n for n in tree.body
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "process_turn_streaming"
    )
    arg_names = [a.arg for a in fn.args.args]
    kwonly = [a.arg for a in fn.args.kwonlyargs]
    assert arg_names == ["text", "metadata"]
    assert kwonly == ["resume_text", "task_id", "messages"]


def test_process_turn_calls_handle_memory_actions():
    """The one-shot core must persist memory sentinels."""
    from vystak_adapter_langchain.turn_core import emit_turn_core_helpers

    src = emit_turn_core_helpers()
    assert "await handle_memory_actions(" in src


def test_process_turn_streaming_calls_handle_memory_actions():
    """The streaming core must persist memory sentinels too."""
    from vystak_adapter_langchain.turn_core import emit_turn_core_helpers

    src = emit_turn_core_helpers()
    # handle_memory_actions appears twice in the emitted source — once
    # in process_turn, once in process_turn_streaming.
    assert src.count("await handle_memory_actions(") == 2


def test_process_turn_signature_includes_messages_kwarg():
    """process_turn(text, metadata, *, resume_text=None, task_id=None, messages=None)."""
    from vystak_adapter_langchain.turn_core import emit_turn_core_helpers

    src = emit_turn_core_helpers()
    tree = ast.parse(src)
    fn = next(
        n for n in tree.body
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "process_turn"
    )
    arg_names = [a.arg for a in fn.args.args]
    kwonly = [a.arg for a in fn.args.kwonlyargs]
    assert arg_names == ["text", "metadata"]
    assert kwonly == ["resume_text", "task_id", "messages"]


def test_emitted_process_turn_uses_messages_when_provided():
    """When messages kwarg is non-None, process_turn uses it as agent_input."""
    from vystak_adapter_langchain.turn_core import emit_turn_core_helpers

    src = emit_turn_core_helpers()
    # The new branch: `elif messages is not None:` followed by agent_input assignment.
    assert "elif messages is not None:" in src
    assert 'agent_input = {"messages": messages}' in src
