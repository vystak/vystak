# Durable / Checkpointed Execution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An in-flight agent turn survives the agent container restarting — it resumes from the last committed LangGraph checkpoint, continues publishing into the same JetStream turn subject, and the assistant reply lands exactly once.

**Architecture:** A durable-by-default checkpointer, plus a SQLite journal of detached turns living beside it. The checkpointer is wrapped so every committed checkpoint id is observable; the Responses SSE stream carries those ids as internal markers, letting the NATS bridge record exactly how many events had been published when each checkpoint became durable. On restart the bridge re-drives unfinished turns, publishing a rewind event so consumers discard exactly the events the resumed run will re-emit.

**Tech Stack:** Python 3.11+, LangGraph 1.1.10, `langgraph-checkpoint-sqlite`, `aiosqlite`, `nats-py` (JetStream), FastAPI, pytest/pytest-asyncio; TypeScript/Next.js for the panel UI.

**Spec:** `docs/superpowers/specs/2026-07-27-durable-checkpointed-execution-design.md`

## Global Constraints

- **v1 is Docker + NATS only.** Detached execution exists only in the NATS bridge. On the HTTP transport behavior is unchanged. Azure is out of scope (no NATS provisioning node).
- **Never edit `packages/python/vystak-cli/src/vystak_cli/templates/`.** It is build-hook output and gitignored (0 tracked files). The source of truth is `packages/python/vystak-template-langchain-python/`.
- **Agent images pip-install bare `vystak` from PyPI.** No change to `vystak` core schema may be required by agent-side code. Configuration reaches the agent through env vars (precedent: `VYSTAK_TRANSPORT_TYPE`).
- **Channel containers install the `REQUIREMENTS` string in `server_template.py`, not `pyproject.toml`.** Any new runtime dependency for `vystak-channel-panel` must be added there in the same commit.
- **The four live CI gates** are `just lint-python`, `just test-python`, `just typecheck-typescript`, `just test-typescript`. All four must stay green. `just typecheck-python` and `just lint-typescript` are known-red on main — do not treat them as regressions.
- **Never run repo-wide `just fmt-python`.**
- **Public repo.** Use placeholder credentials in examples (`<your-api-key>`) and obvious fakes in tests (`testpass`, `xoxb-test`).
- Journal is **always SQLite at `/data/turns.db`**, independent of the checkpointer engine.
- Re-drive attempts are capped at **3**; the panel's overall turn deadline is **15 minutes**.

---

### Task 1: Durable-by-default checkpointer with a path fallback chain

Removes `MemorySaver`. The fallback chain matters: `/data` does not exist in unit-test or dev environments, and `AsyncSqliteSaver.from_conn_string("/data/sessions.db")` would fail at lifespan startup, breaking `just test-python`.

**Files:**
- Modify: `packages/python/vystak-template-langchain-python/_vystak/runtime/store.py:29-53`
- Test: `packages/python/vystak-template-langchain-python/tests/test_store_checkpointer.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces: `resolve_sessions_path() -> str`; `build_checkpointer(agent) -> _LazyCheckpointer` (never `MemorySaver`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_store_checkpointer.py
import os
from pathlib import Path
from unittest import mock

from _vystak.runtime.store import _LazyCheckpointer, build_checkpointer, resolve_sessions_path


class _Agent:
    def __init__(self, sessions=None):
        self.sessions = sessions


class _Sessions:
    def __init__(self, engine, path=None, connection_string=None):
        self.engine = engine
        self.path = path
        self.connection_string = connection_string


def test_env_override_wins(tmp_path):
    target = tmp_path / "custom.db"
    with mock.patch.dict(os.environ, {"VYSTAK_SESSIONS_PATH": str(target)}):
        assert resolve_sessions_path() == str(target)


def test_data_dir_used_when_writable(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    with mock.patch.dict(os.environ, {}, clear=True):
        with mock.patch("_vystak.runtime.store._DATA_DIR", str(data)):
            assert resolve_sessions_path() == str(data / "sessions.db")


def test_falls_back_to_local_when_data_dir_missing(tmp_path):
    missing = tmp_path / "nope"
    with mock.patch.dict(os.environ, {}, clear=True):
        with mock.patch("_vystak.runtime.store._DATA_DIR", str(missing)):
            resolved = resolve_sessions_path()
    assert resolved.endswith("sessions.db")
    assert not resolved.startswith(str(missing))


def test_no_sessions_still_yields_durable_checkpointer(tmp_path):
    with mock.patch.dict(os.environ, {"VYSTAK_SESSIONS_PATH": str(tmp_path / "s.db")}):
        cp = build_checkpointer(_Agent())
    assert isinstance(cp, _LazyCheckpointer)


def test_memory_saver_is_gone(tmp_path):
    with mock.patch.dict(os.environ, {"VYSTAK_SESSIONS_PATH": str(tmp_path / "s.db")}):
        cp = build_checkpointer(_Agent())
    assert type(cp).__name__ != "MemorySaver"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/python/vystak-template-langchain-python/tests/test_store_checkpointer.py -v`
Expected: FAIL with `ImportError: cannot import name 'resolve_sessions_path'`

- [ ] **Step 3: Write minimal implementation**

Replace the body of `build_checkpointer` in `store.py` and add the resolver above it:

```python
import os
import tempfile

_DATA_DIR = "/data"


def resolve_sessions_path() -> str:
    """Resolve the default checkpointer path.

    Chain: VYSTAK_SESSIONS_PATH -> /data/sessions.db (when /data exists and is
    writable, i.e. the deployed container) -> a temp-dir path (unit tests, dev
    machines, and any platform that mounts no volume).
    """
    override = os.environ.get("VYSTAK_SESSIONS_PATH")
    if override:
        return override
    if os.path.isdir(_DATA_DIR) and os.access(_DATA_DIR, os.W_OK):
        return os.path.join(_DATA_DIR, "sessions.db")
    return os.path.join(tempfile.gettempdir(), "vystak-sessions.db")


def build_checkpointer(agent: Any):
    sessions = getattr(agent, "sessions", None)
    engine = getattr(sessions, "engine", None) if sessions is not None else None

    if engine == "postgres":
        def _make_pg_cm():
            from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
            return AsyncPostgresSaver.from_conn_string(sessions.connection_string)

        return _LazyCheckpointer(_make_pg_cm)

    if engine == "sqlite":
        path = getattr(sessions, "path", None) or resolve_sessions_path()
    else:
        # No sessions declared: durable by default rather than in-memory.
        path = resolve_sessions_path()

    def _make_cm():
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
        return AsyncSqliteSaver.from_conn_string(path)

    return _LazyCheckpointer(_make_cm)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/python/vystak-template-langchain-python/tests/ -v`
Expected: PASS. Existing tests that assumed `MemorySaver` for a session-less agent must be updated in this same task — search with `uv run pytest packages/python/ -k "checkpointer or MemorySaver" -v` and fix.

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-template-langchain-python/_vystak/runtime/store.py \
        packages/python/vystak-template-langchain-python/tests/test_store_checkpointer.py
