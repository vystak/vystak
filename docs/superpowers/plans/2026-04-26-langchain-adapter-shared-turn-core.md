# LangChain Adapter — Shared Turn Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Collapse seven near-identical "run-agent + post-process" code blocks emitted by the LangChain adapter into a single shared one-shot core (`process_turn`) and a single shared streaming core (`process_turn_streaming`) inside every generated `server.py`. Each protocol layer (A2A, `/v1/chat/completions`, `/v1/responses`) becomes a thin wire-shape translator around the cores.

**Architecture:** New helpers are emitted once into `server.py` from `templates.py`. Each protocol module (`a2a.py`, `templates.py` chat-completions, `responses.py`) is migrated one path at a time to call the cores. Existing tests are string-presence assertions on `SERVER_PY` — the same pattern is used to verify migration.

**Tech Stack:** Python 3.11+, langgraph, fastapi, pytest. Generated agent runs in Docker via `vystak-provider-docker`.

**Spec:** [`docs/superpowers/specs/2026-04-26-langchain-adapter-shared-turn-core-design.md`](../specs/2026-04-26-langchain-adapter-shared-turn-core-design.md)

---

## Source map

Seven duplicated paths today, in three generator modules:

| # | Module | Generator function | Path emitted into `server.py` | Mode |
|---|---|---|---|---|
| 1 | `templates.py` | (inside `_emit_chat_completions`, ~L742) | `chat_completions` | one-shot |
| 2 | `templates.py` | (inside `_emit_chat_completions`, ~L782+) | `_stream_chat_completions` | streaming |
| 3 | `responses.py` | `_emit_create_response_sync` (~L179) | `create_response` (sync mode) | one-shot |
| 4 | `responses.py` | `_emit_run_background` ainvoke branch (~L238) | `_run_background` (sync) | one-shot |
| 5 | `responses.py` | `_emit_run_background` astream branch (~L395) | `_run_background` (stream) | streaming |
| 6 | `a2a.py` | (inside `emit_a2a`, ~L121) | `_a2a_one_shot` | one-shot |
| 7 | `a2a.py` | (inside `emit_a2a`, ~L207) | `_a2a_streaming` | streaming |

Each block today does some subset of: `_agent.ainvoke` / `_agent.astream_events` → flatten content → `await handle_memory_actions(...)` → update `_task_manager` → return/yield.

After the refactor, only `process_turn` (one-shot) and `process_turn_streaming` (streaming) call `_agent.ainvoke` / `_agent.astream_events` and `handle_memory_actions`. Everything else is shape translation.

## File map

| Path | Action | Responsibility |
|------|--------|----------------|
| `packages/python/vystak-adapter-langchain/src/vystak_adapter_langchain/turn_core.py` | **Create** | Pure emitter producing the `TurnResult` / `TurnEvent` dataclasses + `_flatten_message_content` + `process_turn` + `process_turn_streaming` as Python source strings, ready to splice into `SERVER_PY`. |
| `packages/python/vystak-adapter-langchain/src/vystak_adapter_langchain/templates.py` | Modify | (1) Splice `turn_core.emit_turn_core_helpers()` into `SERVER_PY` between the existing `handle_memory_actions` block and the protocol handlers. (2) Migrate `chat_completions` and `_stream_chat_completions` emitters to call the cores. |
| `packages/python/vystak-adapter-langchain/src/vystak_adapter_langchain/a2a.py` | Modify | Migrate `_a2a_one_shot` and `_a2a_streaming` emitters to call the cores. |
| `packages/python/vystak-adapter-langchain/src/vystak_adapter_langchain/responses.py` | Modify | Migrate `create_response`, `_run_background` (sync), and `_run_background` (stream) emitters to call the cores. |
| `packages/python/vystak-adapter-langchain/tests/test_turn_core.py` | **Create** | Unit-test that the emitter produces syntactically valid Python and that the emitted source defines the expected names with the expected signatures. |
| `packages/python/vystak-adapter-langchain/tests/test_a2a.py` | Modify | Add string-presence assertions confirming `_a2a_one_shot` / `_a2a_streaming` now `await process_turn(`/`process_turn_streaming(` and no longer contain `_agent.ainvoke` / `_agent.astream_events` in their function bodies. |
| `packages/python/vystak-adapter-langchain/tests/test_templates.py` | Modify | Same string-presence assertions for `chat_completions` and `_stream_chat_completions`. |
| `packages/python/vystak-adapter-langchain/tests/test_adapter.py` | Modify | Add a single grep-style test asserting `_agent.ainvoke`, `_agent.astream_events`, and `handle_memory_actions` each appear exactly once in `SERVER_PY` for a representative agent. This is the structural backstop for spec acceptance criterion 1 + 2. |
| `packages/python/vystak-channel-slack/tests/release/test_thread_memory_a2a.py` | **Create** (release-tier) | End-to-end memory regression — deploys docker-slack-multi-agent, sends a save trigger via A2A one-shot, asserts the row appears in the agent's sessions store. |

## Phases

| Phase | Outcome | Tasks |
|-------|---------|-------|
| 1 | Cores emitted into every `server.py`; nothing calls them yet | 1.1 – 1.5 |
| 2 | `_a2a_one_shot` migrated; A2A one-shot is the canonical reference shape for protocol layers | 2.1 |
| 3 | One-shot HTTP paths (`chat_completions`, `create_response`, `_run_background` sync) migrated | 3.1 – 3.3 |
| 4 | Streaming paths (`_stream_chat_completions`, `_a2a_streaming`, `_run_background` stream) migrated; fixes the still-broken streaming memory bug | 4.1 – 4.3 |
| 5 | Spec acceptance (grep-level guarantees, regression test, live deploy) | 5.1 – 5.3 |

Every commit keeps `just lint-python` + `just test-python` + a fresh `vystak apply` of `examples/docker-slack-multi-agent/` working end-to-end.

---

## Task 1.1: Scaffold `turn_core.py` emitter

**Files:**
- Create: `packages/python/vystak-adapter-langchain/src/vystak_adapter_langchain/turn_core.py`
- Create: `packages/python/vystak-adapter-langchain/tests/test_turn_core.py`

- [ ] **Step 1.1.1: Write the failing test for emitter shape**

Create `packages/python/vystak-adapter-langchain/tests/test_turn_core.py`:

```python
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
    """The emitted source must define the four public symbols."""
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
    assert "process_turn" in top_level_names
    assert "process_turn_streaming" in top_level_names


def test_process_turn_signature():
    """process_turn(text, metadata, *, resume_text=None, task_id=None)."""
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
    assert kwonly == ["resume_text", "task_id"]


def test_process_turn_streaming_signature():
    """process_turn_streaming(text, metadata, *, resume_text=None, task_id=None)."""
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
    assert kwonly == ["resume_text", "task_id"]


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
```

- [ ] **Step 1.1.2: Run the tests and confirm they fail**

```bash
uv run pytest packages/python/vystak-adapter-langchain/tests/test_turn_core.py -v
```

Expected: `ModuleNotFoundError: No module named 'vystak_adapter_langchain.turn_core'`. All 7 tests fail at collection.

- [ ] **Step 1.1.3: Implement `turn_core.py`**

Create `packages/python/vystak-adapter-langchain/src/vystak_adapter_langchain/turn_core.py`:

```python
"""Emit the shared one-shot and streaming cores into the agent's ``server.py``.

Every generated agent server includes ``process_turn`` and
``process_turn_streaming`` exactly once, regardless of which protocol
adapters (A2A, /v1/chat/completions, /v1/responses) are present. The
cores own ``_agent.ainvoke`` / ``_agent.astream_events``,
``handle_memory_actions``, ``_task_manager`` state transitions, and
interrupt/resume handling. Each protocol layer is a thin wire-shape
translator around them.

Spec: docs/superpowers/specs/2026-04-26-langchain-adapter-shared-turn-core-design.md
"""

from __future__ import annotations


_TURN_CORE_SRC = '''\
@dataclass
class TurnResult:
    """One-shot turn result. Returned by ``process_turn``."""

    response_text: str
    messages: list
    interrupt_text: str | None = None


@dataclass
class TurnEvent:
    """Single streamed event. Yielded by ``process_turn_streaming``."""

    type: str
    text: str = ""
    data: dict | None = None
    final: bool = False


def _flatten_message_content(content) -> str:
    """Flatten an Anthropic-style message content into a single string."""
    if isinstance(content, list):
        return "".join(
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in content
        )
    return str(content)


def _build_turn_config(metadata: dict, *, session_id: str) -> dict:
    """Build the LangGraph ``configurable`` block from A2A-style metadata."""
    return {"configurable": {
        "thread_id": session_id,
        "trace_id": metadata.get("trace_id") or str(uuid.uuid4()),
        "user_id": metadata.get("user_id"),
        "project_id": metadata.get("project_id"),
        "parent_task_id": metadata.get("parent_task_id"),
        "agent_name": AGENT_NAME,
    }}


async def process_turn(
    text: str,
    metadata: dict,
    *,
    resume_text: str | None = None,
    task_id: str | None = None,
) -> TurnResult:
    """Run one agent turn. Used by every one-shot protocol path.

    Cross-cutting concerns (memory persistence, interrupt detection)
    happen here so they cannot drift between protocols.
    """
    session_id = metadata.get("sessionId") or task_id or str(uuid.uuid4())
    user_id = metadata.get("user_id")
    project_id = metadata.get("project_id")
    config = _build_turn_config(metadata, session_id=session_id)

    if resume_text is not None:
        agent_input = Command(resume=resume_text)
    else:
        agent_input = {"messages": [("user", text)]}

    result = await _agent.ainvoke(agent_input, config=config)

    if _store is not None:
        await handle_memory_actions(
            _store, result["messages"],
            user_id=user_id, project_id=project_id,
        )

    if "__interrupt__" in result:
        iv = result["__interrupt__"]
        interrupt_text = str(iv[0].value) if iv else "Input required"
        return TurnResult(
            response_text=interrupt_text,
            messages=result["messages"],
            interrupt_text=interrupt_text,
        )

    response_text = _flatten_message_content(result["messages"][-1].content)
    return TurnResult(response_text=response_text, messages=result["messages"])


async def process_turn_streaming(
    text: str,
    metadata: dict,
    *,
    resume_text: str | None = None,
    task_id: str | None = None,
):
    """Stream agent events. Used by every streaming protocol path.

    Yields ``TurnEvent`` values. Memory persistence runs after the
    stream completes — once tool messages are collected from
    ``on_tool_end`` events.
    """
    session_id = metadata.get("sessionId") or task_id or str(uuid.uuid4())
    user_id = metadata.get("user_id")
    project_id = metadata.get("project_id")
    config = _build_turn_config(metadata, session_id=session_id)

    if resume_text is not None:
        agent_input = Command(resume=resume_text)
    else:
        agent_input = {"messages": [("user", text)]}

    accumulated: list[str] = []
    tool_msgs: list = []

    async for event in _agent.astream_events(
        agent_input, config=config, version="v2",
    ):
        if "__interrupt__" in event:
            iv = event["__interrupt__"]
            interrupt_text = str(iv[0].value) if iv else "Input required"
            yield TurnEvent(
                type="interrupt", text=interrupt_text,
                data={"state": "input_required"}, final=True,
            )
            return

        ev_kind = event.get("event")
        if ev_kind == "on_chat_model_stream":
            chunk = event["data"].get("chunk")
            token = getattr(chunk, "content", "") if chunk is not None else ""
            if token:
                accumulated.append(token)
                yield TurnEvent(type="token", text=token)
        elif ev_kind == "on_tool_end":
            tm = event["data"].get("output")
            if tm is not None:
                tool_msgs.append(tm)

    if _store is not None and tool_msgs:
        await handle_memory_actions(
            _store, tool_msgs,
            user_id=user_id, project_id=project_id,
        )

    yield TurnEvent(
        type="final", text="".join(accumulated),
        data={"state": "completed"}, final=True,
    )
'''


def emit_turn_core_helpers() -> str:
    """Return the shared turn-core source spliced into every ``server.py``.

    The returned string is plain Python source. It assumes the
    surrounding module has imported ``dataclass``, ``uuid``,
    ``Command``, and that the names ``_agent``, ``_store``,
    ``handle_memory_actions``, and ``AGENT_NAME`` are already bound at
    module level — these are all already part of the existing
    ``SERVER_PY`` shape.
    """
    return _TURN_CORE_SRC
```

- [ ] **Step 1.1.4: Run the tests and verify they pass**

```bash
uv run pytest packages/python/vystak-adapter-langchain/tests/test_turn_core.py -v
```

Expected: all 7 tests pass.

- [ ] **Step 1.1.5: Run lint**

```bash
just lint-python
```

Expected: clean.

- [ ] **Step 1.1.6: Commit**

```bash
git add packages/python/vystak-adapter-langchain/src/vystak_adapter_langchain/turn_core.py \
        packages/python/vystak-adapter-langchain/tests/test_turn_core.py
git commit -m "$(cat <<'EOF'
feat(adapter-langchain): add turn_core emitter for shared cores

Pure source-string emitter producing TurnResult/TurnEvent dataclasses,
_flatten_message_content, process_turn (one-shot core), and
process_turn_streaming (streaming core). Not yet spliced into
server.py — that lands in the next task. Unit-tested via ast parsing
to guarantee the emitted code is syntactically valid Python and
defines the expected symbols.

Refs: docs/superpowers/specs/2026-04-26-langchain-adapter-shared-turn-core-design.md
EOF
)"
```

---

## Task 1.2: Splice cores into emitted `server.py`

**Files:**
- Modify: `packages/python/vystak-adapter-langchain/src/vystak_adapter_langchain/templates.py`
- Modify: `packages/python/vystak-adapter-langchain/tests/test_adapter.py`

The cores are emitted between the existing `handle_memory_actions` block and the protocol handlers (chat_completions, A2A, etc.) so that `_agent`, `_store`, and `handle_memory_actions` are all already in scope when `process_turn` is parsed.

- [ ] **Step 1.2.1: Find the splice point in `templates.py`**

Open `packages/python/vystak-adapter-langchain/src/vystak_adapter_langchain/templates.py`. The function that builds the full `SERVER_PY` lives near `_emit_chat_completions`. Find the block that emits `handle_memory_actions` (around line 649–740).

Right after that block emits the `handle_memory_actions` function definition and before the next block (which emits `chat_completions`), splice in `emit_turn_core_helpers()`.

- [ ] **Step 1.2.2: Write the failing string-presence test**

Append to `packages/python/vystak-adapter-langchain/tests/test_adapter.py`:

```python
def test_server_py_emits_turn_core_helpers():
    """Every generated server.py must include process_turn / process_turn_streaming."""
    from vystak_adapter_langchain.adapter import LangChainAdapter
    from tests.test_adapter import _minimal_agent  # existing helper, see fixture

    adapter = LangChainAdapter()
    code = adapter.generate_code(_minimal_agent())
    server_py = code.files["server.py"]
    assert "class TurnResult:" in server_py
    assert "class TurnEvent:" in server_py
    assert "def _flatten_message_content(" in server_py
    assert "async def process_turn(" in server_py
    assert "async def process_turn_streaming(" in server_py
```

If `_minimal_agent` does not exist in `test_adapter.py`, replace its import with whatever fixture builds an `Agent` in that file (search for the existing tests). Reuse the existing pattern; do not invent a new fixture.

- [ ] **Step 1.2.3: Run the test and confirm it fails**

```bash
uv run pytest packages/python/vystak-adapter-langchain/tests/test_adapter.py::test_server_py_emits_turn_core_helpers -v
```

Expected: failure — `class TurnResult:` not found in `SERVER_PY`.

- [ ] **Step 1.2.4: Splice the cores into `templates.py`**

In `packages/python/vystak-adapter-langchain/src/vystak_adapter_langchain/templates.py`, locate the line that closes the `handle_memory_actions` emit block (after line ~756 where `await handle_memory_actions(...)` is appended in the chat_completions block — the helper itself ends earlier, around line 740). Find the precise line where `lines.extend([...])` for `handle_memory_actions` ends, and the next block starts emitting chat-completions wiring.

At the top of the file, add the import:

```python
from vystak_adapter_langchain.turn_core import emit_turn_core_helpers
```

Then after the `handle_memory_actions` emission block (search for the line that emits `'    return user_id'` or the closing brace of the handle_memory_actions function — typically around line 690), add:

```python
    # Emit the shared turn cores. Every protocol layer (A2A,
    # chat_completions, /v1/responses) calls these instead of duplicating
    # _agent.ainvoke / handle_memory_actions logic per path.
    lines.append("")
    lines.append(emit_turn_core_helpers())
    lines.append("")
```

The exact insertion point is "between the last line of the `handle_memory_actions` function emission and the first line of the chat-completions handler emission." If the file's structure has changed, locate the corresponding boundary.

- [ ] **Step 1.2.5: Verify the `dataclass` import is present in the emitted `SERVER_PY`**

`turn_core.py` uses `@dataclass` — search `templates.py` for an existing emission of `from dataclasses import dataclass`. If absent, add it to the import block emitted at the top of `SERVER_PY` (search for `_emit_imports` or a similar helper). If present, no action.

If absent, in the existing emit-imports helper, add:

```python
    lines.append("from dataclasses import dataclass")
```

- [ ] **Step 1.2.6: Verify the `Command` import is present**

`process_turn` uses `Command(resume=...)`. The existing `_a2a_one_shot` already uses `Command`, so the import should already be there. Grep to confirm:

```bash
grep -n "from langgraph" packages/python/vystak-adapter-langchain/src/vystak_adapter_langchain/templates.py
```

If `Command` is imported only inside the A2A emit block (and only emitted when `agents.has_a2a_emitter` or similar), promote it so it's always emitted.

- [ ] **Step 1.2.7: Run the test and verify it passes**

```bash
uv run pytest packages/python/vystak-adapter-langchain/tests/test_adapter.py::test_server_py_emits_turn_core_helpers -v
```

Expected: PASS.

- [ ] **Step 1.2.8: Run the full adapter test suite**

```bash
uv run pytest packages/python/vystak-adapter-langchain/ -v
```

Expected: every existing test still passes — the cores are emitted but no protocol path calls them yet. No regression.

- [ ] **Step 1.2.9: Run lint**

```bash
just lint-python
```

Expected: clean.

- [ ] **Step 1.2.10: Verify generated server is syntactically valid**

```bash
uv run python -c "
from vystak_adapter_langchain.adapter import LangChainAdapter
import ast
from vystak.schema.agent import Agent
from vystak.schema.model import Model
from vystak.schema.provider import Provider
from vystak.schema.platform import Platform
from vystak.schema.secret import Secret

p = Provider(name='anthropic', type='anthropic')
docker = Provider(name='docker', type='docker')
m = Model(name='m', model_name='claude', provider=p)
agent = Agent(name='probe', model=m, platform=Platform(name='local', type='docker', provider=docker), secrets=[Secret(name='K')])
src = LangChainAdapter().generate_code(agent).files['server.py']
ast.parse(src)
print('OK', len(src), 'bytes')
"
```

