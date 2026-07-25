# Tool-Call Visualization & Progress Status — Implementation Plan

**Goal:** Show tool activity (name, arguments, result) and a progress indicator in the control-panel chat, and persist tool calls so they replay on reload.

**Architecture:** The capability already exists on the A2A path (`executor.py` stamps `vystak_event: tool_call|tool_result`); the OpenAI-compatible `/v1/responses` path — the one the panel uses for streaming — never emitted it. This threads tool events through all four hops: agent SSE → panel `ResponsesClient` → panel SSE → AI SDK UI chunks → React.

**Tech stack:** Python 3.11+ (agent template, panel channel), Next.js 15 / `ai@5.0.220` / `@ai-sdk/react@2.0.222`.

## Verified contracts (checked against installed sources — do not re-derive)

**Agent → panel** (the shapes `vystak-chat/client.py:121-128` already parses, so emitting them also fixes that client):
- `response.output_item.added` with `item = {type: "function_call", id, call_id, name, arguments: ""}`
- `response.function_call_arguments.delta` with `delta`
- `response.function_call_arguments.done` with `arguments`
- `response.output_item.added` with `item = {type: "function_call_output", call_id, output}`

**AI SDK `UIMessageChunk` tool variants** (`ai@5.0.220` `index.d.ts:1766-1806`):
- `tool-input-start` `{toolCallId, toolName, dynamic?}`
- `tool-input-delta` `{toolCallId, inputTextDelta}`
- `tool-input-available` `{toolCallId, toolName, input, dynamic?}`
- `tool-output-available` `{toolCallId, output, dynamic?}`
- `tool-output-error` `{toolCallId, errorText, dynamic?}`

**`dynamic: true` is load-bearing.** The panel declares no client-side `tools` map, so without it the SDK produces no renderable part. With it, parts arrive as `part.type === 'dynamic-tool'` carrying `toolName`, `input`, `output`, `state` (`input-streaming` | `input-available` | `output-available` | `output-error`).

## Global Constraints

- The four live gates stay green: `just lint-python`, `just typecheck-typescript`, `just test-python`, `just test-typescript`.
- **Never run `just fmt-python`** — it reformats ~197 unrelated files.
- No `build` script in `packages/typescript/vystak-panel` (`just typecheck-typescript` runs `pnpm -r run build` first).
- Public repo: obvious fakes in tests, placeholders in examples.
- Every Python test run emits one pre-existing `UserWarning` about `Workspace.copy`; any *additional* warning is a finding.
- **After touching the agent template**: `uv sync --reinstall-package vystak-cli`, then `vystak update --force` in `examples/docker-panel`, or a redeploy will not see the change. The CLI's bundled template snapshot is a gitignored build artifact that does not regenerate on its own.
- **Baselines to diff against** (captured from the working deployment before any change):
  `<scratch>/baseline-agent-sse.txt` (agent hop) and `<scratch>/baseline-panel-sse.txt` (panel hop). Existing event types must still appear with unchanged shapes; tool events are strictly additive.

---

### Task 1: Schema versioning + `messages.parts` column

**Files:**
- Modify: `packages/python/vystak-channel-panel/src/vystak_channel_panel/store.py`
- Test: `packages/python/vystak-channel-panel/tests/test_store_migrations.py` (new)

**Interfaces produced:**
- `SCHEMA_VERSION: int = 2` module constant.
- `messages.parts TEXT` — nullable JSON column.
- `async _migrate(self) -> None`, run inside `connect()` after `executescript(_SCHEMA)`.
- `add_message(..., parts: list[dict] | None = None)` persists JSON; `PanelMessage.parts: list[dict] | None = None`.

**Why this is its own task:** `connect()` is `CREATE TABLE IF NOT EXISTS` only, so an existing `/data` volume silently never gains the column. There is a **live volume** (`vystak-panel-state`) holding a real admin, 3 conversations, and message history — the migration must be proven against that shape, not just a fresh DB.

Steps:
1. Write the migration test FIRST: build a **v1-shaped** DB by hand (old `_SCHEMA` without `parts`, no `schema_version` row), insert a user + conversation + message, then run `connect()` and assert (a) the `parts` column now exists, (b) the pre-existing message still reads back intact with `parts is None`, (c) `schema_version` is `2`, (d) calling `connect()` twice is a no-op. A fresh-DB test proves nothing here.
2. Run it, watch it fail.
3. Implement: read `schema_version` from `settings` (absent ⇒ 1); if `< 2`, `ALTER TABLE messages ADD COLUMN parts TEXT` — guarded by an actual `PRAGMA table_info(messages)` column check as well as the version row, since a live volume exists; then write `schema_version = 2`. Use the existing `_write()` helper.
4. `content` stays the source of truth for text; `parts` is **additive**. `list_messages` returns `parts` decoded when present, `None` otherwise — do not move text into `parts`, or every existing read path changes.
5. Full panel suite + gates, commit.