git commit -m "feat(template): durable sqlite checkpointer by default, drop MemorySaver"
```

---

### Task 2: Observe committed checkpoints

Wraps the resolved saver so every durable `aput` is observable. This is the mechanism that makes boundaries truthful — `on_chain_end` fires *before* the checkpoint recording that node (measured; see spec §3).

**Files:**
- Modify: `packages/python/vystak-template-langchain-python/_vystak/runtime/store.py`
- Test: `packages/python/vystak-template-langchain-python/tests/test_checkpoint_observer.py` (create)

**Interfaces:**
- Consumes: Task 1's `build_checkpointer`.
- Produces: `CheckpointObserver` with `queue_for(thread_id) -> asyncio.Queue[str]`, `drain(thread_id) -> list[str]`, `release(thread_id)`; `ObservedSaver(saver, observer)` proxying `BaseCheckpointSaver`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_checkpoint_observer.py
import asyncio

import pytest

from _vystak.runtime.store import CheckpointObserver, ObservedSaver


class _FakeSaver:
    def __init__(self):
        self.puts = []

    async def aput(self, config, checkpoint, metadata, new_versions):
        self.puts.append(checkpoint["id"])
        return {"ok": True}

    async def aget_tuple(self, config):
        return None


@pytest.mark.asyncio
async def test_aput_delegates_and_records_id():
    inner = _FakeSaver()
    obs = CheckpointObserver()
    saver = ObservedSaver(inner, obs)
    cfg = {"configurable": {"thread_id": "t1"}}

    result = await saver.aput(cfg, {"id": "ck-1"}, {}, {})

    assert result == {"ok": True}
    assert inner.puts == ["ck-1"]
    assert obs.drain("t1") == ["ck-1"]


@pytest.mark.asyncio
async def test_drain_is_per_thread_and_empties():
    obs = CheckpointObserver()
    saver = ObservedSaver(_FakeSaver(), obs)
    await saver.aput({"configurable": {"thread_id": "a"}}, {"id": "ck-a"}, {}, {})
    await saver.aput({"configurable": {"thread_id": "b"}}, {"id": "ck-b"}, {}, {})

    assert obs.drain("a") == ["ck-a"]
    assert obs.drain("a") == []
    assert obs.drain("b") == ["ck-b"]


@pytest.mark.asyncio
async def test_unobserved_thread_drains_empty():
    assert CheckpointObserver().drain("never-seen") == []


@pytest.mark.asyncio
async def test_release_discards_thread_state():
    obs = CheckpointObserver()
    saver = ObservedSaver(_FakeSaver(), obs)
    await saver.aput({"configurable": {"thread_id": "t"}}, {"id": "ck"}, {}, {})
    obs.release("t")
    assert obs.drain("t") == []


@pytest.mark.asyncio
async def test_unknown_attributes_proxy_to_inner():
    inner = _FakeSaver()
    saver = ObservedSaver(inner, CheckpointObserver())
    assert await saver.aget_tuple({}) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/python/vystak-template-langchain-python/tests/test_checkpoint_observer.py -v`
Expected: FAIL with `ImportError: cannot import name 'CheckpointObserver'`

- [ ] **Step 3: Write minimal implementation**

Append to `store.py`:

```python
import asyncio


class CheckpointObserver:
    """Records committed checkpoint ids per thread.

    The Responses stream drains this to emit `vystak.checkpoint` markers. A
    marker is only ever emitted after the underlying `aput` returned, which is
    what makes the recorded stream position a truthful durability high-water
    mark.
    """

    def __init__(self) -> None:
        self._pending: dict[str, list[str]] = {}

    def record(self, thread_id: str, checkpoint_id: str) -> None:
        if not thread_id or not checkpoint_id:
            return
        self._pending.setdefault(thread_id, []).append(checkpoint_id)

    def drain(self, thread_id: str) -> list[str]:
        return self._pending.pop(thread_id, []) if thread_id in self._pending else []

    def release(self, thread_id: str) -> None:
        self._pending.pop(thread_id, None)


class ObservedSaver:
    """Transparent proxy around a checkpointer that reports committed puts."""

    def __init__(self, inner: Any, observer: CheckpointObserver) -> None:
        self._inner = inner
        self._observer = observer

    async def aput(self, config, checkpoint, metadata, new_versions):  # noqa: ANN001
        result = await self._inner.aput(config, checkpoint, metadata, new_versions)
        thread_id = (config or {}).get("configurable", {}).get("thread_id", "")
        self._observer.record(str(thread_id), str(checkpoint.get("id", "")))
        return result

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)
```

Note `record` is called *after* `await self._inner.aput(...)` — that ordering is the whole point of the class.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest packages/python/vystak-template-langchain-python/tests/test_checkpoint_observer.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Wire the observer into the lifespan**

In `app_factory.py`, where the lazy checkpointer is resolved (around lines 154-169), wrap the resolved saver and expose the observer on app state:

```python
observer = CheckpointObserver()
app_.state.checkpoint_observer = observer
resolved = ObservedSaver(resolved, observer)
```

Add `CheckpointObserver` and `ObservedSaver` to the existing `from _vystak.runtime.store import (...)` block at `app_factory.py:36`.

- [ ] **Step 6: Run the full template suite**

Run: `uv run pytest packages/python/vystak-template-langchain-python/tests/ -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add packages/python/vystak-template-langchain-python/_vystak/runtime/store.py \
        packages/python/vystak-template-langchain-python/_vystak/runtime/app_factory.py \
        packages/python/vystak-template-langchain-python/tests/test_checkpoint_observer.py
git commit -m "feat(template): observe committed checkpoint ids via saver proxy"
```

---

### Task 3: Emit `vystak.checkpoint` markers in the Responses stream

**Files:**
- Modify: `packages/python/vystak-template-langchain-python/_vystak/runtime/openai/responses.py:52-80`
- Test: `packages/python/vystak-template-langchain-python/tests/test_openai_responses_checkpoints.py` (create)

**Interfaces:**
- Consumes: `CheckpointObserver.drain` (Task 2).
- Produces: SSE events shaped `{"type": "vystak.checkpoint", "checkpoint_id": "<id>"}`, emitted before the graph event received in the same loop iteration. `ResponsesHandler.__init__` gains an optional `observer` keyword (default `None` → no markers).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_openai_responses_checkpoints.py
import json

import pytest

from _vystak.runtime.openai.responses import ResponsesHandler
from _vystak.runtime.store import CheckpointObserver


class _Agent:
    name = "probe"
    sessions = None


class _Graph:
    """Yields two chat-model chunks; a checkpoint commits between them."""

    def __init__(self, observer, thread_id):
        self._observer = observer
        self._thread_id = thread_id

    async def astream_events(self, input, config, version="v2"):  # noqa: ANN001
        yield {"event": "on_chat_model_stream", "data": {"chunk": {"content": "one"}}}
        self._observer.record(self._thread_id, "ck-mid")
        yield {"event": "on_chat_model_stream", "data": {"chunk": {"content": "two"}}}


def _payloads(chunks):
    out = []
    for c in chunks:
        line = c.strip()
        if line.startswith("data:"):
            out.append(json.loads(line[len("data:"):].strip()))
    return out


@pytest.mark.asyncio
async def test_marker_emitted_after_commit_and_before_next_event():
    observer = CheckpointObserver()
    thread_id = "resp_fixed"
    handler = ResponsesHandler(
        agent=_Agent(), graph=_Graph(observer, thread_id), observer=observer
    )
    body = {"previous_response_id": thread_id, "input": "hi", "stream": True}

    chunks = [c async for c in handler._stream_iterator(body)]
    types = [p.get("type") for p in _payloads(chunks)]

    first_delta = types.index("response.output_text.delta")
    marker = types.index("vystak.checkpoint")
    second_delta = types.index("response.output_text.delta", first_delta + 1)
    assert first_delta < marker < second_delta


@pytest.mark.asyncio
async def test_marker_carries_checkpoint_id():
    observer = CheckpointObserver()
    handler = ResponsesHandler(
        agent=_Agent(), graph=_Graph(observer, "resp_fixed"), observer=observer
    )
    payloads = _payloads(
        [c async for c in handler._stream_iterator(
            {"previous_response_id": "resp_fixed", "input": "hi"}
        )]
    )
    markers = [p for p in payloads if p.get("type") == "vystak.checkpoint"]
    assert [m["checkpoint_id"] for m in markers] == ["ck-mid"]


