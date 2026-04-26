# LangChain Adapter — Shared Turn Core Design

**Date:** 2026-04-26
**Status:** Approved (brainstorm)
**Scope:** `packages/python/vystak-adapter-langchain/` templates + emitted
`server.py` shape. No schema changes. No agent-side or channel-side changes.

## Goal

Collapse the six near-identical "run agent + post-process" code blocks
emitted into every generated `server.py` into **one shared one-shot
core** plus **one shared streaming core**. Each protocol layer (A2A,
`/v1/chat/completions`, `/v1/responses`) becomes a thin shape-translator
around the cores.

## Why

Today the LangChain adapter emits six places that each do their own
version of: `_agent.ainvoke(...)` → extract final text → call
`handle_memory_actions` → update `_task_manager` → return/yield. They
drift. Concrete evidence:

| Generator | Emits | `handle_memory_actions` |
|-----------|-------|--------------------------|
| `templates.py` | `chat_completions` | yes |
| `templates.py` | `_stream_chat_completions` | yes (tool_msgs path) |
| `responses.py` | `create_response` (sync) | yes |
| `responses.py` | `_run_background` (async/stream) | yes (tool_msgs path) |
| `a2a.py` | `_a2a_one_shot` | **was missing until 2026-04-26** |
| `a2a.py` | `_a2a_streaming` | **still missing** |

The Slack channel uses `_a2a_one_shot` and consequently silently dropped
every `save_memory` write until the path-specific fix landed. The same
class of bug will recur on the next cross-cutting feature (audit logging,
rate limiting, OTEL tracing, structured tool-call logging) unless the
six code paths fold into one.

## Architecture

Two emitted core helpers, called by every protocol layer:

```
                                  ┌──────────────────────────────────┐
                                  │ process_turn(                    │
  _a2a_one_shot         ────────▶ │     text, metadata, *,           │ ─▶ TurnResult(
  chat_completions      ────────▶ │     resume_text=None             │      response_text,
  create_response       ────────▶ │ ) → TurnResult                   │      messages,
                                  │   • _agent.ainvoke               │      interrupt_text)
                                  │   • handle_memory_actions        │
                                  │   • interrupt/resume detection   │
                                  └──────────────────────────────────┘

                                  ┌──────────────────────────────────┐
                                  │ process_turn_streaming(          │
  _a2a_streaming        ────────▶ │     text, metadata, *,           │ ─▶ AsyncIterator[TurnEvent]
  _stream_chat_completions ─────▶ │     resume_text=None             │
  _run_background       ────────▶ │ ) → AsyncIterator[TurnEvent]     │
                                  │   • _agent.astream_events        │
                                  │   • handle_memory_actions on tool│
                                  │     completion events            │
                                  │   • emit token / status / final  │
                                  └──────────────────────────────────┘
```

Each protocol layer:
1. Parses its wire shape into `(text, metadata)` (and optional
   `resume_text` for input_required scenarios).
2. Calls the appropriate core.
3. Translates `TurnResult` / `TurnEvent` into its protocol's response
   shape (JSON-RPC envelope, OpenAI delta, SSE frame, etc.).

The cores own:
- LangGraph `ainvoke` / `astream_events`
- Memory-action sentinel processing (`handle_memory_actions`)
- `_task_manager` state transitions (`working`/`completed`/`failed`/`input_required`)
- Interrupt/resume handling (`Command(resume=...)` and `__interrupt__` extraction)
- Future cross-cutting concerns (audit logs, OTEL, rate limiting, etc.)

Protocol layers own:
- Wire-format parsing (JSON-RPC envelope, OpenAI request body, SSE
  formatting)
- Response shaping (history field, tool_call deltas, final-status
  events)
- Protocol-specific bookkeeping (response IDs in `/v1/responses`,
  task IDs from A2A `correlation_id`, etc.)

## Data types (emitted into generated `server.py`)

```python
from dataclasses import dataclass
from typing import Literal


@dataclass
class TurnResult:
    """One-shot turn result. Returned by process_turn()."""
    response_text: str
    messages: list           # full message list from _agent.ainvoke
    interrupt_text: str | None = None  # set if input_required


@dataclass
class TurnEvent:
    """Single streamed event. Yielded by process_turn_streaming()."""
    type: Literal["token", "tool_call", "interrupt", "final", "error"]
    text: str = ""
    data: dict | None = None
    final: bool = False
```

`TurnEvent` is intentionally not protocol-specific — A2A maps it to
`A2AEvent`, OpenAI streaming maps it to chat-completion deltas,
`/v1/responses` maps it to its own SSE event types.

## Core functions (emitted once per agent)