---

### Task 2: Agent template emits tool events

**Files:**
- Modify: `packages/python/vystak-template-langchain-python/_vystak/runtime/openai/responses.py`
- Test: `packages/python/vystak-template-langchain-python/tests/` (extend the streaming tests)

`_stream_iterator` already consumes `astream_events(version="v2")` and handles `on_chat_model_stream`. The same stream yields `on_tool_start` / `on_tool_end` — that is exactly how `a2a_native/executor.py:85-91` surfaces tool calls today. Emit the four event shapes listed above, keyed by a stable `call_id` per tool invocation (`ev["run_id"]` is the natural key).

Constraints:
- Strictly additive: text deltas, `output_text.done`, `completed`, and `failed` keep their current shapes — diff against `baseline-agent-sse.txt`.
- Tool arguments come from `ev["data"]["input"]`; the output from `ev["data"]["output"]`. Both may be non-string — reuse `flatten_content`/`json.dumps` rather than assuming `str`, the exact class of bug that broke this path once already.
- Do not touch the non-streaming path or `chat.py`.

---

### Task 3: Panel channel forwards and persists tool events

**Files:**
- Modify: `packages/python/vystak-channel-panel/src/vystak_channel_panel/responses_client.py`
- Modify: `packages/python/vystak-channel-panel/src/vystak_channel_panel/routes_messages.py`
- Test: extend `tests/test_responses_client.py` and `tests/test_api_messages_stream.py`

**Interfaces produced:**
- `PanelStreamEvent.type` gains `"tool_call"` and `"tool_result"`; new optional fields `tool_call_id: str = ""`, `tool_name: str = ""`, `arguments: str = ""`, `output: str = ""`.
- Panel SSE gains `{"type": "tool_call", "tool_call_id", "tool_name", "arguments"}` and `{"type": "tool_result", "tool_call_id", "output"}`.
- The assistant message persists `parts`: an ordered list of `{"type": "text", "text": ...}` and `{"type": "tool", "tool_call_id", "tool_name", "input", "output"}`.

**Critical:** there are **three** persist sites in `gen()` — the `done` branch, the `error` branch, and the post-loop truncated-stream branch. They have disagreed with each other twice already this session (once discarding text on error, once on a dropped connection). All three must persist the accumulated `parts` alongside the text. Add a test per branch.

---

### Task 4: SSE → AI SDK tool chunks

**Files:**
- Modify: `packages/typescript/vystak-panel/lib/stream.ts`
- Modify: `packages/typescript/vystak-panel/lib/types.ts` (part types)
- Test: `packages/typescript/vystak-panel/tests/stream.test.ts`

Map `tool_call` → `tool-input-start` + `tool-input-available`, and `tool_result` → `tool-output-available`. **Set `dynamic: true` on every tool chunk** (see contracts above). Text chunk ordering is unchanged; a tool part must not open inside an unclosed text part — close the current text part (`text-end`) before emitting tool chunks, and open a fresh one (`text-start` with a new id) if text resumes after.

Also add a **shared cross-language fixture** (`tests/fixtures/panel-sse.txt`) containing one canonical stream with text + a tool call, consumed by both this test and a Python test in Task 3 — the SSE contract currently spans two languages with nothing pinning it.

---

### Task 5: Render tool parts, history replay, progress indicator

**Files:**
- Modify: `packages/typescript/vystak-panel/components/chat.tsx`
- Modify: `packages/typescript/vystak-panel/app/p/[projectId]/c/[convId]/page.tsx`

1. Render `part.type === 'dynamic-tool'`: show `toolName` with a state-driven affordance (running / done / error), and a collapsible `<details>` carrying `input` and `output` (JSON-stringified, guarded for `undefined`).
2. History replay: map persisted `parts` back into `UIMessage.parts` — `{type:'text'}` passes through; `{type:'tool'}` becomes a `dynamic-tool` part with `state: 'output-available'`. When `parts` is null (pre-migration rows), fall back to synthesizing a single text part from `content`, exactly as today.
3. Progress indicator: when `status === 'submitted'` (sent, nothing streamed back yet) show a "thinking…" line. Keep the existing `error` banner and Dismiss.

---

### Definition of done

- All four live gates green.
- `uv sync --reinstall-package vystak-cli` → `vystak update --force` in `examples/docker-panel` → `vystak apply --force`.
- Live re-run of "What is the weather in Kyiv?" shows the `get_weather` call with arguments and result in the browser, and the tool call survives a reload.
- Panel SSE diffed against `baseline-panel-sse.txt`: prior event types unchanged, tool events additive.