@pytest.mark.asyncio
async def test_no_observer_emits_no_markers():
    observer = CheckpointObserver()
    handler = ResponsesHandler(agent=_Agent(), graph=_Graph(observer, "resp_fixed"))
    payloads = _payloads(
        [c async for c in handler._stream_iterator(
            {"previous_response_id": "resp_fixed", "input": "hi"}
        )]
    )
    assert not [p for p in payloads if p.get("type") == "vystak.checkpoint"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/python/vystak-template-langchain-python/tests/test_openai_responses_checkpoints.py -v`
Expected: FAIL — `ResponsesHandler.__init__` does not accept `observer`

- [ ] **Step 3: Write minimal implementation**

Add `observer=None` to `ResponsesHandler.__init__`, storing `self._observer = observer`. Then inside `_stream_iterator`, drain immediately after receiving each event and before emitting it:

```python
async for ev in self.graph.astream_events(
    {"messages": messages}, config, version="v2"
):
    if self._observer is not None:
        for checkpoint_id in self._observer.drain(thread_id):
            yield _sse({"type": "vystak.checkpoint", "checkpoint_id": checkpoint_id})
    ev_type = ev.get("event")
    ...
```

After the loop ends, drain once more so a final checkpoint is not dropped:

```python
if self._observer is not None:
    for checkpoint_id in self._observer.drain(thread_id):
        yield _sse({"type": "vystak.checkpoint", "checkpoint_id": checkpoint_id})
```

In `app_factory.py`, pass `observer=app_.state.checkpoint_observer` where `ResponsesHandler` is constructed.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/python/vystak-template-langchain-python/tests/ -v`
Expected: PASS. `test_codegen_parity.py` must stay green — its `ReplayGraph` passes no observer, so no markers are emitted and the golden file is unaffected. Confirm rather than assume.

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-template-langchain-python/_vystak/runtime/openai/responses.py \
        packages/python/vystak-template-langchain-python/_vystak/runtime/app_factory.py \
        packages/python/vystak-template-langchain-python/tests/test_openai_responses_checkpoints.py
git commit -m "feat(template): emit vystak.checkpoint markers in the Responses stream"
```

---

### Task 4: Resume endpoint

`POST /v1/responses` always starts a new response. Continuing an interrupted thread needs a distinct surface.

**Files:**
- Modify: `packages/python/vystak-template-langchain-python/_vystak/runtime/openai/responses.py`
- Modify: `packages/python/vystak-template-langchain-python/_vystak/runtime/app_factory.py`
- Test: `packages/python/vystak-template-langchain-python/tests/test_openai_responses_resume.py` (create)

**Interfaces:**
- Consumes: Task 3's `_stream_iterator`.
- Produces: `ResponsesHandler.resume_stream(thread_id: str, resume: Any | None) -> AsyncIterator[str]`; route `POST /v1/_vystak/resume` accepting `{"thread_id": str, "resume": Any | None}`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_openai_responses_resume.py
import pytest

from _vystak.runtime.openai.responses import ResponsesHandler


class _Agent:
    name = "probe"
    sessions = None


class _RecordingGraph:
    def __init__(self):
        self.inputs = []

    async def astream_events(self, input, config, version="v2"):  # noqa: ANN001
        self.inputs.append(input)
        yield {"event": "on_chat_model_stream", "data": {"chunk": {"content": "resumed"}}}


@pytest.mark.asyncio
async def test_resume_passes_none_as_graph_input():
    graph = _RecordingGraph()
    handler = ResponsesHandler(agent=_Agent(), graph=graph)
    _ = [c async for c in handler.resume_stream("thread-1", None)]
    assert graph.inputs == [None]


@pytest.mark.asyncio
async def test_resume_with_value_passes_command():
    graph = _RecordingGraph()
    handler = ResponsesHandler(agent=_Agent(), graph=graph)
    _ = [c async for c in handler.resume_stream("thread-1", {"approved": True})]
    sent = graph.inputs[0]
    assert type(sent).__name__ == "Command"
    assert sent.resume == {"approved": True}


@pytest.mark.asyncio
async def test_resume_uses_given_thread_id():
    graph = _RecordingGraph()
    handler = ResponsesHandler(agent=_Agent(), graph=graph)
    chunks = [c async for c in handler.resume_stream("thread-xyz", None)]
    assert any("thread-xyz" in c for c in chunks)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/python/vystak-template-langchain-python/tests/test_openai_responses_resume.py -v`
Expected: FAIL with `AttributeError: 'ResponsesHandler' object has no attribute 'resume_stream'`

- [ ] **Step 3: Write minimal implementation**

Refactor `_stream_iterator` to take the graph input explicitly, then add the public resume entry point:

```python
async def _stream_iterator(self, body: dict, *, graph_input: Any = _UNSET):
    thread_id = body.get("previous_response_id") or _new_response_id()
    ...
    if graph_input is _UNSET:
        graph_input = {"messages": _normalize_input(body.get("input"))}
    async for ev in self.graph.astream_events(graph_input, config, version="v2"):
        ...

def resume_stream(self, thread_id: str, resume: Any | None = None):
    """Continue an interrupted thread. `resume=None` replays from the last
    checkpoint; a value drives a pending interrupt()."""
    graph_input = None
    if resume is not None:
        from langgraph.types import Command
        graph_input = Command(resume=resume)
    return self._stream_iterator(
        {"previous_response_id": thread_id}, graph_input=graph_input
    )
```

Define `_UNSET = object()` at module level. In `app_factory.py` register the route:

```python
@app.post("/v1/_vystak/resume")
async def _vystak_resume(request: Request):
    payload = await request.json()
    thread_id = payload.get("thread_id")
    if not thread_id:
        return JSONResponse({"error": "thread_id required"}, status_code=400)
    return StreamingResponse(
        app.state.responses_handler.resume_stream(thread_id, payload.get("resume")),
        media_type="text/event-stream",
    )
```

It is internal: do not advertise it on the agent card.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/python/vystak-template-langchain-python/tests/ -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-template-langchain-python/_vystak/runtime/openai/responses.py \
        packages/python/vystak-template-langchain-python/_vystak/runtime/app_factory.py \
        packages/python/vystak-template-langchain-python/tests/test_openai_responses_resume.py
git commit -m "feat(template): POST /v1/_vystak/resume to continue an interrupted thread"
```

---

### Task 5: Turn journal store

**Files:**
- Create: `packages/python/vystak-template-langchain-python/_vystak/runtime/turn_journal.py`
- Test: `packages/python/vystak-template-langchain-python/tests/test_turn_journal.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces: `TurnJournal` ABC with `create(turn_id, stream_subject, request)`, `set_thread_id(turn_id, thread_id)`, `record_boundary(turn_id, checkpoint_id, seq)`, `set_last_seq(turn_id, seq)`, `set_status(turn_id, status)`, `bump_attempts(turn_id) -> int`, `get(turn_id) -> TurnRecord | None`, `list_running() -> list[TurnRecord]`, `seq_for_checkpoint(turn_id, checkpoint_id) -> int | None`, `close()`. Implementations `InMemoryTurnJournal` and `SqliteTurnJournal(path)`. `TurnRecord` is a dataclass with fields `turn_id, stream_subject, thread_id, request, status, last_seq, boundary_seq, attempts`. Statuses: `running | parked | done | failed`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_turn_journal.py
import pytest

from _vystak.runtime.turn_journal import InMemoryTurnJournal, SqliteTurnJournal


def _journals(tmp_path):
    return [
        ("memory", InMemoryTurnJournal()),
        ("sqlite", SqliteTurnJournal(str(tmp_path / "turns.db"))),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["memory", "sqlite"])
async def test_create_then_get_roundtrip(tmp_path, kind):
    j = dict(_journals(tmp_path))[kind]
    await j.create("t1", "subj.a", {"input": "hello"})
    rec = await j.get("t1")
    assert rec.turn_id == "t1"
    assert rec.stream_subject == "subj.a"
    assert rec.request == {"input": "hello"}
    assert rec.status == "running"
    assert rec.last_seq == -1
    assert rec.boundary_seq == -1
    assert rec.attempts == 0
    await j.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["memory", "sqlite"])
async def test_boundary_lookup_by_checkpoint(tmp_path, kind):
    j = dict(_journals(tmp_path))[kind]
    await j.create("t1", "subj.a", {})
    await j.record_boundary("t1", "ck-1", 4)
    await j.record_boundary("t1", "ck-2", 9)
    assert await j.seq_for_checkpoint("t1", "ck-1") == 4
    assert await j.seq_for_checkpoint("t1", "ck-2") == 9
    assert await j.seq_for_checkpoint("t1", "ck-missing") is None
    rec = await j.get("t1")
    assert rec.boundary_seq == 9
    await j.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["memory", "sqlite"])
async def test_list_running_excludes_terminal_and_parked(tmp_path, kind):
    j = dict(_journals(tmp_path))[kind]
    for turn_id, status in [("a", "running"), ("b", "done"), ("c", "failed"), ("d", "parked")]:
        await j.create(turn_id, "s", {})
        if status != "running":
            await j.set_status(turn_id, status)
    assert sorted(r.turn_id for r in await j.list_running()) == ["a"]
    await j.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["memory", "sqlite"])
async def test_bump_attempts_returns_new_value(tmp_path, kind):
    j = dict(_journals(tmp_path))[kind]
    await j.create("t1", "s", {})
    assert await j.bump_attempts("t1") == 1
    assert await j.bump_attempts("t1") == 2
    assert (await j.get("t1")).attempts == 2
    await j.close()