Expected: `OK <bytes>` printed; no `SyntaxError`.

- [ ] **Step 1.2.11: Commit**

```bash
git add packages/python/vystak-adapter-langchain/src/vystak_adapter_langchain/templates.py \
        packages/python/vystak-adapter-langchain/tests/test_adapter.py
git commit -m "$(cat <<'EOF'
feat(adapter-langchain): splice shared turn cores into every server.py

Calls turn_core.emit_turn_core_helpers() right after the existing
handle_memory_actions block, before the protocol handlers. Adds the
'from dataclasses import dataclass' import to SERVER_PY (cores use
@dataclass). Test asserts the four expected symbols
(TurnResult, TurnEvent, process_turn, process_turn_streaming) are
present in the emitted source. No protocol path calls them yet —
that's the next phase.

Refs: docs/superpowers/specs/2026-04-26-langchain-adapter-shared-turn-core-design.md
EOF
)"
```

---

## Task 2.1: Migrate `_a2a_one_shot` to `process_turn`

**Files:**
- Modify: `packages/python/vystak-adapter-langchain/src/vystak_adapter_langchain/a2a.py`
- Modify: `packages/python/vystak-adapter-langchain/tests/test_a2a.py`

Why this path first: it's the smallest single function (lines ~121–197 in `a2a.py`), already had a recent fix for memory handling that we know works in production (Slack channel uses it), and serves as the reference shape for migrating the others.

- [ ] **Step 2.1.1: Write the failing migration tests**

Append to `packages/python/vystak-adapter-langchain/tests/test_a2a.py`:

```python
class TestA2AOneShotUsesProcessTurn:
    """The migrated _a2a_one_shot calls process_turn instead of inlining ainvoke."""

    def _server_py(self):
        from vystak_adapter_langchain.a2a import emit_a2a
        from vystak.schema.agent import Agent
        from vystak.schema.model import Model
        from vystak.schema.provider import Provider
        from vystak.schema.platform import Platform
        from vystak.schema.secret import Secret

        p = Provider(name="anthropic", type="anthropic")
        d = Provider(name="docker", type="docker")
        agent = Agent(
            name="probe",
            model=Model(name="m", model_name="claude", provider=p),
            platform=Platform(name="local", type="docker", provider=d),
            secrets=[Secret(name="K")],
        )
        return emit_a2a(agent)

    def test_one_shot_calls_process_turn(self):
        src = self._server_py()
        # The migrated body must invoke the shared core.
        assert "await process_turn(" in src

    def test_one_shot_no_longer_inlines_ainvoke(self):
        """Inside _a2a_one_shot, _agent.ainvoke must not appear (it lives in process_turn now)."""
        src = self._server_py()
        # Find the function body and check.
        import re
        match = re.search(
            r"async def _a2a_one_shot\(.*?\)(?:\s*->\s*[^\n:]*)?:\s*\n(.*?)(?=\nasync def |\Z)",
            src, re.DOTALL,
        )
        assert match, "could not locate _a2a_one_shot function"
        body = match.group(1)
        assert "_agent.ainvoke(" not in body, (
            "expected _a2a_one_shot to delegate to process_turn, "
            "but found inlined _agent.ainvoke"
        )
        # And it must not call handle_memory_actions directly anymore.
        assert "handle_memory_actions(" not in body
```

- [ ] **Step 2.1.2: Run the new tests and confirm they fail**

```bash
uv run pytest packages/python/vystak-adapter-langchain/tests/test_a2a.py::TestA2AOneShotUsesProcessTurn -v
```

Expected: 2 failures (`process_turn` not in body, ainvoke still present).

- [ ] **Step 2.1.3: Rewrite the `_a2a_one_shot` emitter**

In `packages/python/vystak-adapter-langchain/src/vystak_adapter_langchain/a2a.py`, find the block starting at line ~120 with `lines.append("async def _a2a_one_shot(...)")`. Delete the entire body emission from line ~121 through line ~197 (everything before the `# --- Streaming callable` comment). Replace with:

```python
    # --- One-shot callable (delegates to process_turn) ---
    lines.append("async def _a2a_one_shot(message: A2AMessage, metadata: dict) -> str:")
    lines.append('    """Invoke the agent one-shot via the shared turn core.')
    lines.append("")
    lines.append("    Wire-shape translator only:")
    lines.append("      A2A request envelope  ->  process_turn(text, metadata)")
    lines.append("      TurnResult            ->  A2A response text + _task_manager state")
    lines.append('    """')
    lines.append("    task_id = message.correlation_id or str(uuid.uuid4())")
    lines.append('    text = " ".join(p.get("text", "") for p in message.parts if "text" in p)')
    lines.append("")
    lines.append("    existing = _task_manager.get_task(task_id)")
    lines.append("    if existing is None:")
    lines.append("        _task_manager.create_task(task_id, {")
    lines.append('            "role": message.role,')
    lines.append('            "parts": message.parts,')
    lines.append("        })")
    lines.append('    _task_manager.update_task(task_id, "working")')
    lines.append("")
    lines.append("    # Resume scenario — pass current message as the resume payload")
    lines.append("    # rather than as a fresh user turn.")
    lines.append("    existing = _task_manager.get_task(task_id)")
    lines.append('    is_resume = existing is not None and existing["status"]["state"] == "input_required"')
    lines.append("    resume_text = text if is_resume else None")
    lines.append("    turn_text = None if is_resume else text")
    lines.append("")
    lines.append("    try:")
    lines.append("        result = await process_turn(")
    lines.append("            turn_text or text, metadata,")
    lines.append("            resume_text=resume_text, task_id=task_id,")
    lines.append("        )")
    lines.append("    except Exception as exc:")
    lines.append('        _task_manager.update_task(task_id, "failed", str(exc))')
    lines.append("        raise")
    lines.append("")
    lines.append("    if result.interrupt_text is not None:")
    lines.append('        _task_manager.update_task(task_id, "input_required", result.interrupt_text)')
    lines.append("    else:")
    lines.append('        _task_manager.update_task(task_id, "completed", result.response_text)')
    lines.append("    return result.response_text")
    lines.append("")
    lines.append("")
```

- [ ] **Step 2.1.4: Run the new tests and verify they pass**

```bash
uv run pytest packages/python/vystak-adapter-langchain/tests/test_a2a.py::TestA2AOneShotUsesProcessTurn -v
```

Expected: PASS (both tests).

- [ ] **Step 2.1.5: Run the full a2a test module**

```bash
uv run pytest packages/python/vystak-adapter-langchain/tests/test_a2a.py -v
```

Expected: all tests pass — pre-existing assertions about `_a2a_one_shot` (it exists, it returns a string, etc.) still hold.

- [ ] **Step 2.1.6: Run the full adapter test suite + lint**

```bash
uv run pytest packages/python/vystak-adapter-langchain/ -v && just lint-python
```

Expected: clean.

- [ ] **Step 2.1.7: Live-deploy regression check**

```bash
cd examples/docker-slack-multi-agent
docker rm -f vystak-assistant-agent 2>/dev/null || true
uv run vystak apply
docker exec vystak-assistant-agent grep -A 2 "Wire-shape translator only" /app/server.py | head -5
docker exec vystak-assistant-agent grep -c "_agent.ainvoke(" /app/server.py
```

Expected: the new docstring shows up, and the ainvoke count is 1 (in `process_turn` only). For comparison, before this task it was 4.

Then send a save trigger via curl to confirm memory still persists end-to-end:

```bash
PORT=$(docker port vystak-assistant-agent 8000 | head -1 | cut -d: -f2)
curl -s -m 60 -X POST http://localhost:$PORT/a2a -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":"r1","method":"tasks/send","params":{"id":"r1","message":{"role":"user","parts":[{"text":"Save the fact: the user is Anatoly, using save_memory."}]},"metadata":{"sessionId":"r1","user_id":"slack:URELEASE"}}}' \
  | head -c 400 && echo
docker exec vystak-assistant-agent python -c "
import sqlite3
n = sqlite3.connect('/data/sessions_store.db').execute('SELECT count(*) FROM store').fetchone()[0]
print('rows:', n)
"
```

Expected: response body comes back with text indicating save succeeded; `rows: 1` (or higher).

- [ ] **Step 2.1.8: Commit**

```bash
git add packages/python/vystak-adapter-langchain/src/vystak_adapter_langchain/a2a.py \
        packages/python/vystak-adapter-langchain/tests/test_a2a.py
git commit -m "$(cat <<'EOF'
refactor(adapter-langchain): _a2a_one_shot delegates to process_turn

The first protocol layer migrated to the shared turn core. The
function shrinks from ~75 lines of inlined _agent.ainvoke + memory +
content extraction to ~25 lines of pure A2A wire-shape translation
(message parts -> text, _task_manager state, TurnResult ->
response_text).

Tests assert _a2a_one_shot's body no longer contains _agent.ainvoke
or handle_memory_actions; both live in process_turn now. Live
regression: docker-slack-multi-agent save_memory round-trip still
persists.

Refs: docs/superpowers/specs/2026-04-26-langchain-adapter-shared-turn-core-design.md
EOF
)"
```

---

## Task 3.1: Migrate `chat_completions` to `process_turn`

