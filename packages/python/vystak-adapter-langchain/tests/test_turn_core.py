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


def test_process_turn_streaming_wraps_bare_string_tool_outputs():
    """Bare-string tool outputs (save_memory sentinels) must be wrapped for handle_memory_actions.

    Verifies the SimpleNamespace wrapping pattern is emitted.
    """
    from vystak_adapter_langchain.turn_core import emit_turn_core_helpers

    src = emit_turn_core_helpers()
    # The wrap pattern: SimpleNamespace(content=tm) for str outputs.
    assert "SimpleNamespace(content=tm)" in src


class TestTurnCoreToolCallLiteral:
    """TurnEvent type discriminator must include tool_call_start / tool_call_end values."""

    def test_literal_includes_tool_call_start_and_end(self):
        from vystak_adapter_langchain.turn_core import emit_turn_core_helpers

        src = emit_turn_core_helpers()
        assert '"tool_call_start"' in src
        assert '"tool_call_end"' in src

    def test_literal_does_not_keep_unused_tool_call_value(self):
        """The pre-refactor 'tool_call' value was never emitted; replacing it
        with tool_call_start/tool_call_end keeps the discriminator narrow."""
        import re

        from vystak_adapter_langchain.turn_core import emit_turn_core_helpers

        src = emit_turn_core_helpers()
        m = re.search(r"type:\s*Literal\[(.*?)\]", src, re.DOTALL)
        assert m, "TurnEvent.type Literal annotation not found"
        literal_body = m.group(1)
        values = [v.strip().strip('"').strip("'") for v in literal_body.split(",")]
        assert "tool_call" not in values
        assert "tool_call_start" in values
        assert "tool_call_end" in values


class TestTurnCoreToolCallEmissions:
    """process_turn_streaming yields a TurnEvent on each on_tool_start/on_tool_end."""

    def test_streaming_handles_on_tool_start(self):
        from vystak_adapter_langchain.turn_core import emit_turn_core_helpers

        src = emit_turn_core_helpers()
        assert 'ev_kind == "on_tool_start"' in src
        assert 'type="tool_call_start"' in src

    def test_streaming_handles_on_tool_end_with_duration(self):
        from vystak_adapter_langchain.turn_core import emit_turn_core_helpers

        src = emit_turn_core_helpers()
        assert 'type="tool_call_end"' in src
        assert "duration_ms" in src

    def test_streaming_uses_run_id_for_duration(self):
        """Duration must be computed from the langgraph run_id keyed start
        time, NOT recomputed at end-time. Verifies the per-tool start-map."""
        from vystak_adapter_langchain.turn_core import emit_turn_core_helpers

        src = emit_turn_core_helpers()
        assert "run_id" in src
        # A dict keyed by run_id holding start times, populated on
        # on_tool_start and read on on_tool_end.
        assert "_tool_starts" in src or "tool_starts" in src

    def test_streaming_does_not_break_existing_on_tool_end_memory_path(self):
        """The existing on_tool_end branch already collects tool messages for
        handle_memory_actions. The new emission must coexist with it."""
        from vystak_adapter_langchain.turn_core import emit_turn_core_helpers

        src = emit_turn_core_helpers()
        # Memory wrapping pattern (from prior task) must still be present.
        assert "SimpleNamespace(content=tm)" in src
        # handle_memory_actions still appears twice (once for each core).
        assert src.count("await handle_memory_actions(") == 2