@pytest.mark.asyncio
async def test_sqlite_survives_reopen(tmp_path):
    path = str(tmp_path / "turns.db")
    j = SqliteTurnJournal(path)
    await j.create("t1", "subj.a", {"input": "hello"})
    await j.set_last_seq("t1", 7)
    await j.set_thread_id("t1", "resp_abc")
    await j.close()

    reopened = SqliteTurnJournal(path)
    rec = await reopened.get("t1")
    assert rec.last_seq == 7
    assert rec.thread_id == "resp_abc"
    assert rec.status == "running"
    await reopened.close()


@pytest.mark.asyncio
async def test_get_unknown_turn_returns_none(tmp_path):
    j = SqliteTurnJournal(str(tmp_path / "turns.db"))
    assert await j.get("nope") is None
    await j.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/python/vystak-template-langchain-python/tests/test_turn_journal.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named '_vystak.runtime.turn_journal'`

- [ ] **Step 3: Write minimal implementation**

Create `turn_journal.py` following the `heartbeat_sessions.py` structure exactly (ABC + in-memory + `aiosqlite` impl with a `_lock`-guarded lazy `_ensure()` connection). DDL:

```python
_DDL = """
CREATE TABLE IF NOT EXISTS detached_turns (
    turn_id        TEXT PRIMARY KEY,
    stream_subject TEXT NOT NULL,
    thread_id      TEXT,
    request_json   TEXT NOT NULL,
    status         TEXT NOT NULL,
    last_seq       INTEGER NOT NULL DEFAULT -1,
    boundary_seq   INTEGER NOT NULL DEFAULT -1,
    attempts       INTEGER NOT NULL DEFAULT 0,
    updated_at     TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS turn_boundaries (
    turn_id       TEXT NOT NULL,
    checkpoint_id TEXT NOT NULL,
    seq           INTEGER NOT NULL,
    PRIMARY KEY (turn_id, checkpoint_id)
);
"""
```

Use `executescript` for the two-statement DDL. `record_boundary` writes the `turn_boundaries` row (`INSERT ... ON CONFLICT DO UPDATE`) and sets `detached_turns.boundary_seq = seq` in the same call. `request` is stored as `json.dumps` and returned parsed.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest packages/python/vystak-template-langchain-python/tests/test_turn_journal.py -v`
Expected: PASS (11 tests)

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-template-langchain-python/_vystak/runtime/turn_journal.py \
        packages/python/vystak-template-langchain-python/tests/test_turn_journal.py
git commit -m "feat(template): detached-turn journal store"
```

---

### Task 6: Journal the detached turn as it runs

**Files:**
- Modify: `packages/python/vystak-template-langchain-python/_vystak/runtime/nats_bridge.py:330-400`
- Test: `packages/python/vystak-template-langchain-python/tests/test_nats_bridge_journal.py` (create)

**Interfaces:**
- Consumes: Task 5's `TurnJournal`; Task 3's `vystak.checkpoint` markers.
- Produces: `NatsHttpBridge` accepts `journal: TurnJournal | None`; `_run_detached(request, stream_subject, turn_id)` gains `turn_id` and journals as it goes.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_nats_bridge_journal.py
import json

import pytest

from _vystak.runtime.turn_journal import InMemoryTurnJournal


@pytest.mark.asyncio
async def test_row_created_before_ack(bridge_factory):
    journal = InMemoryTurnJournal()
    bridge = bridge_factory(journal=journal)
    await bridge._handle_responses_create_detached(
        {"id": 1, "params": {"request": {"input": "hi"},
                             "turn_id": "t1", "stream_subject": "s.t1"}},
        "reply.inbox",
    )
    rec = await journal.get("t1")
    assert rec is not None and rec.status == "running"


@pytest.mark.asyncio
async def test_thread_id_captured_from_response_created(bridge_factory):
    journal = InMemoryTurnJournal()
    bridge = bridge_factory(
        journal=journal,
        sse_events=[{"type": "response.created", "response": {"id": "resp_9"}}],
    )
    await journal.create("t1", "s.t1", {})
    await bridge._run_detached({"input": "hi"}, "s.t1", "t1")
    assert (await journal.get("t1")).thread_id == "resp_9"


@pytest.mark.asyncio
async def test_checkpoint_marker_records_boundary_and_is_not_published(bridge_factory):
    journal = InMemoryTurnJournal()
    bridge = bridge_factory(
        journal=journal,
        sse_events=[
            {"type": "response.output_text.delta", "delta": "a"},
            {"type": "vystak.checkpoint", "checkpoint_id": "ck-1"},
            {"type": "response.output_text.delta", "delta": "b"},
        ],
    )
    await journal.create("t1", "s.t1", {})
    await bridge._run_detached({"input": "hi"}, "s.t1", "t1")

    published = [json.loads(p)["event"]["type"] for p in bridge.published_payloads]
    assert "vystak.checkpoint" not in published
    # one delta published (seq 0) before the marker
    assert await journal.seq_for_checkpoint("t1", "ck-1") == 0


@pytest.mark.asyncio
async def test_terminal_event_marks_done(bridge_factory):
    journal = InMemoryTurnJournal()
    bridge = bridge_factory(
        journal=journal,
        sse_events=[{"type": "response.completed", "response": {"id": "resp_1"}}],
    )
    await journal.create("t1", "s.t1", {})
    await bridge._run_detached({"input": "hi"}, "s.t1", "t1")
    assert (await journal.get("t1")).status == "done"


@pytest.mark.asyncio
async def test_failure_marks_failed(bridge_factory):
    journal = InMemoryTurnJournal()
    bridge = bridge_factory(
        journal=journal,
        sse_events=[{"type": "response.failed", "response": {"error": {"message": "boom"}}}],
    )
    await journal.create("t1", "s.t1", {})
    await bridge._run_detached({"input": "hi"}, "s.t1", "t1")
    assert (await journal.get("t1")).status == "failed"
```

Add a `bridge_factory` fixture to `tests/conftest.py` building a `NatsHttpBridge` with a stub NATS connection recording `published_payloads`, and a stub HTTP client replaying `sse_events`. Model it on the existing stubs in `test_nats_bridge.py`.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/python/vystak-template-langchain-python/tests/test_nats_bridge_journal.py -v`
Expected: FAIL — `_run_detached()` takes 3 positional arguments but 4 were given

- [ ] **Step 3: Write minimal implementation**

In `_handle_responses_create_detached`, create the journal row **before** publishing the ack (the crash window is then one INSERT wide), and pass `turn_id` into `_run_detached`. In `_run_detached`'s SSE loop:

```python
if event.get("type") == "vystak.checkpoint":
    if self._journal is not None:
        await self._journal.record_boundary(
            turn_id, event.get("checkpoint_id", ""), seq - 1
        )
    continue  # internal: never published to JetStream

if event.get("type") == "response.created":
    response_id = event.get("response", {}).get("id", "")
    if response_id and self._journal is not None:
        await self._journal.set_thread_id(turn_id, response_id)

await publish(event)
if self._journal is not None:
    await self._journal.set_last_seq(turn_id, seq - 1)
```

`seq - 1` is the last *published* seq, because `publish` post-increments. On `response.completed` set status `done`; on `response.failed` set `failed`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/python/vystak-template-langchain-python/tests/ -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-template-langchain-python/_vystak/runtime/nats_bridge.py \
        packages/python/vystak-template-langchain-python/tests/test_nats_bridge_journal.py \
        packages/python/vystak-template-langchain-python/tests/conftest.py
git commit -m "feat(template): journal detached turns and record checkpoint boundaries"
```

---

### Task 7: Re-drive unfinished turns on startup

**Files:**
- Modify: `packages/python/vystak-template-langchain-python/_vystak/runtime/nats_bridge.py`
- Test: `packages/python/vystak-template-langchain-python/tests/test_nats_bridge_redrive.py` (create)

**Interfaces:**
- Consumes: Tasks 4-6.
- Produces: `NatsHttpBridge.redrive_unfinished() -> int` (count re-driven), called from bridge startup. Publishes `{"type": "vystak.turn.rewind", "to_seq": int}`. Module constant `MAX_REDRIVE_ATTEMPTS = 3`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_nats_bridge_redrive.py
import json

import pytest