**Files:**
- Modify: `packages/python/vystak-adapter-langchain/src/vystak_adapter_langchain/templates.py`
- Modify: `packages/python/vystak-adapter-langchain/tests/test_templates.py`

The OpenAI-compatible `/v1/chat/completions` one-shot path. Streaming variant is migrated separately in Task 4.1.

- [ ] **Step 3.1.1: Find the current emitter**

In `templates.py`, the helper that emits `chat_completions` is around lines ~720–780. The signature it emits is `async def chat_completions(request: ChatCompletionRequest):`. The body currently does its own `_agent.ainvoke` and `handle_memory_actions` calls. The streaming branch (`if request.stream:`) calls `_stream_chat_completions` separately — leave that alone for now, just migrate the non-streaming branch.

Use the Read tool to confirm exact line ranges before editing.

- [ ] **Step 3.1.2: Write the failing test**

Append to `packages/python/vystak-adapter-langchain/tests/test_templates.py`:

```python
class TestChatCompletionsUsesProcessTurn:
    """The non-streaming /v1/chat/completions path delegates to process_turn."""

    def _server_py(self):
        from vystak_adapter_langchain.adapter import LangChainAdapter
        from vystak.schema.agent import Agent
        from vystak.schema.model import Model
        from vystak.schema.provider import Provider
        from vystak.schema.platform import Platform
        from vystak.schema.secret import Secret

        p = Provider(name="anthropic", type="anthropic")
        d = Provider(name="docker", type="docker")
        agent = Agent(
            name="probe",
            model=Model(name="m", model_name="claude", provider=p),
            platform=Platform(name="local", type="docker", provider=d),
            secrets=[Secret(name="K")],
        )
        return LangChainAdapter().generate_code(agent).files["server.py"]

    def test_chat_completions_calls_process_turn(self):
        import re
        src = self._server_py()
        match = re.search(
            r"async def chat_completions\(.*?\):\s*\n(.*?)(?=\nasync def |\nclass |\Z)",
            src, re.DOTALL,
        )
        assert match
        body = match.group(1)
        # The non-streaming branch must call process_turn.
        assert "await process_turn(" in body

    def test_chat_completions_no_longer_inlines_ainvoke(self):
        """Inside chat_completions's non-streaming branch, _agent.ainvoke is gone."""
        import re
        src = self._server_py()
        match = re.search(
            r"async def chat_completions\(.*?\):\s*\n(.*?)(?=\nasync def |\nclass |\Z)",
            src, re.DOTALL,
        )
        body = match.group(1)
        assert "_agent.ainvoke(" not in body
        assert "handle_memory_actions(" not in body
```

- [ ] **Step 3.1.3: Run + confirm fail**

```bash
uv run pytest packages/python/vystak-adapter-langchain/tests/test_templates.py::TestChatCompletionsUsesProcessTurn -v
```

Expected: 2 failures.

- [ ] **Step 3.1.4: Rewrite the `chat_completions` emitter**

Locate the block in `templates.py` that emits the body of `chat_completions`. Remove the inlined `_agent.ainvoke`, the content-flattening, and the `handle_memory_actions` call from the **non-streaming** branch. Leave the streaming branch (`if request.stream: return await _stream_chat_completions(...)`) unchanged.

Replace the non-streaming branch body with:

```python
    lines.append("    if request.stream:")
    lines.append("        return await _stream_chat_completions(messages, config, request)")
    lines.append("")
    lines.append("    # Non-streaming: delegate to the shared one-shot core")
    lines.append('    text = messages[-1]["content"] if messages else ""')
    lines.append('    metadata = {')
    lines.append('        "sessionId": request.session_id,')
    lines.append('        "user_id": request.user_id,')
    lines.append('        "project_id": request.project_id,')
    lines.append('        "trace_id": request.trace_id,')
    lines.append('    }')
    lines.append("    result = await process_turn(text, metadata)")
    lines.append("    return ChatCompletionResponse(")
    lines.append('        id=f"chatcmpl-{uuid.uuid4().hex}",')
    lines.append('        object="chat.completion",')
    lines.append("        created=int(time.time()),")
    lines.append('        model=request.model or "vystak/" + AGENT_NAME,')
    lines.append("        choices=[Choice(")
    lines.append("            index=0,")
    lines.append('            message={"role": "assistant", "content": result.response_text},')
    lines.append('            finish_reason="stop",')
    lines.append("        )],")
    lines.append("        usage=Usage(prompt_tokens=0, completion_tokens=0, total_tokens=0),")
    lines.append("    )")
```

If field names like `request.session_id` don't match the actual `ChatCompletionRequest` model in this codebase, use the existing fields by reading the model definition before editing. Pull `text` from the same place the old code did (look for the line currently doing `result["messages"][-1].content` or similar — replace it with `process_turn(...)`).

- [ ] **Step 3.1.5: Run new tests + verify pass**

```bash
uv run pytest packages/python/vystak-adapter-langchain/tests/test_templates.py::TestChatCompletionsUsesProcessTurn -v
```

Expected: PASS.

- [ ] **Step 3.1.6: Run full adapter suite + lint**

```bash
uv run pytest packages/python/vystak-adapter-langchain/ -v && just lint-python
```

Expected: all tests pass; lint clean.

- [ ] **Step 3.1.7: Verify generated server is syntactically valid**

```bash
uv run python -c "
from vystak_adapter_langchain.adapter import LangChainAdapter
import ast
from vystak.schema.agent import Agent
from vystak.schema.model import Model
from vystak.schema.provider import Provider
from vystak.schema.platform import Platform
from vystak.schema.secret import Secret

p = Provider(name='anthropic', type='anthropic')
d = Provider(name='docker', type='docker')
m = Model(name='m', model_name='claude', provider=p)
agent = Agent(name='probe', model=m, platform=Platform(name='local', type='docker', provider=d), secrets=[Secret(name='K')])
src = LangChainAdapter().generate_code(agent).files['server.py']
ast.parse(src)
print('OK', len(src), 'bytes')
"
```

- [ ] **Step 3.1.8: Commit**

```bash
git add packages/python/vystak-adapter-langchain/src/vystak_adapter_langchain/templates.py \
        packages/python/vystak-adapter-langchain/tests/test_templates.py
git commit -m "$(cat <<'EOF'
refactor(adapter-langchain): chat_completions delegates to process_turn

The non-streaming OpenAI-compatible /v1/chat/completions path
collapses to a wire-shape translator: pull text from request,
build metadata, call process_turn, format ChatCompletionResponse.
Streaming branch still routes to _stream_chat_completions —
migrated separately in Phase 4.

Refs: docs/superpowers/specs/2026-04-26-langchain-adapter-shared-turn-core-design.md
EOF
)"
```

---

## Task 3.2: Migrate `create_response` (sync) to `process_turn`

**Files:**
- Modify: `packages/python/vystak-adapter-langchain/src/vystak_adapter_langchain/responses.py`
- Modify: `packages/python/vystak-adapter-langchain/tests/test_templates.py` (or `test_adapter.py` if responses are tested there)

The `/v1/responses` synchronous path is the second one-shot HTTP path. Its emitter is around line 179 of `responses.py`.

- [ ] **Step 3.2.1: Locate the existing emitter**

Read `packages/python/vystak-adapter-langchain/src/vystak_adapter_langchain/responses.py` from line 150 to ~220 to see the exact shape of `create_response` (sync). The function builds a `Response` object from the `ainvoke` result.

- [ ] **Step 3.2.2: Write the failing test**

Append to `test_templates.py`:

```python
class TestCreateResponseUsesProcessTurn:
    def _server_py(self):
        from vystak_adapter_langchain.adapter import LangChainAdapter
        from vystak.schema.agent import Agent
        from vystak.schema.model import Model
        from vystak.schema.provider import Provider
        from vystak.schema.platform import Platform
        from vystak.schema.secret import Secret

        p = Provider(name="anthropic", type="anthropic")
        d = Provider(name="docker", type="docker")
        agent = Agent(
            name="probe",
            model=Model(name="m", model_name="claude", provider=p),
            platform=Platform(name="local", type="docker", provider=d),
            secrets=[Secret(name="K")],
        )
        return LangChainAdapter().generate_code(agent).files["server.py"]

    def test_create_response_calls_process_turn(self):
        import re
        src = self._server_py()
        match = re.search(
            r"async def create_response\(.*?\):\s*\n(.*?)(?=\nasync def |\nclass |\Z)",
            src, re.DOTALL,
        )
        assert match
        body = match.group(1)
        assert "await process_turn(" in body

    def test_create_response_no_longer_inlines_ainvoke(self):
        import re
        src = self._server_py()
        match = re.search(
            r"async def create_response\(.*?\):\s*\n(.*?)(?=\nasync def |\nclass |\Z)",
            src, re.DOTALL,
        )
        body = match.group(1)
        assert "_agent.ainvoke(" not in body
        assert "handle_memory_actions(" not in body
```

- [ ] **Step 3.2.3: Run + confirm fail**

```bash
uv run pytest packages/python/vystak-adapter-langchain/tests/test_templates.py::TestCreateResponseUsesProcessTurn -v
```

Expected: 2 failures.

- [ ] **Step 3.2.4: Rewrite `_emit_create_response_sync` in `responses.py`**

Locate the function around line 179 (whichever helper appends `result = await {agent_ref}.ainvoke(`). Replace its sync-mode emission so the body becomes:

```python
    lines.append('    text = _extract_text_from_input(request.input)')
    lines.append('    metadata = {')
    lines.append('        "sessionId": request.previous_response_id or request.session_id,')
    lines.append('        "user_id": request.user_id,')
    lines.append('        "project_id": request.project_id,')
    lines.append('        "trace_id": request.trace_id,')
    lines.append('    }')
    lines.append("    turn = await process_turn(text, metadata)")
    lines.append("    response_id = f'resp_{uuid.uuid4().hex}'")
    lines.append("    response = Response(")
    lines.append("        id=response_id,")
    lines.append("        object='response',")
    lines.append("        created_at=int(time.time()),")
    lines.append("        model=request.model or 'vystak/' + AGENT_NAME,")
    lines.append("        status='completed' if turn.interrupt_text is None else 'in_progress',")
    lines.append("        output=[ResponseOutputMessage(")
    lines.append("            id=f'msg_{uuid.uuid4().hex}',")
    lines.append("            role='assistant',")
    lines.append("            content=[ResponseOutputText(text=turn.response_text, type='output_text')],")
    lines.append("        )],")
    lines.append("    )")
    lines.append("    if request.store:")
    lines.append("        response_store[response_id] = response")
    lines.append("    return response")
```

If field names don't match (`previous_response_id`, `_extract_text_from_input`, `Response`, `ResponseOutputMessage`, `ResponseOutputText`), use whatever symbols the existing emitter uses — the goal is "same response shape, body delegated to process_turn." Read the existing emit code first.

- [ ] **Step 3.2.5: Run tests + verify pass**

```bash
uv run pytest packages/python/vystak-adapter-langchain/tests/test_templates.py::TestCreateResponseUsesProcessTurn -v
```

Expected: PASS.

- [ ] **Step 3.2.6: Run full suite + lint + ast-parse**

```bash
uv run pytest packages/python/vystak-adapter-langchain/ -v
just lint-python
uv run python -c "
from vystak_adapter_langchain.adapter import LangChainAdapter
import ast
from vystak.schema.agent import Agent
from vystak.schema.model import Model
from vystak.schema.provider import Provider
from vystak.schema.platform import Platform
from vystak.schema.secret import Secret

p = Provider(name='anthropic', type='anthropic')
d = Provider(name='docker', type='docker')
m = Model(name='m', model_name='claude', provider=p)
agent = Agent(name='probe', model=m, platform=Platform(name='local', type='docker', provider=d), secrets=[Secret(name='K')])
ast.parse(LangChainAdapter().generate_code(agent).files['server.py'])
print('OK')
"
```

- [ ] **Step 3.2.7: Commit**

```bash
git add packages/python/vystak-adapter-langchain/src/vystak_adapter_langchain/responses.py \
        packages/python/vystak-adapter-langchain/tests/test_templates.py
git commit -m "$(cat <<'EOF'
refactor(adapter-langchain): create_response (sync) delegates to process_turn

The /v1/responses synchronous path collapses to a wire translator.
Streaming + background-mode branches still inline their own logic —
migrated in Tasks 3.3 and 4.3.

Refs: docs/superpowers/specs/2026-04-26-langchain-adapter-shared-turn-core-design.md
EOF
)"
```

---

## Task 3.3: Migrate `_run_background` (sync mode) to `process_turn`

**Files:**
- Modify: `packages/python/vystak-adapter-langchain/src/vystak_adapter_langchain/responses.py`
- Modify: `packages/python/vystak-adapter-langchain/tests/test_templates.py`

`_run_background` is dispatched by `create_response` when the request has `background=true`. It has TWO internal branches: a sync `ainvoke` branch (~L238) and a streaming `astream` branch (~L395). Migrate the sync branch here; streaming branch is Task 4.3.

- [ ] **Step 3.3.1: Read the existing emitter**

```bash
sed -n '220,310p' packages/python/vystak-adapter-langchain/src/vystak_adapter_langchain/responses.py
```

- [ ] **Step 3.3.2: Write the failing test**

Append to `test_templates.py`:

```python
class TestRunBackgroundSyncUsesProcessTurn:
    def _server_py(self):
        from vystak_adapter_langchain.adapter import LangChainAdapter
        from vystak.schema.agent import Agent
        from vystak.schema.model import Model
        from vystak.schema.provider import Provider
        from vystak.schema.platform import Platform
        from vystak.schema.secret import Secret

        p = Provider(name="anthropic", type="anthropic")
        d = Provider(name="docker", type="docker")
        agent = Agent(
            name="probe",
            model=Model(name="m", model_name="claude", provider=p),
            platform=Platform(name="local", type="docker", provider=d),
            secrets=[Secret(name="K")],
        )
        return LangChainAdapter().generate_code(agent).files["server.py"]

    def test_run_background_sync_branch_calls_process_turn(self):
        """Find the sync (non-stream) branch inside _run_background; it must call process_turn."""
        src = self._server_py()
        # The sync branch is the one that doesn't use astream; assert
        # process_turn is invoked somewhere inside _run_background.
        import re
        match = re.search(
            r"async def _run_background\(.*?\):\s*\n(.*?)(?=\nasync def |\nclass |\Z)",
            src, re.DOTALL,
        )
        assert match
        body = match.group(1)
        assert "await process_turn(" in body
```

- [ ] **Step 3.3.3: Run + confirm fail**

```bash
uv run pytest packages/python/vystak-adapter-langchain/tests/test_templates.py::TestRunBackgroundSyncUsesProcessTurn -v
```

Expected: 1 failure.

- [ ] **Step 3.3.4: Rewrite the sync branch in `_emit_run_background`**

Find the `if not request.stream:` (or equivalent) branch in `_emit_run_background` in `responses.py` at line ~238. Replace its inline `_agent.ainvoke` block + memory call with a `process_turn` invocation:

```python
    lines.append("        if not request.stream:")
    lines.append('            text = _extract_text_from_input(request.input)')
    lines.append('            metadata = {')
    lines.append('                "sessionId": request.previous_response_id or request.session_id,')
    lines.append('                "user_id": user_id,')
    lines.append('                "project_id": project_id,')
    lines.append('                "trace_id": request.trace_id,')
    lines.append('            }')
    lines.append("            turn = await process_turn(text, metadata, task_id=response_id)")
    lines.append("            # Update the stored response object with the final text.")
    lines.append("            stored = response_store.get(response_id)")
    lines.append("            if stored is not None:")
    lines.append("                stored.status = 'completed' if turn.interrupt_text is None else 'in_progress'")
    lines.append("                stored.output = [ResponseOutputMessage(")
    lines.append("                    id=f'msg_{uuid.uuid4().hex}',")
    lines.append("                    role='assistant',")
    lines.append("                    content=[ResponseOutputText(text=turn.response_text, type='output_text')],")
    lines.append("                )]")
    lines.append("            return")
```

Adjust field names / variable names to match the existing emitter exactly. The streaming branch (after the `else:`) is unchanged in this task.

- [ ] **Step 3.3.5: Run tests + verify pass + lint + ast-parse**

```bash
uv run pytest packages/python/vystak-adapter-langchain/ -v
just lint-python
uv run python -c "
from vystak_adapter_langchain.adapter import LangChainAdapter
import ast
from vystak.schema.agent import Agent
from vystak.schema.model import Model
from vystak.schema.provider import Provider
from vystak.schema.platform import Platform
from vystak.schema.secret import Secret

p = Provider(name='anthropic', type='anthropic')
d = Provider(name='docker', type='docker')
m = Model(name='m', model_name='claude', provider=p)
agent = Agent(name='probe', model=m, platform=Platform(name='local', type='docker', provider=d), secrets=[Secret(name='K')])
ast.parse(LangChainAdapter().generate_code(agent).files['server.py'])
print('OK')
"
```

- [ ] **Step 3.3.6: Commit**

```bash
git add packages/python/vystak-adapter-langchain/src/vystak_adapter_langchain/responses.py \
        packages/python/vystak-adapter-langchain/tests/test_templates.py
git commit -m "$(cat <<'EOF'
refactor(adapter-langchain): _run_background sync branch uses process_turn

Phase 3 complete: every one-shot path now delegates to the shared
core. ainvoke sites in source: 2 (process_turn body + the unmigrated
streaming branch of _run_background, which is Task 4.3). Streaming
phase next.

Refs: docs/superpowers/specs/2026-04-26-langchain-adapter-shared-turn-core-design.md
EOF
)"
```

---

## Task 4.1: Migrate `_a2a_streaming` to `process_turn_streaming`

**Files:**
- Modify: `packages/python/vystak-adapter-langchain/src/vystak_adapter_langchain/a2a.py`
- Modify: `packages/python/vystak-adapter-langchain/tests/test_a2a.py`

This task **also fixes the still-broken streaming memory bug**. `_a2a_streaming` today never calls `handle_memory_actions`, so save_memory invocations made via streaming A2A are silently dropped. After this task, `process_turn_streaming` handles them.

- [ ] **Step 4.1.1: Write the failing test**

Append to `test_a2a.py`:

```python
class TestA2AStreamingUsesProcessTurnStreaming:
    def _server_py(self):
        from vystak_adapter_langchain.a2a import emit_a2a
        from vystak.schema.agent import Agent
        from vystak.schema.model import Model
        from vystak.schema.provider import Provider
        from vystak.schema.platform import Platform
        from vystak.schema.secret import Secret

        p = Provider(name="anthropic", type="anthropic")
        d = Provider(name="docker", type="docker")
        agent = Agent(
            name="probe",
            model=Model(name="m", model_name="claude", provider=p),
            platform=Platform(name="local", type="docker", provider=d),
            secrets=[Secret(name="K")],
        )
        return emit_a2a(agent)

    def test_a2a_streaming_calls_process_turn_streaming(self):
        import re
        src = self._server_py()
        match = re.search(
            r"async def _a2a_streaming\(.*?\)(?:\s*->\s*[^\n:]*)?:\s*\n(.*?)(?=\nasync def |\Z)",
            src, re.DOTALL,
        )
        assert match
        body = match.group(1)
        assert "process_turn_streaming(" in body

    def test_a2a_streaming_no_longer_inlines_astream_events(self):
        import re
        src = self._server_py()
        match = re.search(
            r"async def _a2a_streaming\(.*?\)(?:\s*->\s*[^\n:]*)?:\s*\n(.*?)(?=\nasync def |\Z)",
            src, re.DOTALL,
        )
        body = match.group(1)
        assert "_agent.astream_events(" not in body
```

- [ ] **Step 4.1.2: Run + confirm fail**

```bash
uv run pytest packages/python/vystak-adapter-langchain/tests/test_a2a.py::TestA2AStreamingUsesProcessTurnStreaming -v
```

Expected: 2 failures.

- [ ] **Step 4.1.3: Rewrite the `_a2a_streaming` emitter**

In `a2a.py`, locate the block starting at line ~207 with `lines.append("async def _a2a_streaming(...)`. Delete from line ~207 through the closing `lines.append("")` of that function (around line ~296). Replace with:

```python
    # --- Streaming callable (delegates to process_turn_streaming) ---
    lines.append("async def _a2a_streaming(message: A2AMessage, metadata: dict):")
    lines.append('    """Stream agent events via the shared streaming core.')
    lines.append("")
    lines.append("    Maps each TurnEvent into the corresponding A2AEvent shape.")
    lines.append('    """')
    lines.append("    task_id = message.correlation_id or str(uuid.uuid4())")
    lines.append('    text = " ".join(p.get("text", "") for p in message.parts if "text" in p)')
    lines.append("")
    lines.append("    existing = _task_manager.get_task(task_id)")
    lines.append("    if existing is None:")
    lines.append("        _task_manager.create_task(task_id, {")
    lines.append('            "role": message.role,')
    lines.append('            "parts": message.parts,')
    lines.append("        })")
    lines.append('    _task_manager.update_task(task_id, "working")')
    lines.append("")
    lines.append("    existing = _task_manager.get_task(task_id)")
    lines.append('    is_resume = existing is not None and existing["status"]["state"] == "input_required"')
    lines.append("    resume_text = text if is_resume else None")
    lines.append("    turn_text = None if is_resume else text")
    lines.append("")
    lines.append("    try:")
    lines.append("        async for ev in process_turn_streaming(")
    lines.append("            turn_text or text, metadata,")
    lines.append("            resume_text=resume_text, task_id=task_id,")
    lines.append("        ):")
    lines.append('            if ev.type == "token":')
    lines.append('                yield A2AEvent(type="token", text=ev.text)')
    lines.append('            elif ev.type == "interrupt":')
    lines.append('                _task_manager.update_task(task_id, "input_required", ev.text)')
    lines.append("                yield A2AEvent(")
    lines.append('                    type="status",')
    lines.append("                    text=ev.text,")
    lines.append('                    data={"state": "input_required", "task_id": task_id},')
    lines.append("                    final=True,")
    lines.append("                )")
    lines.append("                return")
    lines.append('            elif ev.type == "final":')
    lines.append('                _task_manager.update_task(task_id, "completed", ev.text)')
    lines.append("                yield A2AEvent(")
    lines.append('                    type="final",')
    lines.append("                    text=ev.text,")
    lines.append('                    data={"state": "completed", "task_id": task_id},')
    lines.append("                    final=True,")
    lines.append("                )")
    lines.append("    except Exception as exc:")
    lines.append('        _task_manager.update_task(task_id, "failed", str(exc))')
    lines.append("        raise")
    lines.append("")
    lines.append("")
```

- [ ] **Step 4.1.4: Run tests + verify pass + lint + ast-parse**

```bash
uv run pytest packages/python/vystak-adapter-langchain/ -v
just lint-python
uv run python -c "
from vystak_adapter_langchain.adapter import LangChainAdapter
import ast
from vystak.schema.agent import Agent
from vystak.schema.model import Model
from vystak.schema.provider import Provider
from vystak.schema.platform import Platform
from vystak.schema.secret import Secret

p = Provider(name='anthropic', type='anthropic')
d = Provider(name='docker', type='docker')
m = Model(name='m', model_name='claude', provider=p)
agent = Agent(name='probe', model=m, platform=Platform(name='local', type='docker', provider=d), secrets=[Secret(name='K')])
ast.parse(LangChainAdapter().generate_code(agent).files['server.py'])
print('OK')
"
```

- [ ] **Step 4.1.5: Commit**

```bash
git add packages/python/vystak-adapter-langchain/src/vystak_adapter_langchain/a2a.py \
        packages/python/vystak-adapter-langchain/tests/test_a2a.py
git commit -m "$(cat <<'EOF'
fix(adapter-langchain): _a2a_streaming now persists save_memory sentinels

Migrated _a2a_streaming to process_turn_streaming. Closes the second
half of the same bug class fixed for _a2a_one_shot on 2026-04-26 —
streaming A2A turns no longer drop save_memory sentinels on the floor.

Refs: docs/superpowers/specs/2026-04-26-langchain-adapter-shared-turn-core-design.md
EOF
)"
```

---

## Task 4.2: Migrate `_stream_chat_completions` to `process_turn_streaming`

**Files:**
- Modify: `packages/python/vystak-adapter-langchain/src/vystak_adapter_langchain/templates.py`
- Modify: `packages/python/vystak-adapter-langchain/tests/test_templates.py`

`_stream_chat_completions` is the streaming branch of OpenAI-compatible chat completions. Today it does its own `astream` + collects tool messages + calls `handle_memory_actions(tool_msgs, ...)`. After migration: delegates to `process_turn_streaming` and shapes each `TurnEvent` into the SSE delta format.

- [ ] **Step 4.2.1: Read the existing emitter**

```bash
sed -n '780,880p' packages/python/vystak-adapter-langchain/src/vystak_adapter_langchain/templates.py
```

- [ ] **Step 4.2.2: Write the failing test**

Append to `test_templates.py`:

```python
class TestStreamChatCompletionsUsesProcessTurnStreaming:
    def _server_py(self):
        from vystak_adapter_langchain.adapter import LangChainAdapter
        from vystak.schema.agent import Agent
        from vystak.schema.model import Model
        from vystak.schema.provider import Provider
        from vystak.schema.platform import Platform
        from vystak.schema.secret import Secret

        p = Provider(name="anthropic", type="anthropic")
        d = Provider(name="docker", type="docker")
        agent = Agent(
            name="probe",
            model=Model(name="m", model_name="claude", provider=p),
            platform=Platform(name="local", type="docker", provider=d),
            secrets=[Secret(name="K")],
        )
        return LangChainAdapter().generate_code(agent).files["server.py"]

    def test_stream_chat_completions_calls_process_turn_streaming(self):
        import re
        src = self._server_py()
        match = re.search(
            r"async def _stream_chat_completions\(.*?\):\s*\n(.*?)(?=\nasync def |\nclass |\Z)",
            src, re.DOTALL,
        )
        assert match
        body = match.group(1)
        assert "process_turn_streaming(" in body
        assert "_agent.astream(" not in body
        assert "handle_memory_actions(" not in body
```

- [ ] **Step 4.2.3: Run + confirm fail**

```bash
uv run pytest packages/python/vystak-adapter-langchain/tests/test_templates.py::TestStreamChatCompletionsUsesProcessTurnStreaming -v
```

Expected: 1 failure.

- [ ] **Step 4.2.4: Rewrite the emitter**

In `templates.py` find the helper that emits `_stream_chat_completions` (around line 782). Replace the body emission:

```python
    lines.append("async def _stream_chat_completions(messages, config, request):")
    lines.append('    """Streaming /v1/chat/completions — delegates to process_turn_streaming."""')
    lines.append('    text = messages[-1]["content"] if messages else ""')
    lines.append('    metadata = {')
    lines.append('        "sessionId": request.session_id,')
    lines.append('        "user_id": request.user_id,')
    lines.append('        "project_id": request.project_id,')
    lines.append('        "trace_id": request.trace_id,')
    lines.append('    }')
    lines.append('    completion_id = f"chatcmpl-{uuid.uuid4().hex}"')
    lines.append("    created = int(time.time())")
    lines.append('    model = request.model or "vystak/" + AGENT_NAME')
    lines.append("")
    lines.append("    async def _gen():")
    lines.append("        async for ev in process_turn_streaming(text, metadata):")
    lines.append('            if ev.type == "token":')
    lines.append("                yield 'data: ' + _chunk_payload(completion_id, created, model, ev.text) + '\\n\\n'")
    lines.append('            elif ev.type == "final":')
    lines.append("                yield 'data: ' + _chunk_payload(completion_id, created, model, '', finish_reason='stop') + '\\n\\n'")
    lines.append("                yield 'data: [DONE]\\n\\n'")
    lines.append("                return")
    lines.append("    return StreamingResponse(_gen(), media_type='text/event-stream')")
```

`_chunk_payload` is a helper that already exists in the templates module — find its current emission and reuse the same name. If absent, add a small inline emission of it before this block.