```python
async def process_turn(
    text: str,
    metadata: dict,
    *,
    resume_text: str | None = None,
    task_id: str | None = None,
) -> TurnResult:
    """Run one agent turn. Used by all one-shot protocol paths."""
    session_id = metadata.get("sessionId") or task_id or str(uuid.uuid4())
    user_id = metadata.get("user_id")
    project_id = metadata.get("project_id")

    config = {"configurable": {
        "thread_id": session_id,
        "trace_id": metadata.get("trace_id") or str(uuid.uuid4()),
        "user_id": user_id,
        "project_id": project_id,
        "parent_task_id": metadata.get("parent_task_id"),
        "agent_name": AGENT_NAME,
    }}

    if resume_text is not None:
        agent_input = Command(resume=resume_text)
    else:
        agent_input = {"messages": [("user", text)]}

    result = await _agent.ainvoke(agent_input, config=config)

    # Cross-cutting: memory persistence
    if _store is not None:
        await handle_memory_actions(
            _store, result["messages"], user_id=user_id, project_id=project_id,
        )

    if "__interrupt__" in result:
        iv = result["__interrupt__"]
        interrupt_text = str(iv[0].value) if iv else "Input required"
        return TurnResult(response_text=interrupt_text, messages=result["messages"], interrupt_text=interrupt_text)

    content = result["messages"][-1].content
    response_text = _flatten_message_content(content)
    return TurnResult(response_text=response_text, messages=result["messages"])
```

```python
async def process_turn_streaming(
    text: str,
    metadata: dict,
    *,
    resume_text: str | None = None,
    task_id: str | None = None,
):
    """Stream agent turn events. Used by all streaming protocol paths."""
    config = ...  # same as process_turn
    agent_input = ...

    accumulated: list[str] = []
    tool_msgs: list = []
    async for event in _agent.astream_events(agent_input, config=config, version="v2"):
        if "__interrupt__" in event:
            iv = event["__interrupt__"]
            yield TurnEvent(type="interrupt", text=str(iv[0].value) if iv else "Input required", final=True)
            return
        ev_kind = event.get("event")
        if ev_kind == "on_chat_model_stream":
            token = event["data"]["chunk"].content
            if token:
                accumulated.append(token)
                yield TurnEvent(type="token", text=token)
        elif ev_kind == "on_tool_end":
            # Capture for memory-action processing
            tm = event["data"].get("output")
            if tm is not None:
                tool_msgs.append(tm)

    # Cross-cutting: memory persistence (after stream completes)
    if _store is not None and tool_msgs:
        await handle_memory_actions(
            _store, tool_msgs,
            user_id=metadata.get("user_id"),
            project_id=metadata.get("project_id"),
        )

    yield TurnEvent(type="final", text="".join(accumulated), final=True)
```

`_flatten_message_content` is a small helper (already inlined six times
today; this lifts it to one place):

```python
def _flatten_message_content(content) -> str:
    if isinstance(content, list):
        return "".join(
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in content
        )
    return str(content)
```

## Protocol layer shape (after refactor)

Example: `_a2a_one_shot` becomes ~15 lines of shape translation:

```python
async def _a2a_one_shot(message: A2AMessage, metadata: dict) -> str:
    task_id = message.correlation_id or str(uuid.uuid4())
    text = " ".join(p.get("text", "") for p in message.parts if "text" in p)

    existing = _task_manager.get_task(task_id) or _task_manager.create_task(
        task_id, {"role": message.role, "parts": message.parts},
    )
    _task_manager.update_task(task_id, "working")

    resume_text = text if existing and existing["status"]["state"] == "input_required" else None

    try:
        result = await process_turn(text, metadata, resume_text=resume_text, task_id=task_id)
    except Exception as exc:
        _task_manager.update_task(task_id, "failed", str(exc))
        raise

    if result.interrupt_text:
        _task_manager.update_task(task_id, "input_required", result.interrupt_text)
    else:
        _task_manager.update_task(task_id, "completed", result.response_text)
    return result.response_text
```

`chat_completions`, `create_response`, `_a2a_streaming`,
`_stream_chat_completions`, `_run_background` collapse the same way.

## Implementation strategy

Build the cores first, migrate one protocol layer at a time, then
delete the duplicated code.

### Phase 1 — Add cores alongside existing duplicated code

- `vystak-adapter-langchain/templates.py`: emit `process_turn`,
  `process_turn_streaming`, `TurnResult`, `TurnEvent`,
  `_flatten_message_content` into `server.py`. Existing protocol
  layers keep their inline implementations untouched.
- Goal: cores compile, are emitted in every generated `server.py`,
  but nothing calls them yet. Tests still pass. Generated server is a
  little larger.

### Phase 2 — Migrate `_a2a_one_shot` to use `process_turn`

- `vystak-adapter-langchain/a2a.py`: rewrite the `_a2a_one_shot`
  emitter to produce the ~15-line shape-translator above. Drop the
  inlined `_agent.ainvoke` + memory + content-extraction.
- Verify: snapshot tests against generated `server.py` show the new
  shape; existing functional tests in
  `examples/docker-slack-multi-agent` still work; live save_memory
  round-trip still persists (regression of the 2026-04-26 fix).