from _vystak.runtime.nats_bridge import MAX_REDRIVE_ATTEMPTS
from _vystak.runtime.turn_journal import InMemoryTurnJournal


@pytest.mark.asyncio
async def test_rewind_targets_the_resumed_checkpoint(bridge_factory):
    journal = InMemoryTurnJournal()
    await journal.create("t1", "s.t1", {"input": "hi"})
    await journal.set_thread_id("t1", "resp_1")
    await journal.record_boundary("t1", "ck-1", 3)
    await journal.record_boundary("t1", "ck-2", 8)
    await journal.set_last_seq("t1", 12)

    # LangGraph will resume from ck-1, not the last boundary we observed.
    bridge = bridge_factory(journal=journal, resume_checkpoint_id="ck-1")
    await bridge.redrive_unfinished()

    first = json.loads(bridge.published_payloads[0])
    assert first["seq"] == 13
    assert first["event"] == {"type": "vystak.turn.rewind", "to_seq": 3}


@pytest.mark.asyncio
async def test_falls_back_to_boundary_seq_when_checkpoint_unknown(bridge_factory):
    journal = InMemoryTurnJournal()
    await journal.create("t1", "s.t1", {})
    await journal.set_thread_id("t1", "resp_1")
    await journal.record_boundary("t1", "ck-2", 8)
    await journal.set_last_seq("t1", 12)

    bridge = bridge_factory(journal=journal, resume_checkpoint_id="ck-unknown")
    await bridge.redrive_unfinished()

    assert json.loads(bridge.published_payloads[0])["event"]["to_seq"] == 8


@pytest.mark.asyncio
async def test_parked_turns_are_not_redriven(bridge_factory):
    journal = InMemoryTurnJournal()
    await journal.create("t1", "s.t1", {})
    await journal.set_status("t1", "parked")
    bridge = bridge_factory(journal=journal)
    assert await bridge.redrive_unfinished() == 0
    assert bridge.published_payloads == []


@pytest.mark.asyncio
async def test_attempts_cap_fails_the_turn(bridge_factory):
    journal = InMemoryTurnJournal()
    await journal.create("t1", "s.t1", {})
    await journal.set_last_seq("t1", 5)
    for _ in range(MAX_REDRIVE_ATTEMPTS):
        await journal.bump_attempts("t1")

    bridge = bridge_factory(journal=journal)
    await bridge.redrive_unfinished()

    assert (await journal.get("t1")).status == "failed"
    published = [json.loads(p)["event"]["type"] for p in bridge.published_payloads]
    assert published == ["response.failed"]


@pytest.mark.asyncio
async def test_attempts_increment_on_redrive(bridge_factory):
    journal = InMemoryTurnJournal()
    await journal.create("t1", "s.t1", {})
    await journal.set_thread_id("t1", "resp_1")
    bridge = bridge_factory(journal=journal, resume_checkpoint_id="ck-1")
    await bridge.redrive_unfinished()
    assert (await journal.get("t1")).attempts == 1
```

Extend `bridge_factory` with `resume_checkpoint_id`, stubbing the agent's current-checkpoint lookup.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/python/vystak-template-langchain-python/tests/test_nats_bridge_redrive.py -v`
Expected: FAIL with `ImportError: cannot import name 'MAX_REDRIVE_ATTEMPTS'`

- [ ] **Step 3: Write minimal implementation**

```python
MAX_REDRIVE_ATTEMPTS = 3


async def redrive_unfinished(self) -> int:
    if self._journal is None:
        return 0
    count = 0
    for rec in await self._journal.list_running():
        if rec.attempts >= MAX_REDRIVE_ATTEMPTS:
            await self._publish_synthetic_failure(
                rec, "turn abandoned after repeated restarts"
            )
            await self._journal.set_status(rec.turn_id, "failed")
            continue
        await self._journal.bump_attempts(rec.turn_id)
        await self._redrive_one(rec)
        count += 1
    return count


async def _redrive_one(self, rec) -> None:
    checkpoint_id = await self._current_checkpoint_id(rec.thread_id)
    to_seq = await self._journal.seq_for_checkpoint(rec.turn_id, checkpoint_id)
    if to_seq is None:
        to_seq = rec.boundary_seq
    seq = rec.last_seq + 1
    await self._publish_seq(
        rec.stream_subject, seq, {"type": "vystak.turn.rewind", "to_seq": to_seq}
    )
    await self._stream_from_resume_endpoint(rec, start_seq=seq + 1)
```

`_current_checkpoint_id` calls the agent's `GET /v1/_vystak/checkpoint?thread_id=...` — add that trivial route alongside the resume route in Task 4's file, returning `{"checkpoint_id": <id or null>}` from `graph.aget_state(config)`. `_stream_from_resume_endpoint` POSTs `/v1/_vystak/resume` and reuses the exact SSE-consumption loop from `_run_detached` (extract it into a shared helper rather than duplicating — the marker and journaling behavior must be identical on both paths).

Call `await self.redrive_unfinished()` from bridge startup, after the NATS connection is live.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/python/vystak-template-langchain-python/tests/ -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-template-langchain-python/_vystak/runtime/nats_bridge.py \
        packages/python/vystak-template-langchain-python/_vystak/runtime/openai/responses.py \
        packages/python/vystak-template-langchain-python/_vystak/runtime/app_factory.py \
        packages/python/vystak-template-langchain-python/tests/test_nats_bridge_redrive.py \
        packages/python/vystak-template-langchain-python/tests/conftest.py
git commit -m "feat(template): re-drive unfinished detached turns on startup"
```

---

### Task 8: `responses/turnStatus` and `responses/resumeDetached` RPCs

**Files:**
- Modify: `packages/python/vystak-template-langchain-python/_vystak/runtime/nats_bridge.py:130-150`
- Test: `packages/python/vystak-template-langchain-python/tests/test_nats_bridge_rpcs.py` (create)

**Interfaces:**
- Consumes: Tasks 5-7.
- Produces: RPC `responses/turnStatus {turn_id}` → `{"status": "running"|"parked"|"done"|"failed"|"unknown"}`; RPC `responses/resumeDetached {turn_id, resume}` → `{"turn_id": ...}` ack, then continues the turn.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_nats_bridge_rpcs.py
import json

import pytest

from _vystak.runtime.turn_journal import InMemoryTurnJournal


def _reply(bridge):
    return json.loads(bridge.replies[-1])["result"]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["running", "parked", "done", "failed"])
async def test_turn_status_reports_journal_status(bridge_factory, status):
    journal = InMemoryTurnJournal()
    await journal.create("t1", "s.t1", {})
    if status != "running":
        await journal.set_status("t1", status)
    bridge = bridge_factory(journal=journal)

    await bridge._handle_envelope_for_test(
        {"id": 1, "method": "responses/turnStatus", "params": {"turn_id": "t1"}},
        "reply.inbox",
    )
    assert _reply(bridge)["status"] == status


@pytest.mark.asyncio
async def test_turn_status_unknown_for_missing_row(bridge_factory):
    bridge = bridge_factory(journal=InMemoryTurnJournal())
    await bridge._handle_envelope_for_test(
        {"id": 1, "method": "responses/turnStatus", "params": {"turn_id": "ghost"}},
        "reply.inbox",
    )
    assert _reply(bridge)["status"] == "unknown"


@pytest.mark.asyncio
async def test_resume_detached_flips_parked_to_running(bridge_factory):
    journal = InMemoryTurnJournal()
    await journal.create("t1", "s.t1", {})
    await journal.set_status("t1", "parked")
    await journal.set_thread_id("t1", "resp_1")
    bridge = bridge_factory(journal=journal, resume_checkpoint_id="ck-1")

    await bridge._handle_envelope_for_test(
        {"id": 1, "method": "responses/resumeDetached",
         "params": {"turn_id": "t1", "resume": {"approved": True}}},
        "reply.inbox",
    )
    assert (await journal.get("t1")).status == "running"


@pytest.mark.asyncio
async def test_resume_detached_publishes_no_rewind(bridge_factory):
    """Nothing was lost on a park, so there is nothing to discard."""
    journal = InMemoryTurnJournal()
    await journal.create("t1", "s.t1", {})
    await journal.set_status("t1", "parked")
    await journal.set_thread_id("t1", "resp_1")
    bridge = bridge_factory(journal=journal, resume_checkpoint_id="ck-1")

    await bridge._handle_envelope_for_test(
        {"id": 1, "method": "responses/resumeDetached", "params": {"turn_id": "t1"}},
        "reply.inbox",
    )
    types = [json.loads(p)["event"]["type"] for p in bridge.published_payloads]
    assert "vystak.turn.rewind" not in types
```