- [ ] **Step 4.2.5: Run + verify + lint + ast-parse**

```bash
uv run pytest packages/python/vystak-adapter-langchain/ -v
just lint-python
uv run python -c "
from vystak_adapter_langchain.adapter import LangChainAdapter
import ast
from vystak.schema.agent import Agent
from vystak.schema.model import Model
from vystak.schema.provider import Provider
from vystak.schema.platform import Platform
from vystak.schema.secret import Secret

p = Provider(name='anthropic', type='anthropic')
d = Provider(name='docker', type='docker')
m = Model(name='m', model_name='claude', provider=p)
agent = Agent(name='probe', model=m, platform=Platform(name='local', type='docker', provider=d), secrets=[Secret(name='K')])
ast.parse(LangChainAdapter().generate_code(agent).files['server.py'])
print('OK')
"
```

- [ ] **Step 4.2.6: Commit**

```bash
git add packages/python/vystak-adapter-langchain/src/vystak_adapter_langchain/templates.py \
        packages/python/vystak-adapter-langchain/tests/test_templates.py
git commit -m "$(cat <<'EOF'
refactor(adapter-langchain): _stream_chat_completions uses process_turn_streaming

Streaming OpenAI-compatible chat completions migrated. Was already
handling memory correctly via tool_msgs collection; now goes through
the shared streaming core for consistency.

Refs: docs/superpowers/specs/2026-04-26-langchain-adapter-shared-turn-core-design.md
EOF
)"
```

---

## Task 4.3: Migrate `_run_background` (stream branch) to `process_turn_streaming`

**Files:**
- Modify: `packages/python/vystak-adapter-langchain/src/vystak_adapter_langchain/responses.py`
- Modify: `packages/python/vystak-adapter-langchain/tests/test_templates.py`

The streaming branch of `_run_background` (around `responses.py:395`).

- [ ] **Step 4.3.1: Read the current emitter**

```bash
sed -n '380,470p' packages/python/vystak-adapter-langchain/src/vystak_adapter_langchain/responses.py
```

- [ ] **Step 4.3.2: Write the failing test**

Append to `test_templates.py`:

```python
class TestRunBackgroundStreamUsesProcessTurnStreaming:
    def _server_py(self):
        from vystak_adapter_langchain.adapter import LangChainAdapter
        from vystak.schema.agent import Agent
        from vystak.schema.model import Model
        from vystak.schema.provider import Provider
        from vystak.schema.platform import Platform
        from vystak.schema.secret import Secret

        p = Provider(name="anthropic", type="anthropic")
        d = Provider(name="docker", type="docker")
        agent = Agent(
            name="probe",
            model=Model(name="m", model_name="claude", provider=p),
            platform=Platform(name="local", type="docker", provider=d),
            secrets=[Secret(name="K")],
        )
        return LangChainAdapter().generate_code(agent).files["server.py"]

    def test_run_background_streaming_branch_uses_process_turn_streaming(self):
        import re
        src = self._server_py()
        match = re.search(
            r"async def _run_background\(.*?\):\s*\n(.*?)(?=\nasync def |\nclass |\Z)",
            src, re.DOTALL,
        )
        body = match.group(1)
        assert "process_turn_streaming(" in body
        # No more direct astream / astream_events inside this function.
        assert "_agent.astream(" not in body
        assert "_agent.astream_events(" not in body
```

- [ ] **Step 4.3.3: Run + confirm fail**

```bash
uv run pytest packages/python/vystak-adapter-langchain/tests/test_templates.py::TestRunBackgroundStreamUsesProcessTurnStreaming -v
```

Expected: 1 failure.

- [ ] **Step 4.3.4: Rewrite the streaming branch in `_emit_run_background`**

In `responses.py`, find the `else:` (or `if request.stream:`) branch around line 395. Replace its inline `_agent.astream(...)` block + tool_msgs collection + memory call with:

```python
    lines.append("        else:")
    lines.append('            text = _extract_text_from_input(request.input)')
    lines.append('            metadata = {')
    lines.append('                "sessionId": request.previous_response_id or request.session_id,')
    lines.append('                "user_id": user_id,')
    lines.append('                "project_id": project_id,')
    lines.append('                "trace_id": request.trace_id,')
    lines.append('            }')
    lines.append("            accumulated = []")
    lines.append("            async for ev in process_turn_streaming(")
    lines.append("                text, metadata, task_id=response_id,")
    lines.append("            ):")
    lines.append('                if ev.type == "token":')
    lines.append("                    accumulated.append(ev.text)")
    lines.append('                elif ev.type == "final":')
    lines.append("                    final_text = ev.text or ''.join(accumulated)")
    lines.append("                    stored = response_store.get(response_id)")
    lines.append("                    if stored is not None:")
    lines.append("                        stored.status = 'completed'")
    lines.append("                        stored.output = [ResponseOutputMessage(")
    lines.append("                            id=f'msg_{uuid.uuid4().hex}',")
    lines.append("                            role='assistant',")
    lines.append("                            content=[ResponseOutputText(text=final_text, type='output_text')],")
    lines.append("                        )]")
    lines.append("                    return")
    lines.append('                elif ev.type == "interrupt":')
    lines.append("                    stored = response_store.get(response_id)")
    lines.append("                    if stored is not None:")
    lines.append("                        stored.status = 'in_progress'")
    lines.append("                    return")
```

- [ ] **Step 4.3.5: Run + verify + lint + ast-parse**

```bash
uv run pytest packages/python/vystak-adapter-langchain/ -v
just lint-python
uv run python -c "
from vystak_adapter_langchain.adapter import LangChainAdapter
import ast
from vystak.schema.agent import Agent
from vystak.schema.model import Model
from vystak.schema.provider import Provider
from vystak.schema.platform import Platform
from vystak.schema.secret import Secret

p = Provider(name='anthropic', type='anthropic')
d = Provider(name='docker', type='docker')
m = Model(name='m', model_name='claude', provider=p)
agent = Agent(name='probe', model=m, platform=Platform(name='local', type='docker', provider=d), secrets=[Secret(name='K')])
ast.parse(LangChainAdapter().generate_code(agent).files['server.py'])
print('OK')
"
```

- [ ] **Step 4.3.6: Commit**

```bash
git add packages/python/vystak-adapter-langchain/src/vystak_adapter_langchain/responses.py \
        packages/python/vystak-adapter-langchain/tests/test_templates.py
git commit -m "$(cat <<'EOF'
refactor(adapter-langchain): _run_background streaming branch via shared core

Phase 4 complete: every streaming path now flows through
process_turn_streaming. Streaming memory bug closed across all
three streaming protocols.

Refs: docs/superpowers/specs/2026-04-26-langchain-adapter-shared-turn-core-design.md
EOF
)"
```

---

## Task 5.1: Acceptance — grep-level structural guarantees

**Files:**
- Modify: `packages/python/vystak-adapter-langchain/tests/test_adapter.py`

Spec acceptance criteria 1, 2 say `_agent.ainvoke`, `_agent.astream_events`, and `handle_memory_actions` should each appear once in the right places in the source-tree (excluding test files). Encode as a test so future regressions are blocked.

- [ ] **Step 5.1.1: Write the test**

Append to `test_adapter.py`:

```python
class TestSharedTurnCoreInvariants:
    """Acceptance criteria 1 and 2 from the spec.

    These are the structural backstop preventing the duplicated-path
    pattern from coming back. If a future change adds an _agent.ainvoke
    call outside process_turn, this test breaks and the author
    notices.
    """

    SRC = "packages/python/vystak-adapter-langchain/src/vystak_adapter_langchain"

    def _grep_source(self, needle):
        import pathlib
        root = pathlib.Path(__file__).resolve().parents[3] / self.SRC
        hits = []
        for path in sorted(root.glob("*.py")):
            text = path.read_text()
            for lineno, line in enumerate(text.splitlines(), 1):
                if needle in line:
                    hits.append(f"{path.name}:{lineno}: {line.strip()}")
        return hits

    def test_ainvoke_appears_only_inside_turn_core(self):
        hits = self._grep_source("_agent.ainvoke(")
        # Only one site: inside the process_turn emission in turn_core.py
        assert len(hits) == 1, "expected 1 _agent.ainvoke site, got:\n" + "\n".join(hits)
        assert hits[0].startswith("turn_core.py:"), (
            f"_agent.ainvoke should live in turn_core.py only; got: {hits[0]}"
        )

    def test_astream_events_appears_only_inside_turn_core(self):
        hits = self._grep_source("_agent.astream_events(")
        assert len(hits) == 1, "expected 1 _agent.astream_events site, got:\n" + "\n".join(hits)
        assert hits[0].startswith("turn_core.py:")

    def test_handle_memory_actions_call_sites(self):
        """handle_memory_actions is called from exactly two places: process_turn and process_turn_streaming."""
        hits = self._grep_source("await handle_memory_actions(")
        assert len(hits) == 2, "expected 2 handle_memory_actions call sites, got:\n" + "\n".join(hits)
        assert all(h.startswith("turn_core.py:") for h in hits)
```

- [ ] **Step 5.1.2: Run the test**

```bash
uv run pytest packages/python/vystak-adapter-langchain/tests/test_adapter.py::TestSharedTurnCoreInvariants -v
```

Expected: PASS. If any of the 3 fails, there is a leftover inlined call that needs to be migrated — go back to Phase 2/3/4 and finish it.

- [ ] **Step 5.1.3: Commit**