### Phase 3 — Migrate the other one-shot paths

- `chat_completions` (in `templates.py`)
- `create_response` (in `responses.py`)
- Both shrink to shape-translators.

### Phase 4 — Migrate the streaming paths to `process_turn_streaming`

- `_a2a_streaming` (in `a2a.py`) — currently no memory handling.
  Migration **also fixes** the still-broken streaming memory bug.
- `_stream_chat_completions` (in `templates.py`)
- `_run_background` (in `responses.py`)

Each of these emits a small wrapper that consumes `TurnEvent` and
formats it into the protocol's wire shape (SSE for OpenAI, A2A
streaming events, etc.).

### Phase 5 — Delete dead code

- Remove the now-unused inline `ainvoke`/`astream_events` blocks from
  `templates.py`/`responses.py`/`a2a.py`. Update generator helper
  functions and snapshot tests accordingly.
- Goal: searching the templates package for `_agent.ainvoke` returns
  exactly **one** match (inside `process_turn`); same for
  `astream_events` and `handle_memory_actions`.

Each phase is one commit, each commit keeps the generated `server.py`
working end-to-end.

## Test strategy

The adapter's existing tests are template-content assertions
(`assert "..." in SERVER_PY`) and a few snapshot tests. Three
extensions:

1. **Snapshot tests on the cores.** Add a fixture-driven test that
   renders an agent's `server.py` and asserts both `process_turn` and
   `process_turn_streaming` are present with the expected interfaces.
   Add the `TurnResult` and `TurnEvent` dataclass declarations to the
   asserted strings.

2. **Per-protocol shape tests.** For each protocol layer
   (`_a2a_one_shot`, `chat_completions`, `create_response`,
   `_a2a_streaming`, `_stream_chat_completions`, `_run_background`),
   assert the emitted code now `await process_turn(` (or
   `process_turn_streaming`) and **does not** contain `_agent.ainvoke`
   directly. This is the structural guarantee that the duplication
   collapsed.

3. **End-to-end memory regression.** Add a release-tier test (gated
   like the existing `release_live_chat`) that:
   - Deploys an agent with `sessions: sqlite` and an instruction to
     save the user's name.
   - Sends a save-trigger message via A2A streaming (currently
     untested path).
   - Asserts a row appears in the agent's sessions store.
   - Tears down.

   Single fixture, exercises the streaming memory fix that lands in
   Phase 4.

Existing tests must keep passing through every phase.

## Acceptance criteria

1. **Single core.** A grep for `_agent.ainvoke` inside
   `vystak-adapter-langchain/src/` returns exactly one match (in the
   emitter for `process_turn`). Same for `_agent.astream_events`.
2. **No path-specific memory handling.** `handle_memory_actions` is
   referenced exactly twice in the templates package — once in
   `process_turn`, once in `process_turn_streaming`. Today's value: 6.
3. **Streaming memory works.** A `save_memory` call made through the
   A2A streaming path persists to the agent's store. (Today: silently
   dropped.)
4. **Regression-free.** All existing tests in
   `vystak-adapter-langchain/tests/` plus the
   `examples/docker-slack-multi-agent/` live deploy continue to work.
   Memory round-trip via Slack (the 2026-04-26 fix) still persists.
5. **Smaller generated `server.py`.** Net line count goes down (six
   inlined post-processing blocks → two helpers + six small
   translators). Specifically: `len(SERVER_PY)` after the refactor is
   smaller than before for an agent with a representative shape
   (sessions + memory + 2 subagents + 1 channel).

## Out of scope (future work, but enabled by this refactor)

- **Audit logging on every turn.** One hook in `process_turn` =
  every protocol gets it.
- **Distributed tracing.** Same — one OTEL span around the core, all
  protocols inherit.
- **Rate limiting and quota.** Single enforcement point.
- **Tool-call logging.** A single `on_tool_end` handler in
  `process_turn_streaming` could log every tool invocation
  consistently.
- **Cross-protocol metrics.** Number of turns per agent, latency
  percentiles, error rates — all visible at the core.
- **Mastra adapter parity.** When `vystak-adapter-mastra` graduates
  from stub, it can adopt the same `process_turn` /
  `process_turn_streaming` shape, so the protocol layers across
  adapters look identical.

## Non-goals

- Schema changes. The agent contract (`vystak.schema.Agent`) is
  unchanged.
- Channel changes. Slack channel keeps calling A2A; the cores live
  inside the agent's generated server.
- Wire-format changes. A2A JSON-RPC, OpenAI chat-completions, and
  `/v1/responses` shapes all stay byte-compatible.
- Memory backend changes. The `_get_session_store` quirk (uses
  `agent.sessions`, not `agent.memory`) is a separate bug not fixed
  here.
- Slack-side fixes. The known channel-deploy hash bug (instructions
  changes don't trigger rebuild) is tracked separately.