Extend `bridge_factory` with `_handle_envelope_for_test(envelope, reply_subject)` — a thin test seam that calls the bridge's existing envelope-dispatch method (the one containing the `responses/createDetached` branch at `nats_bridge.py:142`) with a stub NATS message, and a `replies` list recording every payload published to `reply_subject`.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/python/vystak-template-langchain-python/tests/test_nats_bridge_rpcs.py -v`
Expected: FAIL — unknown method, no `result` in reply

- [ ] **Step 3: Write minimal implementation**

Add two branches beside the existing `responses/createDetached` dispatch at `nats_bridge.py:142`:

```python
if method == "responses/turnStatus":
    rec = await self._journal.get(params.get("turn_id", "")) if self._journal else None
    await self._publish_result(
        reply_subject, envelope.get("id"),
        {"status": rec.status if rec else "unknown"},
    )
    return

if method == "responses/resumeDetached":
    await self._handle_resume_detached(envelope, reply_subject)
    return
```

`_handle_resume_detached` looks the row up (JSON-RPC error if absent), sets status `running`, publishes the ack, then spawns a tracked background task calling `_stream_from_resume_endpoint(rec, start_seq=rec.last_seq + 1, resume=params.get("resume"))` — no rewind.

- [ ] **Step 4: Detect a park and mark the row**

Nothing yet *produces* a `parked` row. A graph that hits `interrupt()` ends its SSE stream with no terminal event (`response.completed` / `response.failed` never arrive). Extend `/v1/_vystak/checkpoint` from Task 7 to also return `{"interrupted": bool}` from `graph.aget_state(config).next`, and in the shared SSE-consumption helper:

```python
if not saw_terminal_event and self._journal is not None:
    state = await self._agent_checkpoint_state(rec.thread_id)
    await self._journal.set_status(
        rec.turn_id, "parked" if state.get("interrupted") else "failed"
    )
```