```bash
git add packages/python/vystak-adapter-langchain/tests/test_adapter.py
git commit -m "$(cat <<'EOF'
test(adapter-langchain): grep-level invariants for shared turn core

_agent.ainvoke, _agent.astream_events, and handle_memory_actions
must live exactly in turn_core.py. Locks in spec acceptance criteria
1 and 2 so future changes can't silently add a path-specific copy.

Refs: docs/superpowers/specs/2026-04-26-langchain-adapter-shared-turn-core-design.md
EOF
)"
```

---

## Task 5.2: End-to-end memory regression (release-tier)

**Files:**
- Create: `packages/python/vystak-channel-slack/tests/release/test_thread_memory_a2a.py`

Release-tier test: spin up `examples/docker-slack-multi-agent`, send a save trigger via A2A one-shot, assert a row lands in the agent's sessions store. Gated by the existing `release_smoke` marker so it only runs when Docker is available.

- [ ] **Step 5.2.1: Create the test**

```python
"""Release-tier regression for the shared turn core's memory persistence.

Deploys docker-slack-multi-agent, fires a save trigger via the A2A
one-shot path (the same path the Slack channel uses), then inspects the
agent's sqlite store to confirm the row landed. Tears down on exit.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import httpx
import pytest


pytestmark = pytest.mark.release_smoke

EXAMPLE = Path(__file__).resolve().parents[5] / "examples" / "docker-slack-multi-agent"


def _vystak(args: list[str], cwd: Path):
    env_path = cwd / ".env"
    if not env_path.exists():
        # Fallback to repo-root .env if symlink is not present.
        repo_env = Path(__file__).resolve().parents[5] / ".env"
        if repo_env.exists():
            shutil.copy(repo_env, env_path)
    return subprocess.run(
        ["uv", "run", "vystak", *args],
        cwd=str(cwd), check=True, capture_output=True, text=True,
    )


def _agent_port(name: str) -> int:
    out = subprocess.check_output(
        ["docker", "port", name, "8000"], text=True,
    ).strip()
    # e.g. "0.0.0.0:54321" — take the host port
    return int(out.splitlines()[0].split(":")[-1])


def _store_rows() -> int:
    code = textwrap.dedent('''
        import sqlite3
        n = sqlite3.connect("/data/sessions_store.db").execute(
            "SELECT count(*) FROM store"
        ).fetchone()[0]
        print(n)
    ''')
    out = subprocess.check_output(
        ["docker", "exec", "vystak-assistant-agent", "python", "-c", code],
        text=True,
    )
    return int(out.strip())


@pytest.mark.skipif(
    not EXAMPLE.exists(),
    reason="examples/docker-slack-multi-agent missing",
)
def test_a2a_one_shot_persists_save_memory(tmp_path):
    """A save_memory invocation made via A2A one-shot must persist."""
    # Deploy
    _vystak(["destroy"], EXAMPLE)  # idempotent — safe even if nothing's up
    _vystak(["apply"], EXAMPLE)
    try:
        port = _agent_port("vystak-assistant-agent")

        # Confirm starting state.
        baseline = _store_rows()

        # Fire the save trigger via A2A one-shot.
        with httpx.Client(timeout=120) as client:
            resp = client.post(
                f"http://localhost:{port}/a2a",
                json={
                    "jsonrpc": "2.0", "id": "regression",
                    "method": "tasks/send",
                    "params": {
                        "id": "regression",
                        "message": {
                            "role": "user",
                            "parts": [{"text": (
                                "My name is RegressionTester. Save this fact "
                                "using save_memory."
                            )}],
                        },
                        "metadata": {
                            "sessionId": "regression",
                            "user_id": "slack:URELEASE",
                        },
                    },
                },
            )
            resp.raise_for_status()

        # Allow the agent's lifespan store flush to settle.
        deadline = time.time() + 10
        while time.time() < deadline:
            if _store_rows() > baseline:
                break
            time.sleep(0.5)

        assert _store_rows() > baseline, (
            "save_memory did not persist; the A2A one-shot path is "
            "likely missing handle_memory_actions"
        )
    finally:
        _vystak(["destroy"], EXAMPLE)
```

- [ ] **Step 5.2.2: Run the test**

```bash
uv run pytest packages/python/vystak-channel-slack/tests/release/test_thread_memory_a2a.py -v -m release_smoke
```

Expected: PASS, takes ~30–60s. Skips if the example dir is missing.

- [ ] **Step 5.2.3: Commit**

```bash
git add packages/python/vystak-channel-slack/tests/release/test_thread_memory_a2a.py
git commit -m "$(cat <<'EOF'
test(release): A2A save_memory persistence regression

Release-tier test deploys docker-slack-multi-agent, fires save_memory
via A2A one-shot, verifies a row lands in the sessions store, tears
down. Gated by release_smoke marker (Docker required).

Catches regression of either:
  - turn_core dropping handle_memory_actions
  - protocol layer regressing back to inlined ainvoke without memory call

Refs: docs/superpowers/specs/2026-04-26-langchain-adapter-shared-turn-core-design.md
EOF
)"
```

---

## Task 5.3: Final verification

**Files:** none modified — verification only.

- [ ] **Step 5.3.1: Run all four CI gates**

```bash
just lint-python
just test-python
just typecheck-typescript
just test-typescript
```

Expected: every gate passes.

- [ ] **Step 5.3.2: Run the full release-smoke suite**

```bash
uv run pytest packages/python/vystak-provider-docker/tests/release/ \
              packages/python/vystak-channel-slack/tests/release/ \
              -v -m "release_smoke or release_integration"
```

Expected: same pass/skip pattern as before the refactor + the new memory regression test passes.

- [ ] **Step 5.3.3: Manual end-to-end Slack check**

In `examples/docker-slack-multi-agent/`:

1. `uv run vystak destroy && uv run vystak apply`.
2. In Slack: `@VyStack my name is Anatoly`. Wait for reply.
3. In a brand-new thread (root-level post in the same channel): `@VyStack do you know my name?`. Bot should answer "Anatoly" — the round-trip exercises both the migrated A2A one-shot path and the memory recall path.
4. `uv run vystak destroy`.

If steps 2–3 work, the refactor is functionally complete.

- [ ] **Step 5.3.4: Verify the spec acceptance criterion 5 (smaller server.py)**

```bash
uv run python -c "
from vystak_adapter_langchain.adapter import LangChainAdapter
from vystak.schema.agent import Agent
from vystak.schema.model import Model
from vystak.schema.provider import Provider
from vystak.schema.platform import Platform
from vystak.schema.secret import Secret
from vystak.schema.service import Sqlite

p = Provider(name='anthropic', type='anthropic')
d = Provider(name='docker', type='docker')
m = Model(name='m', model_name='claude', provider=p)
agent = Agent(
    name='probe', model=m,
    platform=Platform(name='local', type='docker', provider=d),
    secrets=[Secret(name='K')],
    sessions=Sqlite(name='probe-sessions', provider=d),
)
src = LangChainAdapter().generate_code(agent).files['server.py']
print(f'lines={src.count(chr(10))} bytes={len(src)}')
"
```

Compare against pre-refactor numbers (run the same command on the merge-base of `main` and the refactor branch). Net should be a reduction. If it grew significantly, audit for accidental duplication; the cores plus seven 15-line translators should be smaller than seven 50-line inlined blocks.

- [ ] **Step 5.3.5: No commit** — verification only.

---

## Spec coverage checklist

| Spec section / requirement | Implemented in |
|---|---|
| Goal: collapse 7 paths to 2 cores + thin translators | Tasks 1–4 |
| `process_turn` signature `(text, metadata, *, resume_text=None, task_id=None)` | Task 1.1 (Step 1.1.3) |
| `process_turn_streaming` same signature, async generator | Task 1.1 (Step 1.1.3) |
| `TurnResult(response_text, messages, interrupt_text)` dataclass | Task 1.1 (Step 1.1.3) |
| `TurnEvent(type, text, data, final)` dataclass | Task 1.1 (Step 1.1.3) |
| Cores own `_agent.ainvoke` / `astream_events` | Tasks 5.1 grep-test enforces this |
| Cores own `handle_memory_actions` | Tasks 5.1 grep-test enforces this |
| Cores own interrupt/resume detection | Task 1.1 (`__interrupt__` block) |
| Each protocol layer is wire-shape translator only | Tasks 2–4 |
| Phase 1 — add cores (no migration) | Task 1 |
| Phase 2 — `_a2a_one_shot` migrated | Task 2.1 |
| Phase 3 — one-shot HTTP paths migrated | Tasks 3.1, 3.2, 3.3 |
| Phase 4 — streaming paths migrated | Tasks 4.1, 4.2, 4.3 |
| Phase 5 — delete dead code, verify | Tasks 5.1, 5.2, 5.3 |
| Streaming A2A memory bug fix | Task 4.1 |
| AC1 (`_agent.ainvoke` exactly once in src) | Task 5.1 (Step 5.1.1 first test) |
| AC2 (`handle_memory_actions` exactly twice in src) | Task 5.1 (Step 5.1.1 third test) |
| AC3 (streaming save_memory persists) | Task 4.1 + Task 5.2 (regression) |
| AC4 (regression-free; existing tests pass) | Each task ends with `uv run pytest packages/python/vystak-adapter-langchain/ -v` |
| AC5 (smaller `SERVER_PY`) | Task 5.3 (Step 5.3.4) |
| Out of scope: schema changes / channel changes / wire format / memory backend / slack hash | Plan stays inside the adapter package |
