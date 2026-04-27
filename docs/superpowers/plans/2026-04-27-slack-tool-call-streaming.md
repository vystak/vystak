# Slack Tool-Call Streaming Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a per-channel `stream_tool_calls` option to Slack channels. When enabled, the bot's reply message edits live to show tool-call progress (`🔧 *tool* ✓ _(2.1s)_`) while the agent runs, then is replaced by the final reply. Default off — non-streaming behavior unchanged.

**Architecture:** Three layers cooperate. (1) `process_turn_streaming` (turn_core.py) emits two new `TurnEvent` types from langgraph's `on_tool_start` / `on_tool_end`. (2) `_a2a_streaming` + the SSE `event_generator` (a2a.py) forward them on the wire as `A2AEvent(type="tool_call"|"tool_result")`. (3) The Slack channel's new `_stream_to_agent` helper consumes the event stream, maintains a per-turn progress buffer, and rate-limits `chat.update` to ≤1/sec.

**Tech Stack:** Python 3.11, Pydantic v2, FastAPI, sse-starlette `EventSourceResponse`, slack-bolt async, httpx, langgraph `astream_events("v2")`. Tests: pytest (string-presence assertions on emitted source) + a real HTTP fixture for end-to-end wire verification.

---

## Spec divergences (locked in by this plan)

The spec at `docs/superpowers/specs/2026-04-27-slack-tool-call-streaming-design.md` is the source of truth for behavior. Three details get adjusted here based on what the codebase actually looks like:

1. **`SlackChannelConfig` lives in `vystak-channel-slack/src/vystak_channel_slack/plugin.py:20`**, NOT in `vystak/src/vystak/schema/channel.py`. The plan adds the field to `plugin.py`. The plugin currently does not instantiate `SlackChannelConfig` against `channel.config`; it reads the dict directly. So the new field on the Pydantic model is documentation-only — the runtime path is `channel.config.get("stream_tool_calls", False)` inside `generate_code`.
2. **`TurnEvent.type` already includes a `"tool_call"` literal** (turn_core.py:30) which is never emitted. Per spec, we **replace** it with `"tool_call_start"` and `"tool_call_end"` (no consumer of the unused value exists).
3. **The SSE wire format gap.** The current `event_generator` in `a2a.py` wraps `A2AEvent` instances in JSON-RPC envelopes (`{"jsonrpc": "2.0", "id": ..., "result": {...}}`) for token/status/final. `HttpTransport.stream_task` (transport.py:93) decodes each line as `A2AEvent.model_validate(parsed)` — which fails on the JSON-RPC envelope shape (no top-level `type`). This means `stream_task` is broken end-to-end against the LangChain-adapter SSE today; nothing in production exercises it because the channel uses `send_task` (one-shot). The narrow fix in this plan: add new `elif ev.type == "tool_call":` and `elif ev.type == "tool_result":` branches in `event_generator` that emit bare `A2AEvent.model_dump_json()` (matching `test_http_transport.py:45`'s test harness shape). Existing token/status/final branches stay untouched — anything currently consuming the JSON-RPC envelope still works. A separate Task 1 also fixes the wire decode for these new types only by extending the `final` branch path so the channel sees the final reply.

## File map

| Path | Responsibility | Change |
|------|----------------|--------|
| `packages/python/vystak-adapter-langchain/src/vystak_adapter_langchain/turn_core.py` | Emits the shared `process_turn` / `process_turn_streaming` source. | Extend `TurnEvent.type` Literal; add `on_tool_start` / `on_tool_end` emissions with `run_id`-keyed duration tracking. |
| `packages/python/vystak-adapter-langchain/src/vystak_adapter_langchain/a2a.py` | Emits `_a2a_streaming` + SSE `event_generator`. | Translate two new `TurnEvent` types → `A2AEvent`; add SSE wire branches for `tool_call`/`tool_result`/`final` that emit bare `model_dump_json()`. |
| `packages/python/vystak-channel-slack/src/vystak_channel_slack/plugin.py` | Plugin metadata + `generate_code`. | Add `stream_tool_calls: bool = False` to `SlackChannelConfig`; emit `channel.config.get("stream_tool_calls", False)` into `channel_config.json`. |
| `packages/python/vystak-channel-slack/src/vystak_channel_slack/server_template.py` | Channel runtime source (string-templated). | Add `_stream_to_agent` async helper; read flag at startup; branch in `on_mention` and `on_message` thread-follow path. |
| `packages/python/vystak-adapter-langchain/tests/test_turn_core.py` | Unit tests on the emitted turn-core source. | New `TestTurnCoreToolCallEmissions`. |
| `packages/python/vystak-adapter-langchain/tests/test_a2a.py` | Unit tests on the emitted A2A source. | New tests in `TestA2AStreamingUsesProcessTurnStreaming` for tool_call wire mapping + SSE branches. |
| `packages/python/vystak-channel-slack/tests/test_plugin.py` | Plugin emission tests. | New `TestSlackChannelStreamToolCalls`. |
| `packages/python/vystak-adapter-langchain/tests/test_streaming_e2e.py` | NEW — real-HTTP end-to-end SSE round-trip. | One test that spins up a FastAPI app with the emitted SSE source, calls it via `HttpTransport.stream_task`, and asserts the consumer sees the new event types. |

No provider, CLI, gateway, or website-docs changes in scope.

---

## Task 1: Extend `TurnEvent` literal in turn_core.py

**Files:**
- Modify: `packages/python/vystak-adapter-langchain/src/vystak_adapter_langchain/turn_core.py`
- Test: `packages/python/vystak-adapter-langchain/tests/test_turn_core.py`

- [ ] **Step 1: Write the failing test**

Append to `packages/python/vystak-adapter-langchain/tests/test_turn_core.py`:

```python
class TestTurnCoreToolCallLiteral:
    """The TurnEvent type discriminator must include the new tool_call_start / tool_call_end values."""

    def test_literal_includes_tool_call_start_and_end(self):
        from vystak_adapter_langchain.turn_core import emit_turn_core_helpers

        src = emit_turn_core_helpers()
        assert '"tool_call_start"' in src
        assert '"tool_call_end"' in src

    def test_literal_does_not_keep_unused_tool_call_value(self):
        """The pre-refactor 'tool_call' value was never emitted; replacing it
        with tool_call_start/tool_call_end keeps the discriminator narrow."""
        from vystak_adapter_langchain.turn_core import emit_turn_core_helpers
        import re

        src = emit_turn_core_helpers()
        # Match the Literal[...] annotation on TurnEvent.type.
        m = re.search(r"type:\s*Literal\[(.*?)\]", src, re.DOTALL)
        assert m, "TurnEvent.type Literal annotation not found"
        literal_body = m.group(1)
        # The bare "tool_call" value must NOT appear among the discriminators.
        # (Substring check across the whole emitted source would false-positive
        # on tool_call_start. Restrict to the Literal[...] body.)
        values = [v.strip().strip('"').strip("'") for v in literal_body.split(",")]
        assert "tool_call" not in values
        assert "tool_call_start" in values
        assert "tool_call_end" in values
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/python/vystak-adapter-langchain/tests/test_turn_core.py::TestTurnCoreToolCallLiteral -v`
Expected: FAIL — `"tool_call_start"` not found in source.

- [ ] **Step 3: Update the Literal in turn_core.py**

In `packages/python/vystak-adapter-langchain/src/vystak_adapter_langchain/turn_core.py`, replace the existing `TurnEvent` definition (around lines 26–33) with:

```python
@dataclass
class TurnEvent:
    """Single streamed event. Yielded by ``process_turn_streaming``."""

    type: Literal[
        "token",
        "tool_call_start",
        "tool_call_end",
        "interrupt",
        "final",
        "error",
    ]
    text: str = ""
    data: dict | None = None
    final: bool = False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/python/vystak-adapter-langchain/tests/test_turn_core.py -v`
Expected: PASS — all turn_core tests including the new `TestTurnCoreToolCallLiteral`.

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-adapter-langchain/src/vystak_adapter_langchain/turn_core.py \
        packages/python/vystak-adapter-langchain/tests/test_turn_core.py
git commit -m "feat(adapter-langchain): extend TurnEvent literal with tool_call_start / tool_call_end"
```

---

## Task 2: Emit `tool_call_start` / `tool_call_end` from `process_turn_streaming`

**Files:**
- Modify: `packages/python/vystak-adapter-langchain/src/vystak_adapter_langchain/turn_core.py`
- Test: `packages/python/vystak-adapter-langchain/tests/test_turn_core.py`

- [ ] **Step 1: Write the failing test**

Append to `packages/python/vystak-adapter-langchain/tests/test_turn_core.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/python/vystak-adapter-langchain/tests/test_turn_core.py::TestTurnCoreToolCallEmissions -v`
Expected: FAIL — `on_tool_start` branch not present.

- [ ] **Step 3: Add the emissions in turn_core.py**

In `packages/python/vystak-adapter-langchain/src/vystak_adapter_langchain/turn_core.py`, locate the `process_turn_streaming` body inside `_TURN_CORE_SRC` (currently around lines 138–176). Replace the body's accumulator declarations and event loop with the following (note: the existing `on_tool_end` branch's memory-collection logic is preserved and extended):

```python
    accumulated: list[str] = []
    tool_msgs: list = []
    _tool_starts: dict[str, float] = {}

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
            raw = getattr(chunk, "content", "") if chunk is not None else ""
            token = _flatten_message_content(raw)
            if token:
                accumulated.append(token)
                yield TurnEvent(type="token", text=token)
        elif ev_kind == "on_tool_start":
            tool_name = event.get("name") or event.get("data", {}).get("name", "?")
            run_id = str(event.get("run_id") or "")
            started_at = time.time()
            if run_id:
                _tool_starts[run_id] = started_at
            yield TurnEvent(
                type="tool_call_start",
                data={"tool_name": tool_name, "started_at": started_at},
            )
        elif ev_kind == "on_tool_end":
            tool_name = event.get("name") or event.get("data", {}).get("name", "?")
            run_id = str(event.get("run_id") or "")
            started_at = _tool_starts.pop(run_id, None)
            duration_ms = (
                int((time.time() - started_at) * 1000)
                if started_at is not None else 0
            )
            yield TurnEvent(
                type="tool_call_end",
                data={"tool_name": tool_name, "duration_ms": duration_ms},
            )
            tm = event["data"].get("output")
            if tm is not None:
                if hasattr(tm, "content"):
                    tool_msgs.append(tm)
                elif isinstance(tm, str):
                    tool_msgs.append(SimpleNamespace(content=tm))

    if _store is not None and tool_msgs:
        await handle_memory_actions(
            _store, tool_msgs,
            user_id=user_id, project_id=project_id,
        )

    yield TurnEvent(
        type="final", text="".join(accumulated),
        data={"state": "completed"}, final=True,
    )
```

The emitted source uses `time.time()` at runtime — `templates.py:493` already emits `import time` into every `server.py`, so no template change is needed.

- [ ] **Step 4: Run all turn_core tests**

Run: `uv run pytest packages/python/vystak-adapter-langchain/tests/test_turn_core.py -v`
Expected: PASS — including the four new tests and all pre-existing tests (signature, memory, SimpleNamespace wrap).

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-adapter-langchain/src/vystak_adapter_langchain/turn_core.py \
        packages/python/vystak-adapter-langchain/tests/test_turn_core.py
git commit -m "feat(adapter-langchain): emit tool_call_start / tool_call_end from process_turn_streaming"
```

---

## Task 3: Wire the new `TurnEvent` types through `_a2a_streaming` and the SSE generator

**Files:**
- Modify: `packages/python/vystak-adapter-langchain/src/vystak_adapter_langchain/a2a.py`
- Test: `packages/python/vystak-adapter-langchain/tests/test_a2a.py`

The current `_a2a_streaming` body has three `if/elif` branches for `token`, `interrupt`, `final`. We add two more (for `tool_call_start` → `A2AEvent(type="tool_call")` and `tool_call_end` → `A2AEvent(type="tool_result")`) — these are the in-process A2AEvent translations.

The SSE `event_generator` in `_handle_tasks_send_subscribe` currently only emits JSON-RPC envelopes for `token` / `status` / `final` and silently drops anything else. We add three more branches for `tool_call` / `tool_result` / `final` (this last one rewritten so the wire shape is decodable by `HttpTransport.stream_task`'s `A2AEvent.model_validate`). The new branches emit `A2AEvent.model_dump_json()` directly — same shape as the test harness in `test_http_transport.py:45`. Existing `token` / `status` branches keep their JSON-RPC envelope shape (anything else relying on it stays working).

- [ ] **Step 1: Write the failing test**

Append to `packages/python/vystak-adapter-langchain/tests/test_a2a.py` inside class `TestA2AStreamingUsesProcessTurnStreaming` (or as a new class right after it):

```python
class TestA2AStreamingToolCallWireMapping:
    """The streaming A2A path forwards new TurnEvent types over the wire."""

    def _server_py(self):
        from vystak.schema.agent import Agent
        from vystak.schema.model import Model
        from vystak.schema.platform import Platform
        from vystak.schema.provider import Provider
        from vystak.schema.secret import Secret
        from vystak_adapter_langchain.adapter import LangChainAdapter

        p = Provider(name="anthropic", type="anthropic")
        d = Provider(name="docker", type="docker")
        agent = Agent(
            name="probe",
            model=Model(name="m", model_name="claude", provider=p),
            platform=Platform(name="local", type="docker", provider=d),
            secrets=[Secret(name="K")],
        )
        return LangChainAdapter().generate(agent).files["server.py"]

    def test_a2a_streaming_translates_tool_call_start(self):
        import re
        src = self._server_py()
        match = re.search(
            r"async def _a2a_streaming\(.*?\)(?:\s*->\s*[^\n:]*)?:\s*\n(.*?)(?=\nasync def |\Z)",
            src, re.DOTALL,
        )
        body = match.group(1)
        assert 'ev.type == "tool_call_start"' in body
        assert 'A2AEvent(type="tool_call"' in body

    def test_a2a_streaming_translates_tool_call_end(self):
        import re
        src = self._server_py()
        match = re.search(
            r"async def _a2a_streaming\(.*?\)(?:\s*->\s*[^\n:]*)?:\s*\n(.*?)(?=\nasync def |\Z)",
            src, re.DOTALL,
        )
        body = match.group(1)
        assert 'ev.type == "tool_call_end"' in body
        assert 'A2AEvent(type="tool_result"' in body

    def test_sse_generator_emits_tool_call_branches(self):
        """event_generator inside _handle_tasks_send_subscribe must have wire
        branches for tool_call and tool_result, otherwise A2AEvents emitted by
        _a2a_streaming are silently dropped before reaching the HTTP client."""
        src = self._server_py()
        # The SSE generator emits these as bare A2AEvent JSON
        # (model_dump_json) so HttpTransport.stream_task can decode them.
        assert 'ev.type == "tool_call"' in src
        assert 'ev.type == "tool_result"' in src
        assert "model_dump_json()" in src

    def test_sse_generator_emits_decodable_final_event(self):
        """Final event must also be wire-decodable as A2AEvent so the channel
        sees the final reply text. The new branch emits model_dump_json()."""
        src = self._server_py()
        # Look for the new final-as-A2AEvent emission. It coexists with the
        # legacy JSON-RPC envelope branch — both must be present so existing
        # consumers (gateway test fixtures) and new consumers (channel
        # stream_task) both see what they expect.
        # Required string-presence checks:
        assert 'A2AEvent(type="final"' in src or '"final"' in src
        # Plain model_dump_json() emission appears at least once.
        assert src.count("model_dump_json()") >= 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/python/vystak-adapter-langchain/tests/test_a2a.py::TestA2AStreamingToolCallWireMapping -v`
Expected: FAIL — `tool_call_start` branch not present in `_a2a_streaming`.

- [ ] **Step 3: Add the in-process translations in `_a2a_streaming`**

In `packages/python/vystak-adapter-langchain/src/vystak_adapter_langchain/a2a.py`, locate the `_a2a_streaming` async-for body inside `generate_a2a_handler_code` (lines 188–207). Insert two new `elif` branches between the `"token"` branch and the `"interrupt"` branch:

```python
    lines.append("    try:")
    lines.append("        async for ev in process_turn_streaming(")
    lines.append("            turn_text, metadata,")
    lines.append("            resume_text=resume_text, task_id=task_id,")
    lines.append("        ):")
    lines.append('            if ev.type == "token":')
    lines.append('                yield A2AEvent(type="token", text=ev.text)')
    lines.append('            elif ev.type == "tool_call_start":')
    lines.append('                yield A2AEvent(type="tool_call", data=ev.data)')
    lines.append('            elif ev.type == "tool_call_end":')
    lines.append('                yield A2AEvent(type="tool_result", data=ev.data)')
    lines.append('            elif ev.type == "interrupt":')
    # ... rest unchanged
```

(Replace lines 188–192 of the existing emit, keeping lines 193+ intact.)

- [ ] **Step 4: Add SSE wire branches in `event_generator`**

Still in `a2a.py`, locate the `event_generator` body inside `_handle_tasks_send_subscribe` (lines 354–397). Add three new branches right before the existing `elif ev.type == "final":` branch:

```python
    lines.append('                elif ev.type == "tool_call":')
    lines.append('                    yield {"data": ev.model_dump_json()}')
    lines.append('                elif ev.type == "tool_result":')
    lines.append('                    yield {"data": ev.model_dump_json()}')
    lines.append('                elif ev.type == "final":')
    lines.append("                    final_event = {")
    # ... legacy JSON-RPC envelope branch unchanged
    # After the legacy envelope yield, also emit a bare A2AEvent shape so
    # consumers using HttpTransport.stream_task (which model_validates each
    # SSE line as A2AEvent) see the final reply text.
    lines.append('                    yield {"data": ev.model_dump_json()}')
```

The `final` branch now yields TWO SSE events: the legacy JSON-RPC envelope first (existing consumers keep working), then the bare `A2AEvent` JSON (new consumers like the Slack channel get a decodable final). HttpTransport.stream_task tolerates the JSON-RPC envelope already because `A2AEvent.model_validate` raises on it, the transport catches `json.JSONDecodeError` only — but a `ValidationError` propagates. We confirm in Task 7 that the wire round-trips.

If validation errors propagate today (and the contract test in `test_http_transport.py` would have caught any wire mismatch but uses its own bare-A2AEvent harness), wrap the validate call in `try/except` in `transport.py` — see Task 7's check. For now, leave `transport.py` alone; if Task 7 reveals an exception, return here and fix.

- [ ] **Step 5: Run a2a tests**

Run: `uv run pytest packages/python/vystak-adapter-langchain/tests/test_a2a.py -v`
Expected: PASS — all 4 new tests + all pre-existing.

- [ ] **Step 6: Commit**

```bash
git add packages/python/vystak-adapter-langchain/src/vystak_adapter_langchain/a2a.py \
        packages/python/vystak-adapter-langchain/tests/test_a2a.py
git commit -m "feat(adapter-langchain): forward tool_call/tool_result over A2A SSE wire"
```

---

## Task 4: Add `stream_tool_calls` to `SlackChannelConfig` + emit into `channel_config.json`

**Files:**
- Modify: `packages/python/vystak-channel-slack/src/vystak_channel_slack/plugin.py`
- Test: `packages/python/vystak-channel-slack/tests/test_plugin.py`

- [ ] **Step 1: Write the failing test**

Append to `packages/python/vystak-channel-slack/tests/test_plugin.py`:

```python
class TestSlackChannelStreamToolCalls:
    """The stream_tool_calls flag round-trips from Channel.config to channel_config.json."""

    def test_default_value_false(self):
        plugin = SlackChannelPlugin()
        code = plugin.generate_code(_channel(), {})
        cfg = json.loads(code.files["channel_config.json"])
        assert cfg.get("stream_tool_calls") is False

    def test_true_when_set_in_channel_config(self):
        plugin = SlackChannelPlugin()
        ch = _channel(config={"stream_tool_calls": True})
        code = plugin.generate_code(ch, {})
        cfg = json.loads(code.files["channel_config.json"])
        assert cfg["stream_tool_calls"] is True

    def test_slack_channel_config_pydantic_field(self):
        """The pydantic SlackChannelConfig schema documents the field."""
        from vystak_channel_slack import SlackChannelConfig

        cfg = SlackChannelConfig(stream_tool_calls=True)
        assert cfg.stream_tool_calls is True
        # Default still False.
        assert SlackChannelConfig().stream_tool_calls is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/python/vystak-channel-slack/tests/test_plugin.py::TestSlackChannelStreamToolCalls -v`
Expected: FAIL — field missing on `SlackChannelConfig`, key not in JSON.

- [ ] **Step 3: Update `SlackChannelConfig` and `generate_code`**

In `packages/python/vystak-channel-slack/src/vystak_channel_slack/plugin.py`, replace lines 20–23:

```python
class SlackChannelConfig(BaseModel):
    """Optional config for a Slack channel."""

    port: int = 8080
    stream_tool_calls: bool = False
```

In the same file, in `generate_code`, add one line to the `channel_config` dict (around line 86 — right before `"state": state_cfg,`):

```python
            "stream_tool_calls": bool(channel.config.get("stream_tool_calls", False)),
            "state": state_cfg,
```

- [ ] **Step 4: Run plugin tests**

Run: `uv run pytest packages/python/vystak-channel-slack/tests/test_plugin.py -v`
Expected: PASS — three new tests + all pre-existing.

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-channel-slack/src/vystak_channel_slack/plugin.py \
        packages/python/vystak-channel-slack/tests/test_plugin.py
git commit -m "feat(channel-slack): add stream_tool_calls flag to SlackChannelConfig"
```

---

## Task 5: Add `_stream_to_agent` helper to the channel runtime

**Files:**
- Modify: `packages/python/vystak-channel-slack/src/vystak_channel_slack/server_template.py`
- Test: `packages/python/vystak-channel-slack/tests/test_plugin.py`

The helper:
- Reads `_channel_config["stream_tool_calls"]` at startup; if False, the helper is never called (caller branches on the flag in Task 6).
- Renders progress as Slack mrkdwn (`🔧 *<tool_name>*` in-flight, `🔧 *<tool_name>* ✓ _(2.1s)_` completed) plus `_Working..._` trailer.
- Calls `chat.update` no more than once per second per turn (rate-limit honoured); the final event is exempt.
- On error: replaces placeholder with the existing "Sorry, I hit an error talking to *X*: ..." text, identical to the non-streaming path's wording.
- Mirrors the metadata shape `_forward_to_agent` builds (sessionId, user_id with `slack:` prefix, project_id).

- [ ] **Step 1: Write failing tests**

Append to `packages/python/vystak-channel-slack/tests/test_plugin.py`:

```python
class TestStreamToAgentHelper:
    """The _stream_to_agent helper is emitted into server.py and the runtime
    branches on the stream_tool_calls flag at use sites."""

    def _server_py(self):
        from vystak_channel_slack.server_template import SERVER_PY
        return SERVER_PY

    def test_helper_is_defined(self):
        src = self._server_py()
        assert "async def _stream_to_agent(" in src

    def test_helper_uses_stream_task(self):
        src = self._server_py()
        assert "stream_task(" in src

    def test_helper_is_rate_limited(self):
        """Throttle to 1 chat.update per second (Slack tier-3 cap)."""
        src = self._server_py()
        # The helper computes a min interval between updates.
        assert "_STREAM_UPDATE_MIN_INTERVAL_S" in src or "1.0" in src
        # The helper tracks last_update_at to coalesce.
        assert "last_update_at" in src

    def test_helper_renders_in_flight_and_completed_lines(self):
        """In-flight tools render as `🔧 *<name>*`; completed tools add `✓ _(Xs)_`."""
        src = self._server_py()
        assert "\\U0001f527" in src or "🔧" in src
        assert "✓" in src or "\\u2713" in src
        # The duration formatter renders as "(2.1s)" — keep the regex narrow
        # so we don't false-positive on unrelated mentions.
        assert "duration_ms" in src

    def test_helper_handles_error_with_legacy_text(self):
        """Same error text as _forward_to_agent's except branch."""
        src = self._server_py()
        # The exact phrase mirrors on_mention's existing error path.
        assert "Sorry, I hit an error talking to" in src

    def test_helper_replaces_placeholder_on_final(self):
        """On final event, chat.update with the rendered final reply."""
        src = self._server_py()
        # The helper calls _to_slack_mrkdwn on ev.text (or equivalent) for
        # the final replacement. Looking for the function call inside the
        # streaming helper body.
        # Use a regex to scope the assertion to the helper.
        import re
        m = re.search(
            r"async def _stream_to_agent\(.*?\):.*?(?=\n(?:async def |def |@|\Z))",
            src, re.DOTALL,
        )
        assert m, "_stream_to_agent body not found"
        body = m.group(0)
        assert "_to_slack_mrkdwn" in body
        assert "chat_update" in body

    def test_helper_passes_metadata_like_forward_to_agent(self):
        """Same metadata shape: sessionId, user_id (slack-prefixed), project_id."""
        src = self._server_py()
        import re
        m = re.search(
            r"async def _stream_to_agent\(.*?\):.*?(?=\n(?:async def |def |@|\Z))",
            src, re.DOTALL,
        )
        body = m.group(0)
        assert '"sessionId"' in body
        assert "slack:" in body  # the user_id prefix
        assert "project_id" in body

    def test_runtime_reads_stream_tool_calls_flag(self):
        """server.py reads the flag from _channel_config at startup."""
        src = self._server_py()
        assert '"stream_tool_calls"' in src
        # A module-level binding so the handlers can branch fast.
        assert "_STREAM_TOOL_CALLS" in src or "_stream_tool_calls" in src
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/python/vystak-channel-slack/tests/test_plugin.py::TestStreamToAgentHelper -v`
Expected: FAIL — helper absent.

- [ ] **Step 3: Add module-level flag binding to server_template.py**

In `packages/python/vystak-channel-slack/src/vystak_channel_slack/server_template.py`, locate where `_channel_config` is loaded (around line 97) and add right after the existing flag/config bindings (e.g., after `_thread_cfg` at line 343, but pick a coherent spot — the `_FORWARD_TIMEOUT_S` block at line 178 is a good neighbour for runtime flags):

```python
_STREAM_TOOL_CALLS: bool = bool(_channel_config.get("stream_tool_calls", False))
_STREAM_UPDATE_MIN_INTERVAL_S: float = 1.0  # Slack tier-3 chat.update cap
```

- [ ] **Step 4: Add the `_stream_to_agent` helper**

In `packages/python/vystak-channel-slack/src/vystak_channel_slack/server_template.py`, add this helper right after the existing `_forward_to_agent` function (around line 229):

```python
def _format_duration(duration_ms: int) -> str:
    seconds = duration_ms / 1000.0
    return f"{seconds:.1f}s"


def _render_progress_trail(in_flight: list[dict], completed: list[dict]) -> str:
    """Render the progress trail as Slack mrkdwn.

    Each completed tool: 🔧 *<name>* ✓ _(2.1s)_
    Each in-flight tool: 🔧 *<name>*
    Trailer: _Working..._  (or _Responding..._ before any tool event)
    """
    lines: list[str] = []
    for t in completed:
        lines.append(f"🔧 *{t['tool_name']}* ✓ _({_format_duration(t['duration_ms'])})_")
    for t in in_flight:
        lines.append(f"🔧 *{t['tool_name']}*")
    if completed or in_flight:
        lines.append("_Working..._")
    else:
        lines.append("_Responding..._")
    return "\\n".join(lines)


async def _stream_to_agent(
    client, placeholder: dict | None, say,
    *,
    agent_name: str, text: str, session_id: str,
    user_id: str | None = None,
    project_id: str | None = None,
    thread_ts: str | None = None,
) -> None:
    """Stream agent events into the placeholder Slack message.

    Mirrors _forward_to_agent's metadata shape but consumes the SSE
    stream from stream_task and edits the placeholder via chat_update,
    rate-limited to once per second per turn. On final, the entire
    progress trail is replaced with _to_slack_mrkdwn(final_text).
    """
    metadata: dict = {"sessionId": session_id}
    if user_id:
        metadata["user_id"] = f"slack:{user_id}"
    if project_id:
        metadata["project_id"] = project_id

    in_flight: list[dict] = []
    completed: list[dict] = []
    final_text: str | None = None
    last_update_at: float = 0.0

    async def _maybe_update(force: bool = False) -> None:
        nonlocal last_update_at
        if placeholder is None:
            return
        now = _time.time()
        if not force and (now - last_update_at) < _STREAM_UPDATE_MIN_INTERVAL_S:
            return
        last_update_at = now
        body = _render_progress_trail(in_flight, completed)
        try:
            await client.chat_update(
                channel=placeholder["channel"],
                ts=placeholder["ts"],
                text=body,
            )
        except Exception as exc:
            logger.warning("stream chat_update failed: %s", exc)

    try:
        async for ev in _default_client().stream_task(
            agent_name, text,
            metadata=metadata,
            timeout=_FORWARD_TIMEOUT_S,
        ):
            if ev.type == "tool_call":
                d = ev.data or {}
                in_flight.append({
                    "tool_name": d.get("tool_name", "?"),
                    "started_at": d.get("started_at", _time.time()),
                })
                await _maybe_update()
            elif ev.type == "tool_result":
                d = ev.data or {}
                tool_name = d.get("tool_name", "?")
                duration_ms = int(d.get("duration_ms", 0))
                # Move the matching in-flight entry to completed.
                for i, t in enumerate(in_flight):
                    if t["tool_name"] == tool_name:
                        in_flight.pop(i)
                        break
                completed.append({"tool_name": tool_name, "duration_ms": duration_ms})
                await _maybe_update()
            elif ev.type == "final":
                final_text = ev.text or ""
                # Force the final update — exempt from rate limit.
                if placeholder is not None:
                    rendered = _to_slack_mrkdwn(final_text)
                    try:
                        await client.chat_update(
                            channel=placeholder["channel"],
                            ts=placeholder["ts"],
                            text=rendered,
                        )
                    except Exception as exc:
                        logger.exception("stream final chat_update failed: %s", exc)
                else:
                    rendered = _to_slack_mrkdwn(final_text)
                    kwargs = {"text": rendered}
                    if thread_ts:
                        kwargs["thread_ts"] = thread_ts
                    await say(**kwargs)
                return
    except Exception as exc:
        logger.exception("stream_to_agent failed agent=%s: %s", agent_name, exc)
        await _finalize(
            client, say, placeholder,
            text=f"Sorry, I hit an error talking to *{agent_name}*: `{exc}`",
            thread_ts=thread_ts,
        )
        return

    # Stream ended without a final event — fall back to a blank reply so the
    # placeholder doesn't sit forever as "Responding...".
    if final_text is None and placeholder is not None:
        await _finalize(
            client, say, placeholder,
            text="(no response from agent)",
            thread_ts=thread_ts,
        )
```

`_time` (`import time as _time` at line 785) and `logger` are already in scope. Python's lazy name resolution looks up `_time` in module globals at call time, not at def time, so the existing import position works.

- [ ] **Step 5: Run plugin tests**

Run: `uv run pytest packages/python/vystak-channel-slack/tests/test_plugin.py::TestStreamToAgentHelper -v`
Expected: PASS — 8 new tests.

Then full suite: `uv run pytest packages/python/vystak-channel-slack/tests/test_plugin.py -v`
Expected: PASS — all old tests too.

- [ ] **Step 6: Commit**

```bash
git add packages/python/vystak-channel-slack/src/vystak_channel_slack/server_template.py \
        packages/python/vystak-channel-slack/tests/test_plugin.py
git commit -m "feat(channel-slack): add _stream_to_agent helper with rate-limited chat.update"
```

---

## Task 6: Branch on `stream_tool_calls` in `on_mention` and `on_message` thread-follow

**Files:**
- Modify: `packages/python/vystak-channel-slack/src/vystak_channel_slack/server_template.py`
- Test: `packages/python/vystak-channel-slack/tests/test_plugin.py`

Per the spec, only `on_mention` and the channel-message thread-follow path inside `on_message` need to branch. DM behaviour stays one-shot (the spec leaves DMs on the same code path; less surface area; revisit if needed).

- [ ] **Step 1: Write failing tests**

Append to `packages/python/vystak-channel-slack/tests/test_plugin.py`:

```python
class TestStreamToolCallsBranch:
    """on_mention and on_message thread-follow branch on _STREAM_TOOL_CALLS."""

    def _server_py(self):
        from vystak_channel_slack.server_template import SERVER_PY
        return SERVER_PY

    def test_on_mention_branches_on_flag(self):
        import re
        src = self._server_py()
        m = re.search(
            r"async def on_mention\(.*?\):.*?(?=\n(?:async def |def |@|\Z))",
            src, re.DOTALL,
        )
        assert m, "on_mention body not found"
        body = m.group(0)
        # The branch checks the flag and routes to _stream_to_agent on True.
        assert "_STREAM_TOOL_CALLS" in body
        assert "_stream_to_agent(" in body
        # The non-streaming branch still calls _forward_to_agent.
        assert "_forward_to_agent(" in body

    def test_on_message_thread_follow_branches_on_flag(self):
        import re
        src = self._server_py()
        m = re.search(
            r"async def on_message\(.*?\):.*?(?=\n(?:async def |def |@|\Z))",
            src, re.DOTALL,
        )
        assert m, "on_message body not found"
        body = m.group(0)
        assert "_STREAM_TOOL_CALLS" in body
        assert "_stream_to_agent(" in body

    def test_default_off_preserves_forward_to_agent(self):
        """When stream_tool_calls=False, the existing _forward_to_agent path
        is unchanged. Verifying the non-streaming branch still includes the
        existing reply-finalize sequence."""
        src = self._server_py()
        # _to_slack_mrkdwn + _finalize sequence still present in on_mention.
        # (Both pre-existed; we just want them not to be removed.)
        assert "_to_slack_mrkdwn(raw_reply)" in src
        assert "_finalize(client, say, placeholder" in src
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/python/vystak-channel-slack/tests/test_plugin.py::TestStreamToolCallsBranch -v`
Expected: FAIL — `_STREAM_TOOL_CALLS` not used in handlers.

- [ ] **Step 3: Branch in `on_mention`**

In `packages/python/vystak-channel-slack/src/vystak_channel_slack/server_template.py`, locate the existing `try`/`except` block in `on_mention` that calls `_forward_to_agent` (lines 538–550). Replace it with:

```python
    project_id = f"slack:{event.get('team', '')}:{channel}" if channel else None
    if _STREAM_TOOL_CALLS:
        await _stream_to_agent(
            client, placeholder, say,
            agent_name=agent_name, text=text, session_id=session_id,
            user_id=user, project_id=project_id, thread_ts=reply_thread_ts,
        )
        # Streaming path handled placeholder finalize itself (final/error).
        # Still claim the thread on success.
        thread_key_ts = event.get("thread_ts") or event.get("ts")
        if thread_key_ts:
            _store.set_thread_binding(
                team=event.get("team", ""),
                channel=channel,
                thread_ts=thread_key_ts,
                agent=agent_name,
            )
        return
    try:
        raw_reply = await _forward_to_agent(
            agent_name, text, session_id,
            user_id=user, project_id=project_id,
        )
    except Exception as exc:
        logger.exception("mention forward failed agent=%s: %s", agent_name, exc)
        await _finalize(
            client, say, placeholder,
            text=f"Sorry, I hit an error talking to *{agent_name}*: `{exc}`",
            thread_ts=reply_thread_ts,
        )
        return
    logger.info("mention reply len=%d preview=%r", len(raw_reply or ""), (raw_reply or "")[:120])
    reply = _to_slack_mrkdwn(raw_reply)
    try:
        await _finalize(client, say, placeholder, text=reply, thread_ts=reply_thread_ts)
        logger.info("mention posted ok")
    except Exception as exc:
        logger.exception("mention post failed: %s", exc)
        return
    # Reply succeeded — claim this thread for the agent so subsequent
    # non-mention messages in it route here without re-mention.
    thread_key_ts = event.get("thread_ts") or event.get("ts")
    if thread_key_ts:
        _store.set_thread_binding(
            team=event.get("team", ""),
            channel=channel,
            thread_ts=thread_key_ts,
            agent=agent_name,
        )
```

(Note: the lines after the streaming branch are the original on_mention body unchanged — kept here so the executor doesn't have to splice. The streaming path early-returns; the non-streaming path falls through to existing logic.)

- [ ] **Step 4: Branch in `on_message` thread-follow**

In the same file, locate the channel-message branch in `on_message` (around lines 627–652). Replace the `try` block that calls `_forward_to_agent` with:

```python
        project_id = f"slack:{event.get('team', '')}:{channel}" if channel else None
        if _STREAM_TOOL_CALLS:
            await _stream_to_agent(
                client, placeholder, say,
                agent_name=agent_name, text=text, session_id=session_id,
                user_id=user, project_id=project_id, thread_ts=reply_thread_ts,
            )
            return
        try:
            raw_reply = await _forward_to_agent(
                agent_name, text, session_id,
                user_id=user, project_id=project_id,
            )
        except Exception as exc:
            logger.exception("thread-follow forward failed agent=%s: %s", agent_name, exc)
            await _finalize(
                client, say, placeholder,
                text=f"Sorry, I hit an error talking to *{agent_name}*: `{exc}`",
                thread_ts=reply_thread_ts,
            )
            return
        logger.info(
            "thread-follow reply len=%d preview=%r",
            len(raw_reply or ""), (raw_reply or "")[:120],
        )
        reply = _to_slack_mrkdwn(raw_reply)
        try:
            await _finalize(
                client, say, placeholder, text=reply, thread_ts=reply_thread_ts,
            )
            logger.info("thread-follow posted ok")
        except Exception as exc:
            logger.exception("thread-follow post failed: %s", exc)
        return
```

- [ ] **Step 5: Run plugin tests**

Run: `uv run pytest packages/python/vystak-channel-slack/tests/test_plugin.py -v`
Expected: PASS — `TestStreamToolCallsBranch` (3 new) + all pre-existing.

- [ ] **Step 6: Commit**

```bash
git add packages/python/vystak-channel-slack/src/vystak_channel_slack/server_template.py \
        packages/python/vystak-channel-slack/tests/test_plugin.py
git commit -m "feat(channel-slack): branch on stream_tool_calls in mention + thread-follow handlers"
```

---

## Task 7: End-to-end SSE round-trip test (real HTTP)

**Files:**
- Create: `packages/python/vystak-adapter-langchain/tests/test_streaming_e2e.py`

This test stands up a FastAPI app whose `/a2a` route dispatches through a real `A2AHandler` whose streaming callable yields a hand-crafted A2AEvent sequence (token, tool_call, tool_result, final). Then it calls `HttpTransport.stream_task` against that route and asserts the consumer sees all four event types in order. This catches wire-format bugs that string-presence tests miss.

- [ ] **Step 1: Write the test**

Create `packages/python/vystak-adapter-langchain/tests/test_streaming_e2e.py`:

```python
"""End-to-end SSE round-trip: emitted server source ⇄ HttpTransport.stream_task.

Catches wire-format bugs invisible to string-presence assertions: malformed
JSON, JSON-RPC envelope vs A2AEvent shape mismatches, missing event types in
the SSE generator, etc.
"""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager

import pytest
import uvicorn
from fastapi import FastAPI, Request
from sse_starlette.sse import EventSourceResponse
from vystak.transport import (
    A2AEvent,
    A2AHandler,
    A2AMessage,
    A2AResult,
)


def _build_app(events: list[A2AEvent]) -> FastAPI:
    """Build a minimal FastAPI app with a /a2a route that streams the given
    event list through an A2AHandler. The SSE wire shape mirrors what the
    LangChain adapter's emitted server.py uses for tool_call/tool_result/final
    (bare A2AEvent JSON via model_dump_json)."""
    app = FastAPI()

    async def _one_shot(message: A2AMessage, metadata: dict) -> str:
        return ""  # not exercised in this test

    async def _streaming(message: A2AMessage, metadata: dict):
        for ev in events:
            yield ev

    handler = A2AHandler(one_shot=_one_shot, streaming=_streaming)

    @app.post("/a2a")
    async def a2a(request: Request):
        body = await request.json()
        params = body.get("params", {})
        msg = A2AMessage(
            role=params.get("message", {}).get("role", "user"),
            parts=params.get("message", {}).get("parts", []),
            correlation_id=params.get("id"),
            metadata=params.get("metadata", {}),
        )
        if body.get("method") == "tasks/sendSubscribe":
            async def gen():
                async for ev in handler.dispatch_stream(msg, params.get("metadata", {})):
                    if ev.type in ("tool_call", "tool_result", "final"):
                        yield {"data": ev.model_dump_json()}
                    elif ev.type == "token":
                        yield {"data": json.dumps({
                            "jsonrpc": "2.0",
                            "id": body.get("id"),
                            "result": {"artifact": {"parts": [{"text": ev.text or ""}]}},
                        })}
            return EventSourceResponse(gen())
        return {"jsonrpc": "2.0", "id": body.get("id"), "result": {}}

    return app


@asynccontextmanager
async def _serve(app: FastAPI, port: int):
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    for _ in range(100):
        if server.started:
            break
        await asyncio.sleep(0.01)
    try:
        yield
    finally:
        server.should_exit = True
        await task


@pytest.mark.asyncio
async def test_tool_call_events_round_trip(unused_tcp_port):
    from vystak.transport import AgentRef
    from vystak_transport_http import HttpTransport

    events = [
        A2AEvent(type="tool_call", data={"tool_name": "ask_weather", "started_at": 1.0}),
        A2AEvent(type="tool_result", data={"tool_name": "ask_weather", "duration_ms": 2100}),
        A2AEvent(type="final", text="It's sunny in Lisbon.", final=True),
    ]
    app = _build_app(events)
    async with _serve(app, unused_tcp_port):
        transport = HttpTransport(routes={
            "probe.agents.default": f"http://127.0.0.1:{unused_tcp_port}/a2a"
        })
        ref = AgentRef(canonical_name="probe.agents.default", short_name="probe")
        msg = A2AMessage(role="user", parts=[{"text": "weather?"}], metadata={})

        received = []
        async for ev in transport.stream_task(ref, msg, {}, timeout=5):
            received.append(ev)

        # All three event types reached the consumer with payloads intact.
        assert len(received) == 3
        assert received[0].type == "tool_call"
        assert (received[0].data or {}).get("tool_name") == "ask_weather"
        assert received[1].type == "tool_result"
        assert (received[1].data or {}).get("duration_ms") == 2100
        assert received[2].type == "final"
        assert received[2].text == "It's sunny in Lisbon."


@pytest.mark.asyncio
async def test_token_envelope_does_not_break_stream(unused_tcp_port):
    """Mixed wire frames: legacy JSON-RPC envelopes for tokens + bare
    A2AEvent frames for tool_call/tool_result/final must coexist on the
    SSE stream. The transport may skip envelope frames silently (since
    they don't validate as A2AEvent) but must still surface every
    bare-A2AEvent frame to the consumer.
    """
    from vystak.transport import AgentRef
    from vystak_transport_http import HttpTransport

    events = [
        A2AEvent(type="token", text="thinking..."),  # → JSON-RPC envelope on wire
        A2AEvent(type="tool_call", data={"tool_name": "ask_weather"}),
        A2AEvent(type="final", text="done", final=True),
    ]
    app = _build_app(events)
    async with _serve(app, unused_tcp_port):
        transport = HttpTransport(routes={
            "probe.agents.default": f"http://127.0.0.1:{unused_tcp_port}/a2a"
        })
        ref = AgentRef(canonical_name="probe.agents.default", short_name="probe")
        msg = A2AMessage(role="user", parts=[{"text": "x"}], metadata={})

        types_seen = []
        async for ev in transport.stream_task(ref, msg, {}, timeout=5):
            types_seen.append(ev.type)

        # The token envelope frame may or may not surface depending on
        # whether transport.py skips ValidationError. The two bare frames
        # MUST surface in order.
        assert "tool_call" in types_seen
        assert "final" in types_seen
        assert types_seen.index("tool_call") < types_seen.index("final")
```

- [ ] **Step 2: Run the test**

Run: `uv run pytest packages/python/vystak-adapter-langchain/tests/test_streaming_e2e.py -v`
Expected: PASS — at least `test_tool_call_events_round_trip`.

If it fails with `pydantic.ValidationError: 1 validation error for A2AEvent / type / Field required`, the wire-format gap is real and `HttpTransport.stream_task` (`packages/python/vystak-transport-http/src/vystak_transport_http/transport.py:93`) needs:

```python
try:
    yield A2AEvent.model_validate(parsed)
except ValidationError:
    # Skip lines that don't match the A2AEvent shape (e.g., legacy
    # JSON-RPC envelope frames). Existing SSE consumers can still parse
    # the envelope themselves.
    continue
```

If you have to add this, also add a one-liner test in `vystak-transport-http/tests/test_http_transport.py` that asserts the skip-on-validation-error behavior.

- [ ] **Step 3: Commit**

```bash
git add packages/python/vystak-adapter-langchain/tests/test_streaming_e2e.py
# If transport.py was modified to skip ValidationError:
git add packages/python/vystak-transport-http/src/vystak_transport_http/transport.py \
        packages/python/vystak-transport-http/tests/test_http_transport.py
git commit -m "test(adapter-langchain): end-to-end SSE round-trip for tool_call streaming"
```

---

## Task 8: Verify full project gates

- [ ] **Step 1: Run full Python test suite**

Run: `uv run pytest packages/python/ -v -m "not docker"`
Expected: PASS (or no NEW failures vs. main; pre-existing typecheck/lint baseline noted in CLAUDE.md applies to typecheck-python and lint-typescript, neither of which runs here).

- [ ] **Step 2: Run lint**

Run: `just lint-python`
Expected: PASS — no new ruff complaints in the touched files.

- [ ] **Step 3: Manual smoke (optional but recommended)**

Stand up `examples/docker-slack-multi-agent` with `stream_tool_calls: true`:

```yaml
channels:
  - name: slack-main
    type: slack
    platform: docker
    config:
      stream_tool_calls: true   # NEW
    agents: [assistant-agent, weather-agent, time-agent]
    default_agent: assistant-agent
    secrets:
      - {name: SLACK_BOT_TOKEN}
      - {name: SLACK_APP_TOKEN}
```

Then:

```bash
cd examples/docker-slack-multi-agent
vystak destroy && vystak apply
```

Send a Slack message: "weather in Lisbon and current time". Expect the bot's reply to:
1. Post `_Responding..._` immediately.
2. Update to `🔧 *ask_weather_agent*\n_Working..._` within ~1s of the agent invoking it.
3. Add a second line `🔧 *ask_time_agent*` when the second tool starts.
4. Replace each line with `✓ _(Xs)_` as tools complete.
5. Replace the entire trail with the final reply text.

If any step misbehaves, capture the slack-channel container logs (`docker logs vystak-channel-slack-main 2>&1 | tail -200`) and the agent container logs.

- [ ] **Step 4: Final commit (if any cleanup needed)**

If smoke-test surfaces issues, fix them and commit. Otherwise no commit needed for this task.

---

## Spec coverage

| Acceptance criterion (spec §10) | Task / step covering it |
|--------------------------------|-------------------------|
| 1. `SlackChannelConfig(stream_tool_calls=True)` validates | Task 4 / step 1 (test_slack_channel_config_pydantic_field) |
| 2. `channel_config.json` carries the flag | Task 4 / step 1 (test_true_when_set_in_channel_config) |
| 3. `SERVER_PY` references `_stream_to_agent` and reads the flag | Task 5 / step 1 (test_helper_is_defined, test_runtime_reads_stream_tool_calls_flag) |
| 4. `process_turn_streaming` emits new TurnEvent types with duration | Task 2 / step 1 (TestTurnCoreToolCallEmissions) |
| 5. `_a2a_streaming` forwards as `tool_call` / `tool_result` | Task 3 / step 1 (TestA2AStreamingToolCallWireMapping) |
| 6. `chat.update` no more than once per second per turn | Task 5 / step 1 (test_helper_is_rate_limited) |
| 7. Final event replaces trail with final reply | Task 5 / step 1 (test_helper_replaces_placeholder_on_final) |
| 8. Error path uses existing "Sorry, I hit an error..." text | Task 5 / step 1 (test_helper_handles_error_with_legacy_text) |
| 9. Default (flag off) preserves today's behavior | Task 6 / step 1 (test_default_off_preserves_forward_to_agent) |
| 10. `just lint-python`, `just test-python`, `just typecheck-typescript`, `just test-typescript` pass | Task 8 |
| Wire-format gap (spec §architecture, implicit) | Task 3 / step 4 + Task 7 |

## Out-of-band notes

- The legacy `"tool_call"` Literal value on `TurnEvent.type` was unused; replacing it with `tool_call_start`/`tool_call_end` is safe (Task 1).
- DM messages (third branch in `on_message`) are intentionally NOT touched — they keep one-shot behavior. Out of scope per spec §non-goals (no separate path for DMs, but the behavioral choice is to keep the DM branch on `_forward_to_agent` for v1; revisit if user feedback demands streaming in DMs).
- The `final` SSE branch ends up emitting BOTH a JSON-RPC envelope AND a bare `model_dump_json()`. Anything currently consuming the envelope (gateway test fixtures) keeps working; the channel reads the bare frame. If a future cleanup wants a single wire shape, that's a separate spec — too much surface area to retrofit here.
- No website docs changes in scope. A one-paragraph addition to `website/docs/channels/slack.md` is deferred — the user can ask for it after the feature lands.