Add a test with a stub graph whose stream ends with no terminal event and whose state reports `interrupted: True`, asserting the row becomes `parked` and no terminal event is published (the panel's `turnStatus` consult is what keeps it waiting). Add a second test with `interrupted: False` asserting `failed`.

The seam is otherwise unexercised in v1: no shipped tool calls `interrupt()`. Add a test-only interrupting tool in the template test suite to prove `resumeDetached` drives a real parked graph to completion.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest packages/python/vystak-template-langchain-python/tests/ -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add packages/python/vystak-template-langchain-python/_vystak/runtime/nats_bridge.py \
        packages/python/vystak-template-langchain-python/_vystak/runtime/app_factory.py \
        packages/python/vystak-template-langchain-python/tests/test_nats_bridge_rpcs.py
git commit -m "feat(template): turnStatus and resumeDetached RPCs, park detection"
```

---

### Task 9: `TurnAccumulator.rewind`

**Files:**
- Modify: `packages/python/vystak-channel-panel/src/vystak_channel_panel/turn_stream.py:71-133`
- Test: `packages/python/vystak-channel-panel/tests/test_turn_stream_rewind.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces: `TurnAccumulator.feed_seq(seq: int, ev: PanelStreamEvent)`; `TurnAccumulator.rewind(to_seq: int)`; `TurnAccumulator.retained() -> list[tuple[int, PanelStreamEvent]]`. Existing `feed()`, `content`, `parts()`, `has_output` keep working unchanged.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_turn_stream_rewind.py
from vystak_channel_panel.responses_client import PanelStreamEvent
from vystak_channel_panel.turn_stream import TurnAccumulator


def _tok(text):
    return PanelStreamEvent(type="token", text=text)


def test_rewind_drops_events_above_to_seq():
    acc = TurnAccumulator()
    for seq, text in enumerate(["a", "b", "c", "d"]):
        acc.feed_seq(seq, _tok(text))
    acc.rewind(1)
    assert acc.content == "ab"


def test_rewind_is_inclusive_of_to_seq():
    acc = TurnAccumulator()
    acc.feed_seq(0, _tok("keep"))
    acc.rewind(0)
    assert acc.content == "keep"


def test_rewind_to_negative_clears_everything():
    acc = TurnAccumulator()
    acc.feed_seq(0, _tok("gone"))
    acc.rewind(-1)
    assert acc.content == ""
    assert acc.has_output is False


def test_feeding_after_rewind_continues_cleanly():
    acc = TurnAccumulator()
    acc.feed_seq(0, _tok("a"))
    acc.feed_seq(1, _tok("STALE"))
    acc.rewind(0)
    acc.feed_seq(1, _tok("b"))
    assert acc.content == "ab"


def test_rewind_refolds_tool_parts():
    acc = TurnAccumulator()
    acc.feed_seq(0, _tok("before "))
    acc.feed_seq(1, PanelStreamEvent(type="tool_call", tool_call_id="c1",
                                     tool_name="search", arguments="{}"))
    acc.feed_seq(2, PanelStreamEvent(type="tool_result", tool_call_id="c1",
                                     output="hit", is_error=False))
    acc.feed_seq(3, _tok("STALE"))
    acc.rewind(2)
    parts = acc.parts()
    assert [p["type"] for p in parts] == ["text", "tool"]
    assert acc.content == "before "


def test_retained_returns_surviving_pairs():
    acc = TurnAccumulator()
    acc.feed_seq(0, _tok("a"))
    acc.feed_seq(1, _tok("b"))
    acc.rewind(0)
    assert [s for s, _ in acc.retained()] == [0]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/python/vystak-channel-panel/tests/test_turn_stream_rewind.py -v`
Expected: FAIL with `AttributeError: 'TurnAccumulator' object has no attribute 'feed_seq'`

- [ ] **Step 3: Write minimal implementation**

Keep the existing fold, add a retained log and re-fold on rewind:

```python
def __init__(self) -> None:
    ...
    self._log: list[tuple[int, PanelStreamEvent]] = []

def feed_seq(self, seq: int, ev: PanelStreamEvent) -> None:
    self._log.append((seq, ev))
    self.feed(ev)

def retained(self) -> list[tuple[int, PanelStreamEvent]]:
    return list(self._log)

def rewind(self, to_seq: int) -> None:
    """Discard events above `to_seq` (inclusive of `to_seq` itself) and
    re-fold. A resumed run re-emits exactly these, so keeping them would
    duplicate output."""
    survivors = [(s, e) for s, e in self._log if s <= to_seq]
    self.text_chunks.clear()
    self._current_text.clear()
    self.msg_parts.clear()
    self._pending_tool_calls.clear()
    self._log = []
    for s, e in survivors:
        self.feed_seq(s, e)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest packages/python/vystak-channel-panel/tests/ -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-channel-panel/src/vystak_channel_panel/turn_stream.py \
        packages/python/vystak-channel-panel/tests/test_turn_stream_rewind.py
git commit -m "feat(panel): rewind support in TurnAccumulator"
```

---

### Task 10: Idle no longer concludes a turn

The blocker: `stream_turn_events` raises `TurnStreamIdle` after 120s and `run_turn_persister` treats it as the turn ending, writing a partial row and clearing `active_turn_id`. A restart plus re-drive routinely exceeds 120s.

**Files:**
- Modify: `packages/python/vystak-channel-panel/src/vystak_channel_panel/turn_worker.py`
- Modify: `packages/python/vystak-channel-panel/src/vystak_channel_panel/nats_client.py`
- Test: `packages/python/vystak-channel-panel/tests/test_turn_worker_idle.py` (create)

**Interfaces:**
- Consumes: Task 8's `responses/turnStatus`.
- Produces: `NatsPanelClient.turn_status(agent_name: str, turn_id: str) -> str`; `run_turn_persister(rt, conv_id, turn_id, subject, deadline_s: float = 900.0)`. The persister resolves `agent_name` from the conversation record it already loads — `nats_client` must not learn about conversations.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_turn_worker_idle.py
import pytest

from vystak_channel_panel.turn_worker import run_turn_persister


@pytest.mark.asyncio
async def test_idle_with_running_status_keeps_waiting(persister_harness):
    h = persister_harness(
        event_batches=[[], [("done", "resp_1")]],  # idle, then the reply
        turn_status="running",
    )
    await run_turn_persister(h.rt, "c1", "t1", "s.t1")

    assert h.reattach_count == 2
    assert h.persisted_rows[0]["response_id"] == "resp_1"
    assert h.cleared_active_turn is True


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["done", "failed", "unknown"])
async def test_idle_with_terminal_status_concludes(persister_harness, status):
    h = persister_harness(event_batches=[[]], turn_status=status)
    await run_turn_persister(h.rt, "c1", "t1", "s.t1")
    assert h.reattach_count == 1
    assert h.cleared_active_turn is True


@pytest.mark.asyncio
async def test_status_rpc_failure_keeps_waiting(persister_harness):
    """The agent being unreachable is exactly when the answer matters."""
    h = persister_harness(
        event_batches=[[], [("done", "resp_1")]],
        turn_status=RuntimeError("agent unreachable"),
    )
    await run_turn_persister(h.rt, "c1", "t1", "s.t1")
    assert h.reattach_count == 2
    assert h.persisted_rows[0]["response_id"] == "resp_1"


@pytest.mark.asyncio
async def test_overall_deadline_concludes_as_errored(persister_harness):
    h = persister_harness(
        event_batches=[[]] * 50,
        turn_status="running",
        clock=[0.0, 901.0],
    )
    await run_turn_persister(h.rt, "c1", "t1", "s.t1", deadline_s=900.0)
    assert h.cleared_active_turn is True
    assert h.reattach_count < 50


@pytest.mark.asyncio
async def test_parked_status_keeps_waiting(persister_harness):
    h = persister_harness(event_batches=[[], [("done", "resp_1")]], turn_status="parked")
    await run_turn_persister(h.rt, "c1", "t1", "s.t1")
    assert h.reattach_count == 2
```

Add a `persister_harness` fixture to `packages/python/vystak-channel-panel/tests/conftest.py`: a fake `rt` whose `nats_client.stream_turn_events` yields one batch per attach then raises `TurnStreamIdle`, whose `turn_status` returns the configured value or raises it, an injectable monotonic clock, and a recording `panel_store`.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/python/vystak-channel-panel/tests/test_turn_worker_idle.py -v`
Expected: FAIL — `run_turn_persister()` got an unexpected keyword argument `deadline_s`

- [ ] **Step 3: Write minimal implementation**

Wrap the consume loop so `TurnStreamIdle` consults the agent instead of concluding:

```python
WAITING_STATUSES = {"running", "parked"}


async def run_turn_persister(rt, conv_id, turn_id, subject, deadline_s: float = 900.0):
    started = rt.monotonic()
    conv = await rt.panel_store.get_conversation(conv_id)
    agent_name = conv.agent
    ...
    while True:
        try:
            async for seq, ev in rt.nats_client.stream_turn_events(subject):
                if ev.type == "done":
                    response_id = ev.response_id or None
                    break
                if ev.type == "error":
                    errored = True
                    break
                if ev.type == "rewind":
                    acc.rewind(ev.to_seq)
                    continue
                acc.feed_seq(seq, ev)
            else:
                continue
            break
        except TurnStreamIdle:
            if rt.monotonic() - started >= deadline_s:
                logger.warning("turn deadline conv=%s turn=%s", conv_id, turn_id)
                errored = True
                break
            try:
                status = await rt.nats_client.turn_status(agent_name, turn_id)
            except Exception:  # noqa: BLE001 — unreachable agent means keep waiting
                logger.info("turnStatus unreachable conv=%s turn=%s", conv_id, turn_id)
                continue
            if status in WAITING_STATUSES:
                continue
            errored = True
            break
```

Everything from the existing persist/cleanup block down stays as-is. Replay-from-0 on re-attach is why the accumulator must be reset at the top of each attach — reuse `TurnAccumulator()` per attach.

Add `turn_status` to `NatsPanelClient`, sending `responses/turnStatus` on the agent's tasks subject with a short request timeout.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/python/vystak-channel-panel/tests/ -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-channel-panel/src/vystak_channel_panel/turn_worker.py \
        packages/python/vystak-channel-panel/src/vystak_channel_panel/nats_client.py \
        packages/python/vystak-channel-panel/tests/test_turn_worker_idle.py \
        packages/python/vystak-channel-panel/tests/conftest.py
git commit -m "fix(panel): idle means still working, not concluded"
```

---

### Task 11: Rewind reaches the browser

**Files:**
- Modify: `packages/python/vystak-channel-panel/src/vystak_channel_panel/turn_stream.py` (add `rewind` to `translate_responses_event` and `browser_frame`)
- Modify: `packages/python/vystak-channel-panel/src/vystak_channel_panel/routes_messages.py`
- Test: `packages/python/vystak-channel-panel/tests/test_routes_messages_rewind.py` (create)

**Interfaces:**
- Consumes: Task 9.
- Produces: `PanelStreamEvent(type="rewind", to_seq=int)`; browser frame `{"type": "reset"}` followed by re-emitted retained frames.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_routes_messages_rewind.py
import pytest

from vystak_channel_panel.turn_stream import browser_frame, translate_responses_event


def test_translate_recognizes_rewind():
    ev = translate_responses_event({"type": "vystak.turn.rewind", "to_seq": 4}, {})
    assert ev.type == "rewind"
    assert ev.to_seq == 4


def test_browser_frame_for_rewind_is_reset():
    from vystak_channel_panel.responses_client import PanelStreamEvent
    assert browser_frame(PanelStreamEvent(type="rewind", to_seq=4)) == {"type": "reset"}


@pytest.mark.asyncio
async def test_proxy_emits_reset_then_replays_prefix(sse_proxy_harness):
    h = sse_proxy_harness(events=[
        (0, {"type": "response.output_text.delta", "delta": "keep"}),
        (1, {"type": "response.output_text.delta", "delta": "STALE"}),
        (2, {"type": "vystak.turn.rewind", "to_seq": 0}),
        (3, {"type": "response.output_text.delta", "delta": "-new"}),
    ])
    frames = await h.collect()
    kinds = [f["type"] for f in frames]
    assert "reset" in kinds
    reset_at = kinds.index("reset")
    after = [f for f in frames[reset_at + 1:] if f["type"] == "delta"]
    assert "".join(f["text"] for f in after) == "keep-new"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/python/vystak-channel-panel/tests/test_routes_messages_rewind.py -v`
Expected: FAIL — `translate_responses_event` returns `None` for the rewind type

- [ ] **Step 3: Write minimal implementation**

Add `to_seq: int = -1` to `PanelStreamEvent`. In `translate_responses_event`, before the final `return None`:

```python
if event_type == "vystak.turn.rewind":
    return PanelStreamEvent(type="rewind", to_seq=int(data.get("to_seq", -1)))
```

In `browser_frame`, before the error fallback: `if ev.type == "rewind": return {"type": "reset"}`.

In the SSE proxy in `routes_messages.py`, keep a `TurnAccumulator` alongside the forwarding so a rewind can replay:

```python
if ev.type == "rewind":
    acc.rewind(ev.to_seq)
    yield _sse(browser_frame(ev))
    for _s, kept in acc.retained():
        yield _sse(browser_frame(kept))
    continue
acc.feed_seq(seq, ev)
yield _sse(browser_frame(ev))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/python/vystak-channel-panel/tests/ -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-channel-panel/src/vystak_channel_panel/turn_stream.py \
        packages/python/vystak-channel-panel/src/vystak_channel_panel/responses_client.py \
        packages/python/vystak-channel-panel/src/vystak_channel_panel/routes_messages.py \
        packages/python/vystak-channel-panel/tests/test_routes_messages_rewind.py
git commit -m "feat(panel): translate rewind into a browser reset + prefix replay"
```

---

### Task 12: Next.js adapter handles `reset`

**Files:**
- Modify: `packages/typescript/vystak-panel/lib/panel-stream.ts` (locate `panelStreamToUIChunks` first: `rg -l panelStreamToUIChunks packages/typescript/vystak-panel`)
- Test: alongside the existing adapter tests in the same package.

**Interfaces:**
- Consumes: Task 11's `{"type": "reset"}` frame.
- Produces: adapter clears in-flight assistant text/tool state on `reset`.

- [ ] **Step 1: Write the failing test**

```typescript
import { describe, expect, it } from "vitest";
import { panelStreamToUIChunks } from "./panel-stream";

describe("panelStreamToUIChunks", () => {
  it("clears in-flight text on reset", async () => {
    const chunks = await collect(panelStreamToUIChunks(frames([
      { type: "delta", text: "stale" },
      { type: "reset" },
      { type: "delta", text: "fresh" },
    ])));
    expect(renderText(chunks)).toBe("fresh");
  });

  it("passes through streams with no reset unchanged", async () => {
    const chunks = await collect(panelStreamToUIChunks(frames([
      { type: "delta", text: "a" },
      { type: "delta", text: "b" },
    ])));
    expect(renderText(chunks)).toBe("ab");
  });
});
```

Reuse the `frames` / `collect` / `renderText` helpers from the existing adapter test file; if none exist, define them locally.

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm --filter vystak-panel test`
Expected: FAIL — `reset` is an unknown frame type, text renders as `"stalefresh"`

- [ ] **Step 3: Write minimal implementation**

In the adapter's frame switch, handle `reset` by emitting the same "start a fresh assistant message" chunk sequence the adapter already produces on a fresh resume attach, discarding accumulated text and pending tool-call state.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pnpm --filter vystak-panel test && pnpm --filter vystak-panel run typecheck`
Expected: PASS (both are live CI gates)

- [ ] **Step 5: Commit**

```bash
git add packages/typescript/vystak-panel/lib/
git commit -m "feat(panel-ui): reset in-flight assistant message on rewind"
```

---

### Task 13: Always mount an agent data volume

**Files:**
- Modify: `packages/python/vystak-provider-docker/src/vystak_provider_docker/nodes/agent.py:243-255`
- Test: `packages/python/vystak-provider-docker/tests/test_agent_node_volume.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces: agents with no `sessions:` get volume `vystak-agent-<name>-data` bound at `/data`.

- [ ] **Step 1: Write the failing test**

```python
def test_sessionless_agent_gets_a_data_volume(agent_node_factory):
    node = agent_node_factory(sessions=None, name="solo")
    volumes = node._build_volumes(context={})
    assert volumes["vystak-agent-solo-data"] == {"bind": "/data", "mode": "rw"}


def test_declared_sessions_volume_still_wins(agent_node_factory):
    node = agent_node_factory(sessions="declared", name="solo")
    volumes = node._build_volumes(context={"sessions": _result("vystak-sessions-vol")})
    assert volumes["vystak-sessions-vol"]["bind"] == "/data"
    assert "vystak-agent-solo-data" not in volumes
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/python/vystak-provider-docker/tests/test_agent_node_volume.py -v`
Expected: FAIL — no `_build_volumes`, or no default volume

- [ ] **Step 3: Write minimal implementation**

Extract the inline volume assembly into `_build_volumes(context)` and add the fallback: when `self._agent.sessions` is `None`, create/mount `vystak-agent-<name>-data` at `/data`. Ensure the volume is created in `provision()` and removed in `destroy()` alongside the agent's other resources.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/python/vystak-provider-docker/tests/ -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-provider-docker/src/vystak_provider_docker/nodes/agent.py \
        packages/python/vystak-provider-docker/tests/test_agent_node_volume.py
git commit -m "feat(docker): always mount a per-agent data volume"
```

---

### Task 14: Example — `examples/docker-panel-durable`

Per CLAUDE.md this is definition-of-done, not an extra.

**Files:**
- Create: `examples/docker-panel-durable/vystak.yaml`, `tools/slow_steps.py`, `README.md`, `.env.example`

- [ ] **Step 1: Copy the NATS panel example as the base**

```bash
cp -r examples/docker-panel-nats examples/docker-panel-durable
rm -rf examples/docker-panel-durable/_vystak
```

`_vystak/` is a template snapshot; `vystak init` regenerates it. Shipping a stale one is a known repo problem (`examples/docker-chat/_vystak`) — do not commit one here.

- [ ] **Step 2: Add a deliberately slow multi-step tool**

```python
# tools/slow_steps.py
import asyncio


async def slow_step(label: str) -> str:
    """Take a slow step in a multi-step job. Call once per step, in order."""
    await asyncio.sleep(20)
    return f"step {label} complete"
```

Register it in `vystak.yaml` and give the agent a prompt instructing it to call `slow_step` for steps one through four in sequence. This makes the restart window wide enough to hit by hand.

- [ ] **Step 3: Write the README**

Document: `vystak init .`, `vystak apply`, open the panel, send "run the four-step job", then mid-run `docker restart vystak-<agent>`, and observe the reply still lands and the browser resets to the committed prefix rather than duplicating it. Use `<your-api-key>` placeholders only.

- [ ] **Step 4: Verify it deploys**

Run: `cd examples/docker-panel-durable && vystak init . && vystak plan`
Expected: a clean plan with the agent, panel channel, NATS broker, and the agent data volume.

- [ ] **Step 5: Commit**

```bash
git add examples/docker-panel-durable
git commit -m "example: docker-panel-durable exercising turn resume across restart"
```

---

### Task 15: Release cells

**Files:**
- Create: `packages/python/vystak-provider-docker/tests/release/test_durable_turns.py`

**Interfaces:**
- Consumes: the `project` and `docker_required` fixtures from `tests/release/conftest.py`.

- [ ] **Step 1: Write the deterministic restart cell**

Marked `release_integration`, sentinel credentials, no live LLM. Deploy `docker-panel-durable`, dispatch a turn, `docker restart` the agent, then assert the mechanical facts that hold regardless of LLM behavior: the journal row is still present on the agent's data volume, the re-drive is logged, `attempts` incremented, and the panel has not concluded the turn at the 120s mark. This is the gate that always runs locally — the live cell below auto-skips on sentinel keys and never runs in GitHub Actions.

- [ ] **Step 2: Write the live end-to-end cell**

Marked `release_live_chat` (real `ANTHROPIC_API_KEY`). Start the four-step job, `docker restart` the agent mid-tool, then assert exactly one assistant row lands carrying its `turn_id`, `active_turn_id` is cleared, and `slow_step` ran four times total — not five. The tool-call count is the assertion that proves resume-from-checkpoint rather than re-run.

- [ ] **Step 3: Run the deterministic cell**

Run: `uv run pytest packages/python/vystak-provider-docker/tests/release/test_durable_turns.py -v -m release_integration`
Expected: PASS

- [ ] **Step 4: Run the live cell**

Run: `export ANTHROPIC_API_KEY=sk-ant-... && uv run pytest packages/python/vystak-provider-docker/tests/release/test_durable_turns.py -v -m release_live_chat`
Expected: PASS (costs a few cents)

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-provider-docker/tests/release/test_durable_turns.py
git commit -m "test(release): durable turn resume across agent restart"
```

---

### Task 16: Documentation

**Files:**
- Create: `docs/durable-execution.md`
- Modify: `website/` concept page + `CLAUDE.md` (release-cell map, examples list)

- [ ] **Step 1: Write `docs/durable-execution.md`**

Cover: what survives a restart and what does not; the NATS-only constraint; the checkpointer default change and that **an existing deployment must be destroyed and re-applied to gain the data volume**, because the `Agent` schema is unchanged so `vystak plan` shows no diff; the 3-attempt cap; the 15-minute panel deadline; and the park/`interrupt()` seam as the foundation for future approvals.

- [ ] **Step 2: Add the website concept page**

Follow the structure of the existing scheduled-tasks concept page.

- [ ] **Step 3: Update `CLAUDE.md`**

Add `docker-panel-durable` to the examples list and `test_durable_turns.py` to the Docker release-cell map.

- [ ] **Step 4: Build the docs site**

Run: `just docs-build`
Expected: clean build

- [ ] **Step 5: Commit**

```bash
git add docs/durable-execution.md website/ CLAUDE.md
git commit -m "docs: durable execution"
```

---

## Final verification

- [ ] Run the four live CI gates: `just ci-live` — all green.
- [ ] Run the Docker release suite: `uv run pytest packages/python/vystak-provider-docker/tests/release/ -v -m "release_smoke or release_integration"`.
- [ ] Confirm no edits landed in `packages/python/vystak-cli/src/vystak_cli/templates/` (`git status` should never show it — it is gitignored).
- [ ] Scan the full diff for credentials before the final push.
