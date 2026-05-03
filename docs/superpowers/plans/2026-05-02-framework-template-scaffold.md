# Framework Template Scaffold (No-Codegen Agents) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `vystak-adapter-langchain` (codegen) with a real `vystak-template-langchain-python` package whose source is copied into the user's project at `vystak init` time and refreshed by `vystak update`.

**Architecture:** Real Python modules under `_vystak/runtime/` inside a scaffolded user project. Files outside `_vystak/` are user-owned; files inside are managed (overwritten by `update`). New `Agent.framework: str` field selects the template registry entry. CLI bundles the template tree at wheel-build time; falls back to sibling-workspace path during editable installs.

**Tech Stack:** Python 3.11+, FastAPI, LangChain/LangGraph 1.x, Pydantic v2, pytest, hatchling, uv workspace.

**Spec:** `docs/superpowers/specs/2026-05-02-framework-template-design.md`

**Phasing:** 9 phases land as separate PRs. The codegen path stays alive through Phase 7; Phase 8 migrates examples; Phase 9 deletes the codegen package.

---

## Phase 0 — Scaffold the template package

Create `vystak-template-langchain-python` as a workspace member. Empty runtime, working pytest harness, listed in workspace `pyproject.toml`. Codegen path untouched.

### Task 0.1: Create package skeleton

**Files:**
- Create: `packages/python/vystak-template-langchain-python/pyproject.toml`
- Create: `packages/python/vystak-template-langchain-python/README.md`
- Create: `packages/python/vystak-template-langchain-python/_vystak/__init__.py`
- Create: `packages/python/vystak-template-langchain-python/_vystak/runtime/__init__.py`
- Create: `packages/python/vystak-template-langchain-python/_vystak/manifest.template.json`
- Create: `packages/python/vystak-template-langchain-python/server.py`
- Create: `packages/python/vystak-template-langchain-python/Dockerfile`
- Create: `packages/python/vystak-template-langchain-python/vystak.yaml`
- Create: `packages/python/vystak-template-langchain-python/.env.example`
- Create: `packages/python/vystak-template-langchain-python/.gitignore`
- Create: `packages/python/vystak-template-langchain-python/requirements.txt`
- Create: `packages/python/vystak-template-langchain-python/tools/__init__.py`
- Create: `packages/python/vystak-template-langchain-python/tests/__init__.py`
- Create: `packages/python/vystak-template-langchain-python/tests/conftest.py`

- [ ] **Step 1: Create directory tree**

```bash
mkdir -p packages/python/vystak-template-langchain-python/{_vystak/runtime,tools,tests}
```

- [ ] **Step 2: Write `pyproject.toml`**

```toml
[project]
name = "vystak-template-langchain-python"
version = "0.1.0"
description = "Vystak LangChain/LangGraph agent template — copied into user projects at init time."
requires-python = ">=3.11"
dependencies = [
    "vystak",
    "fastapi>=0.115",
    "uvicorn>=0.34",
    "langchain>=1.1",
    "langgraph>=1.1",
    "langchain-anthropic>=0.3",
    "langchain-openai>=0.3",
    "httpx>=0.28",
    "pydantic>=2.7",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["_vystak"]

[tool.uv.sources]
vystak = { workspace = true }
```

- [ ] **Step 3: Write `README.md` (one-line stub)**

```markdown
# vystak-template-langchain-python

LangChain/LangGraph agent template for Vystak. Source is bundled into `vystak-cli` and copied into user projects via `vystak init --framework langchain-python`.

See: `docs/superpowers/specs/2026-05-02-framework-template-design.md`.
```

- [ ] **Step 4: Write `_vystak/manifest.template.json`**

```json
{
  "schema_version": 1,
  "template": {
    "name": "langchain-python",
    "version": "0.1.0"
  },
  "vystak": {
    "schema_version": "0.5",
    "min_compat": "0.4",
    "max_compat": "0.5"
  }
}
```

- [ ] **Step 5: Write empty starter files**

`_vystak/__init__.py` — empty.

`_vystak/runtime/__init__.py`:
```python
"""Vystak LangChain/LangGraph runtime — wired by build_agent_app."""
```

`server.py`:
```python
"""Agent entrypoint. User-owned: customize freely.
Imports from _vystak.runtime to build the FastAPI app."""

from _vystak.runtime.app_factory import build_agent_app
from _vystak.runtime.config import load_agent

agent = load_agent("vystak.yaml")
app = build_agent_app(agent)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
```

`Dockerfile`:
```dockerfile
FROM python:3.12-slim
WORKDIR /app

COPY _vystak/requirements.txt /app/_vystak/requirements.txt
RUN pip install -r /app/_vystak/requirements.txt

COPY requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt

COPY . /app
CMD ["python", "server.py"]
```

`vystak.yaml` (starter — used as the example for tests; not authoritative):
```yaml
name: example-agent
framework: langchain-python
instructions: An example agent.
model:
  provider:
    type: anthropic
  model_name: claude-sonnet-4-6
```

`.env.example`:
```
ANTHROPIC_API_KEY=sk-ant-your-key-here
```

`.gitignore`:
```
__pycache__/
*.pyc
.env
.vystak/
```

`requirements.txt` — empty file (`touch`).

`_vystak/requirements.txt`:
```
vystak
fastapi>=0.115
uvicorn>=0.34
langchain>=1.1
langgraph>=1.1
langchain-anthropic>=0.3
langchain-openai>=0.3
httpx>=0.28
```

`tools/__init__.py` — empty.

`tests/__init__.py` — empty.

`tests/conftest.py`:
```python
"""Pytest configuration for vystak-template-langchain-python tests."""

import pytest


@pytest.fixture
def tmp_agent_dir(tmp_path):
    """Provides a tmp directory with a minimal vystak.yaml."""
    (tmp_path / "vystak.yaml").write_text(
        "name: test-agent\n"
        "framework: langchain-python\n"
        "model:\n"
        "  provider:\n"
        "    type: anthropic\n"
        "  model_name: claude-sonnet-4-6\n"
    )
    return tmp_path
```

- [ ] **Step 6: Add to workspace `pyproject.toml`**

Modify `/Users/akolodkin/Developer/work/AgentsStack/pyproject.toml`. In `[tool.uv]` `dev-dependencies` array, add `"vystak-template-langchain-python",`. In `[tool.uv.sources]`, add `vystak-template-langchain-python = { workspace = true }`.

- [ ] **Step 7: Run `uv sync` and verify package resolves**

Run: `uv sync`
Expected: completes without error; `vystak-template-langchain-python` listed under installed packages.

- [ ] **Step 8: Verify pytest discovery**

Run: `uv run pytest packages/python/vystak-template-langchain-python/ -v --collect-only`
Expected: collects 0 tests (none yet) but no errors.

- [ ] **Step 9: Verify lint passes**

Run: `uv run ruff check packages/python/vystak-template-langchain-python/`
Expected: All checks passed.

- [ ] **Step 10: Commit**

```bash
git add packages/python/vystak-template-langchain-python/ pyproject.toml
git commit -m "feat(template-langchain-python): scaffold empty workspace package"
```

### Task 0.2: Add baseline smoke test

**Files:**
- Create: `packages/python/vystak-template-langchain-python/tests/test_package.py`

- [ ] **Step 1: Write smoke test**

```python
"""Sanity check: package imports and the manifest seed is parseable JSON."""

import json
from pathlib import Path


def test_package_imports():
    import _vystak
    import _vystak.runtime  # noqa: F401


def test_manifest_template_is_valid_json():
    pkg_root = Path(__file__).parent.parent
    manifest_seed = pkg_root / "_vystak" / "manifest.template.json"
    data = json.loads(manifest_seed.read_text())
    assert data["template"]["name"] == "langchain-python"
    assert data["schema_version"] == 1
    assert "min_compat" in data["vystak"]
    assert "max_compat" in data["vystak"]
```

- [ ] **Step 2: Run test**

Run: `uv run pytest packages/python/vystak-template-langchain-python/tests/test_package.py -v`
Expected: 2 passed.

- [ ] **Step 3: Commit**

```bash
git add packages/python/vystak-template-langchain-python/tests/test_package.py
git commit -m "test(template-langchain-python): baseline smoke test"
```

---

## Phase 1 — Extract A2A (TaskManager, AgentCard, A2AHandler)

Build real classes for the A2A protocol. The codegen path stays alive — these classes ship inside the new template only.

### Task 1.1: TaskManager — task store + state machine

**Files:**
- Create: `packages/python/vystak-template-langchain-python/_vystak/runtime/a2a/__init__.py`
- Create: `packages/python/vystak-template-langchain-python/_vystak/runtime/a2a/tasks.py`
- Create: `packages/python/vystak-template-langchain-python/tests/test_a2a_tasks.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_a2a_tasks.py`:
```python
"""TaskManager unit tests — task store + state transitions."""

import pytest

from _vystak.runtime.a2a.tasks import Task, TaskManager, TaskState


def test_create_task_returns_submitted_state():
    mgr = TaskManager()
    task = mgr.create(task_id="t1", message={"role": "user", "parts": [{"text": "hi"}]})
    assert task.id == "t1"
    assert task.state == TaskState.SUBMITTED


def test_transition_submitted_to_working():
    mgr = TaskManager()
    mgr.create(task_id="t1", message={})
    mgr.set_state("t1", TaskState.WORKING)
    assert mgr.get("t1").state == TaskState.WORKING


def test_invalid_transition_raises():
    mgr = TaskManager()
    mgr.create(task_id="t1", message={})
    mgr.set_state("t1", TaskState.COMPLETED)
    with pytest.raises(ValueError, match="cannot transition"):
        mgr.set_state("t1", TaskState.WORKING)


def test_get_unknown_task_returns_none():
    mgr = TaskManager()
    assert mgr.get("nope") is None


def test_cancel_marks_canceled():
    mgr = TaskManager()
    mgr.create(task_id="t1", message={})
    mgr.set_state("t1", TaskState.WORKING)
    mgr.cancel("t1")
    assert mgr.get("t1").state == TaskState.CANCELED


def test_cancel_completed_task_is_noop():
    mgr = TaskManager()
    mgr.create(task_id="t1", message={})
    mgr.set_state("t1", TaskState.COMPLETED)
    mgr.cancel("t1")
    assert mgr.get("t1").state == TaskState.COMPLETED
```

- [ ] **Step 2: Run tests, expect failure**

Run: `uv run pytest packages/python/vystak-template-langchain-python/tests/test_a2a_tasks.py -v`
Expected: ImportError — `_vystak.runtime.a2a.tasks` does not exist.

- [ ] **Step 3: Implement TaskManager**

Create `_vystak/runtime/a2a/__init__.py`:
```python
"""A2A protocol runtime — task manager, agent card, dispatch."""
```

Create `_vystak/runtime/a2a/tasks.py`:
```python
"""A2A task store + state machine."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class TaskState(str, Enum):
    SUBMITTED = "submitted"
    WORKING = "working"
    INPUT_REQUIRED = "input-required"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"


_TERMINAL: set[TaskState] = {TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELED}


@dataclass
class Task:
    id: str
    state: TaskState = TaskState.SUBMITTED
    message: dict = field(default_factory=dict)
    artifacts: list[dict] = field(default_factory=list)
    history: list[dict] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class TaskManager:
    """In-memory task store. Per-process; not durable across restarts."""

    def __init__(self) -> None:
        self._tasks: dict[str, Task] = {}

    def create(self, task_id: str, message: dict) -> Task:
        task = Task(id=task_id, message=message)
        self._tasks[task_id] = task
        return task

    def get(self, task_id: str) -> Task | None:
        return self._tasks.get(task_id)

    def set_state(self, task_id: str, new_state: TaskState) -> None:
        task = self._tasks[task_id]
        if task.state in _TERMINAL and new_state != task.state:
            raise ValueError(f"cannot transition from terminal state {task.state} to {new_state}")
        task.state = new_state
        task.updated_at = datetime.now(timezone.utc)

    def cancel(self, task_id: str) -> None:
        task = self._tasks[task_id]
        if task.state in _TERMINAL:
            return
        task.state = TaskState.CANCELED
        task.updated_at = datetime.now(timezone.utc)

    def append_artifact(self, task_id: str, artifact: dict) -> None:
        self._tasks[task_id].artifacts.append(artifact)

    def append_history(self, task_id: str, message: dict) -> None:
        self._tasks[task_id].history.append(message)
```

- [ ] **Step 4: Run tests, expect pass**

Run: `uv run pytest packages/python/vystak-template-langchain-python/tests/test_a2a_tasks.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-template-langchain-python/_vystak/runtime/a2a/ packages/python/vystak-template-langchain-python/tests/test_a2a_tasks.py
git commit -m "feat(template): TaskManager + Task state machine"
```

### Task 1.2: AgentCard — render the public agent metadata

**Files:**
- Create: `packages/python/vystak-template-langchain-python/_vystak/runtime/a2a/card.py`
- Create: `packages/python/vystak-template-langchain-python/tests/test_a2a_card.py`

- [ ] **Step 1: Write failing tests**

```python
"""AgentCard renders the /.well-known/agent.json shape from an Agent schema."""

from vystak.schema.agent import Agent
from vystak.schema.model import Model
from vystak.schema.provider import Provider
from vystak.schema.skill import Skill

from _vystak.runtime.a2a.card import AgentCard


def _agent(skills: list[Skill] | None = None) -> Agent:
    return Agent(
        name="weather",
        instructions="A helpful weather agent.",
        model=Model(
            provider=Provider(type="anthropic"),
            model_name="claude-sonnet-4-6",
        ),
        skills=skills or [],
    )


def test_render_minimal_agent():
    card = AgentCard(_agent()).render()
    assert card["name"] == "weather"
    assert card["description"] == "A helpful weather agent."
    assert card["capabilities"]["streaming"] is True
    assert card["capabilities"]["pushNotifications"] is False
    assert card["skills"] == []


def test_render_includes_skills():
    skills = [Skill(name="forecast", description="Get weather forecast", tools=["get_weather"])]
    card = AgentCard(_agent(skills=skills)).render()
    assert len(card["skills"]) == 1
    assert card["skills"][0]["id"] == "forecast"
    assert card["skills"][0]["name"] == "forecast"
    assert card["skills"][0]["description"] == "Get weather forecast"


def test_render_default_input_output_modes():
    card = AgentCard(_agent()).render()
    assert "text/plain" in card["defaultInputModes"]
    assert "text/plain" in card["defaultOutputModes"]


def test_render_omits_description_when_no_instructions():
    agent = _agent()
    agent.instructions = None
    card = AgentCard(agent).render()
    assert card["description"] == ""
```

- [ ] **Step 2: Run tests, expect failure**

Run: `uv run pytest packages/python/vystak-template-langchain-python/tests/test_a2a_card.py -v`
Expected: ImportError on `_vystak.runtime.a2a.card`.

- [ ] **Step 3: Implement**

Create `_vystak/runtime/a2a/card.py`:
```python
"""AgentCard — renders /.well-known/agent.json from the Agent schema."""

from vystak.schema.agent import Agent


class AgentCard:
    """Builds the A2A Agent Card payload for /.well-known/agent.json."""

    def __init__(self, agent: Agent) -> None:
        self._agent = agent

    def render(self) -> dict:
        a = self._agent
        return {
            "name": a.name,
            "description": a.instructions or "",
            "version": "1.0.0",
            "capabilities": {
                "streaming": True,
                "pushNotifications": False,
            },
            "defaultInputModes": ["text/plain"],
            "defaultOutputModes": ["text/plain"],
            "skills": [
                {
                    "id": skill.name,
                    "name": skill.name,
                    "description": skill.description or "",
                }
                for skill in a.skills
            ],
        }
```

- [ ] **Step 4: Run tests, expect pass**

Run: `uv run pytest packages/python/vystak-template-langchain-python/tests/test_a2a_card.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-template-langchain-python/_vystak/runtime/a2a/card.py packages/python/vystak-template-langchain-python/tests/test_a2a_card.py
git commit -m "feat(template): AgentCard renderer"
```

### Task 1.3: A2AHandler — JSON-RPC dispatch (non-streaming)

**Files:**
- Create: `packages/python/vystak-template-langchain-python/_vystak/runtime/a2a/handler.py`
- Create: `packages/python/vystak-template-langchain-python/tests/test_a2a_handler.py`

- [ ] **Step 1: Write failing tests for `tasks/send`**

```python
"""A2AHandler dispatch — non-streaming JSON-RPC methods."""

import pytest

from _vystak.runtime.a2a.handler import A2AHandler
from _vystak.runtime.a2a.tasks import TaskManager, TaskState


class FakeGraph:
    """Minimal CompiledGraph stand-in returning a canned final response."""

    def __init__(self, response_text: str = "ok") -> None:
        self._text = response_text

    async def ainvoke(self, input, config):  # noqa: ANN001
        return {"messages": [{"role": "assistant", "content": self._text}]}


@pytest.fixture
def handler():
    return A2AHandler(agent=None, graph=FakeGraph("hello"), task_manager=TaskManager())


@pytest.mark.asyncio
async def test_tasks_send_returns_completed_with_text(handler):
    payload = {
        "jsonrpc": "2.0",
        "id": "rpc-1",
        "method": "tasks/send",
        "params": {
            "id": "task-1",
            "message": {"role": "user", "parts": [{"text": "hi"}]},
        },
    }
    result = await handler.dispatch(payload)
    assert result["jsonrpc"] == "2.0"
    assert result["id"] == "rpc-1"
    assert result["result"]["status"]["state"] == "completed"
    assert result["result"]["status"]["message"]["parts"][0]["text"] == "hello"


@pytest.mark.asyncio
async def test_tasks_get_returns_stored_task(handler):
    await handler.dispatch({
        "jsonrpc": "2.0", "id": "1", "method": "tasks/send",
        "params": {"id": "task-1", "message": {"role": "user", "parts": [{"text": "hi"}]}},
    })
    result = await handler.dispatch({
        "jsonrpc": "2.0", "id": "2", "method": "tasks/get",
        "params": {"id": "task-1"},
    })
    assert result["result"]["id"] == "task-1"


@pytest.mark.asyncio
async def test_tasks_cancel_marks_canceled(handler):
    handler.task_manager.create("task-1", {})
    handler.task_manager.set_state("task-1", TaskState.WORKING)
    result = await handler.dispatch({
        "jsonrpc": "2.0", "id": "3", "method": "tasks/cancel",
        "params": {"id": "task-1"},
    })
    assert result["result"]["status"]["state"] == "canceled"


@pytest.mark.asyncio
async def test_unknown_method_returns_jsonrpc_error(handler):
    result = await handler.dispatch({
        "jsonrpc": "2.0", "id": "x", "method": "tasks/unknown", "params": {},
    })
    assert "error" in result
    assert result["error"]["code"] == -32601


@pytest.mark.asyncio
async def test_get_unknown_task_returns_jsonrpc_error(handler):
    result = await handler.dispatch({
        "jsonrpc": "2.0", "id": "y", "method": "tasks/get",
        "params": {"id": "missing"},
    })
    assert result["error"]["code"] == -32602
```

- [ ] **Step 2: Run tests, expect failure**

Run: `uv run pytest packages/python/vystak-template-langchain-python/tests/test_a2a_handler.py -v`
Expected: ImportError on `_vystak.runtime.a2a.handler`.

- [ ] **Step 3: Implement non-streaming dispatch**

Create `_vystak/runtime/a2a/handler.py`:
```python
"""A2AHandler — JSON-RPC dispatch over /a2a."""

from typing import Any

from _vystak.runtime.a2a.tasks import TaskManager, TaskState


class A2AHandler:
    def __init__(self, agent, graph, task_manager: TaskManager) -> None:  # noqa: ANN001
        self.agent = agent
        self.graph = graph
        self.task_manager = task_manager

    async def dispatch(self, payload: dict) -> dict:
        method = payload.get("method")
        rpc_id = payload.get("id")
        params = payload.get("params") or {}

        try:
            if method == "tasks/send":
                result = await self._tasks_send(params)
            elif method == "tasks/get":
                result = self._tasks_get(params)
            elif method == "tasks/cancel":
                result = self._tasks_cancel(params)
            else:
                return _err(rpc_id, -32601, f"Method not found: {method}")
        except _RpcError as e:
            return _err(rpc_id, e.code, e.message)

        return {"jsonrpc": "2.0", "id": rpc_id, "result": result}

    async def _tasks_send(self, params: dict) -> dict:
        task_id = params["id"]
        message = params.get("message", {})
        self.task_manager.create(task_id, message)
        self.task_manager.set_state(task_id, TaskState.WORKING)

        config = {"configurable": {"thread_id": task_id}}
        result = await self.graph.ainvoke({"messages": [_to_lc_message(message)]}, config)

        last = result["messages"][-1]
        self.task_manager.set_state(task_id, TaskState.COMPLETED)
        return _task_payload(self.task_manager.get(task_id), final_text=_extract_text(last))

    def _tasks_get(self, params: dict) -> dict:
        task = self.task_manager.get(params["id"])
        if task is None:
            raise _RpcError(-32602, f"Task not found: {params['id']}")
        return _task_payload(task)

    def _tasks_cancel(self, params: dict) -> dict:
        task = self.task_manager.get(params["id"])
        if task is None:
            raise _RpcError(-32602, f"Task not found: {params['id']}")
        self.task_manager.cancel(params["id"])
        return _task_payload(self.task_manager.get(params["id"]))


class _RpcError(Exception):
    def __init__(self, code: int, message: str) -> None:
        self.code = code
        self.message = message


def _err(rpc_id: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": code, "message": message}}


def _to_lc_message(msg: dict) -> dict:
    parts = msg.get("parts", [])
    text = "".join(p.get("text", "") for p in parts)
    return {"role": msg.get("role", "user"), "content": text}


def _extract_text(message: Any) -> str:
    if isinstance(message, dict):
        return str(message.get("content", ""))
    return getattr(message, "content", "")


def _task_payload(task, final_text: str | None = None) -> dict:
    payload = {
        "id": task.id,
        "status": {
            "state": task.state.value,
        },
    }
    if final_text is not None:
        payload["status"]["message"] = {
            "role": "assistant",
            "parts": [{"text": final_text}],
        }
    return payload
```

- [ ] **Step 4: Run tests, expect pass**

Run: `uv run pytest packages/python/vystak-template-langchain-python/tests/test_a2a_handler.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-template-langchain-python/_vystak/runtime/a2a/handler.py packages/python/vystak-template-langchain-python/tests/test_a2a_handler.py
git commit -m "feat(template): A2AHandler with tasks/send, tasks/get, tasks/cancel"
```

### Task 1.4: A2AHandler — `tasks/sendSubscribe` SSE streaming

**Files:**
- Modify: `packages/python/vystak-template-langchain-python/_vystak/runtime/a2a/handler.py`
- Modify: `packages/python/vystak-template-langchain-python/tests/test_a2a_handler.py`

- [ ] **Step 1: Add streaming test**

Append to `tests/test_a2a_handler.py`:
```python
class FakeStreamingGraph:
    """Yields canned LangGraph stream events."""

    def __init__(self, events: list[dict]) -> None:
        self._events = events

    async def astream_events(self, input, config, version="v2"):  # noqa: ANN001
        for ev in self._events:
            yield ev


@pytest.mark.asyncio
async def test_tasks_send_subscribe_yields_sse_frames():
    events = [
        {"event": "on_chat_model_stream", "data": {"chunk": {"content": "hel"}}},
        {"event": "on_chat_model_stream", "data": {"chunk": {"content": "lo"}}},
    ]
    handler = A2AHandler(agent=None, graph=FakeStreamingGraph(events), task_manager=TaskManager())

    frames = []
    async for frame in handler.stream_dispatch({
        "jsonrpc": "2.0", "id": "rpc-1", "method": "tasks/sendSubscribe",
        "params": {"id": "task-1", "message": {"role": "user", "parts": [{"text": "hi"}]}},
    }):
        frames.append(frame)

    assert any("data:" in f for f in frames)
    joined = "".join(frames)
    assert "task-1" in joined
    assert "hel" in joined
    assert "lo" in joined
```

- [ ] **Step 2: Run, expect AttributeError on `stream_dispatch`**

Run: `uv run pytest packages/python/vystak-template-langchain-python/tests/test_a2a_handler.py::test_tasks_send_subscribe_yields_sse_frames -v`
Expected: `AttributeError: 'A2AHandler' object has no attribute 'stream_dispatch'`.

- [ ] **Step 3: Add `stream_dispatch` to handler**

Append to `_vystak/runtime/a2a/handler.py` (inside `A2AHandler`):
```python
    async def stream_dispatch(self, payload: dict):
        """Yields SSE frames (str, ending in \\n\\n) for tasks/sendSubscribe."""
        method = payload.get("method")
        rpc_id = payload.get("id")
        params = payload.get("params") or {}
        if method != "tasks/sendSubscribe":
            yield _sse(_err(rpc_id, -32601, f"Method not found: {method}"))
            return

        task_id = params["id"]
        message = params.get("message", {})
        self.task_manager.create(task_id, message)
        self.task_manager.set_state(task_id, TaskState.WORKING)
        yield _sse({"jsonrpc": "2.0", "id": rpc_id, "result": _task_payload(self.task_manager.get(task_id))})

        config = {"configurable": {"thread_id": task_id}}
        try:
            async for ev in self.graph.astream_events(
                {"messages": [_to_lc_message(message)]}, config, version="v2"
            ):
                if ev.get("event") == "on_chat_model_stream":
                    chunk = ev.get("data", {}).get("chunk")
                    text = _extract_text(chunk) if chunk else ""
                    if text:
                        yield _sse({
                            "jsonrpc": "2.0", "id": rpc_id,
                            "result": {
                                "id": task_id,
                                "status": {"state": "working"},
                                "artifact": {"parts": [{"text": text}]},
                            },
                        })
        except Exception as e:  # noqa: BLE001
            self.task_manager.set_state(task_id, TaskState.FAILED)
            yield _sse(_err(rpc_id, -32000, f"Stream error: {e}"))
            return

        self.task_manager.set_state(task_id, TaskState.COMPLETED)
        yield _sse({
            "jsonrpc": "2.0", "id": rpc_id,
            "result": {"id": task_id, "status": {"state": "completed"}, "final": True},
        })


def _sse(payload: dict) -> str:
    import json
    return f"data: {json.dumps(payload)}\n\n"
```

- [ ] **Step 4: Run streaming test, expect pass**

Run: `uv run pytest packages/python/vystak-template-langchain-python/tests/test_a2a_handler.py -v`
Expected: 6 passed (5 from before + new streaming test).

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-template-langchain-python/_vystak/runtime/a2a/handler.py packages/python/vystak-template-langchain-python/tests/test_a2a_handler.py
git commit -m "feat(template): A2AHandler.stream_dispatch for tasks/sendSubscribe"
```

### Task 1.5: Phase 1 release gate — full A2A test pass

- [ ] **Step 1: Run all template tests**

Run: `uv run pytest packages/python/vystak-template-langchain-python/ -v`
Expected: all green (TaskManager + AgentCard + A2AHandler tests).

- [ ] **Step 2: Run global CI**

Run: `just lint-python && just test-python`
Expected: all green; codegen path tests untouched and still passing.

- [ ] **Step 3: Tag a phase-end commit (optional)**

```bash
git tag -a phase-1-a2a-extracted -m "Phase 1 complete: A2A extracted as real classes"
```

---

## Phase 2 — Extract Responses + ChatCompletions + golden-file parity

OpenAI Responses API (`/v1/responses`) and stateless Chat Completions (`/v1/chat/completions`). Parity with the codegen path is the gate — verified by replaying recorded LangGraph event streams through both handlers and byte-comparing SSE output.

### Task 2.1: ChatCompletionsHandler — stateless `/v1/chat/completions`

**Files:**
- Create: `packages/python/vystak-template-langchain-python/_vystak/runtime/openai/__init__.py`
- Create: `packages/python/vystak-template-langchain-python/_vystak/runtime/openai/chat.py`
- Create: `packages/python/vystak-template-langchain-python/tests/test_openai_chat.py`

- [ ] **Step 1: Write failing tests**

```python
"""ChatCompletionsHandler — stateless /v1/chat/completions parity."""

import pytest

from _vystak.runtime.openai.chat import ChatCompletionsHandler


class FakeGraph:
    async def ainvoke(self, input, config):  # noqa: ANN001
        return {"messages": [{"role": "assistant", "content": "pong"}]}


@pytest.fixture
def handler():
    return ChatCompletionsHandler(agent=_fake_agent(), graph=FakeGraph())


def _fake_agent():
    class _A:
        name = "weather"
    return _A()


@pytest.mark.asyncio
async def test_create_returns_chat_completion_envelope(handler):
    body = {
        "model": "vystak/weather",
        "messages": [{"role": "user", "content": "ping"}],
    }
    resp = await handler.create(body)
    assert resp["object"] == "chat.completion"
    assert resp["model"] == "vystak/weather"
    assert resp["choices"][0]["message"]["content"] == "pong"
    assert resp["choices"][0]["message"]["role"] == "assistant"
    assert resp["choices"][0]["finish_reason"] == "stop"


@pytest.mark.asyncio
async def test_create_includes_usage_block(handler):
    body = {"model": "vystak/weather", "messages": [{"role": "user", "content": "ping"}]}
    resp = await handler.create(body)
    assert "usage" in resp
    assert "prompt_tokens" in resp["usage"]
    assert "completion_tokens" in resp["usage"]


@pytest.mark.asyncio
async def test_create_no_thread_id_passed_to_graph():
    captured = {}

    class CapturingGraph:
        async def ainvoke(self, input, config):
            captured["config"] = config
            return {"messages": [{"role": "assistant", "content": "x"}]}

    handler = ChatCompletionsHandler(agent=_fake_agent(), graph=CapturingGraph())
    await handler.create({"model": "vystak/weather", "messages": [{"role": "user", "content": "p"}]})
    assert "thread_id" not in (captured["config"].get("configurable") or {})
```

- [ ] **Step 2: Run, expect ImportError**

Run: `uv run pytest packages/python/vystak-template-langchain-python/tests/test_openai_chat.py -v`
Expected: ImportError on `_vystak.runtime.openai.chat`.

- [ ] **Step 3: Implement**

Create `_vystak/runtime/openai/__init__.py`:
```python
"""OpenAI-compatible runtime: ChatCompletions + Responses handlers."""
```

Create `_vystak/runtime/openai/chat.py`:
```python
"""Stateless /v1/chat/completions handler."""

import time
import uuid
from typing import Any


class ChatCompletionsHandler:
    """Stateless Chat Completions — no checkpointer, full message array per call."""

    def __init__(self, agent: Any, graph: Any) -> None:
        self.agent = agent
        self.graph = graph

    async def create(self, body: dict) -> dict:
        messages = body.get("messages", [])
        result = await self.graph.ainvoke({"messages": messages}, config={})

        last = result["messages"][-1]
        content = last["content"] if isinstance(last, dict) else getattr(last, "content", "")

        return {
            "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": body.get("model", f"vystak/{self.agent.name}"),
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            },
        }
```

- [ ] **Step 4: Run, expect 3 passed**

Run: `uv run pytest packages/python/vystak-template-langchain-python/tests/test_openai_chat.py -v`

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-template-langchain-python/_vystak/runtime/openai/ packages/python/vystak-template-langchain-python/tests/test_openai_chat.py
git commit -m "feat(template): stateless ChatCompletionsHandler"
```

### Task 2.2: ResponsesHandler — non-streaming `/v1/responses` (store=true and store=false)

**Files:**
- Create: `packages/python/vystak-template-langchain-python/_vystak/runtime/openai/responses.py`
- Create: `packages/python/vystak-template-langchain-python/tests/test_openai_responses_create.py`

- [ ] **Step 1: Write failing tests**

```python
"""ResponsesHandler.create() non-streaming behavior."""

import pytest

from _vystak.runtime.openai.responses import ResponsesHandler


class FakeGraph:
    async def ainvoke(self, input, config):  # noqa: ANN001
        return {"messages": [{"role": "assistant", "content": "pong"}]}


def _fake_agent():
    class _A:
        name = "weather"
    return _A()


@pytest.fixture
def handler():
    return ResponsesHandler(agent=_fake_agent(), graph=FakeGraph(), store=None)


@pytest.mark.asyncio
async def test_create_non_streaming_returns_response_envelope(handler):
    body = {"model": "vystak/weather", "input": "ping", "store": True}
    resp = await handler.create(body)
    assert resp["object"] == "response"
    assert resp["model"] == "vystak/weather"
    assert resp["status"] == "completed"
    assert resp["output"][0]["content"][0]["text"] == "pong"
    assert resp["id"].startswith("resp_")


@pytest.mark.asyncio
async def test_create_with_store_true_persists_via_thread_id(handler):
    captured_configs = []

    class CapturingGraph:
        async def ainvoke(self, input, config):
            captured_configs.append(config)
            return {"messages": [{"role": "assistant", "content": "x"}]}

    h = ResponsesHandler(agent=_fake_agent(), graph=CapturingGraph(), store=None)
    resp = await h.create({"model": "vystak/weather", "input": "p", "store": True})
    assert "configurable" in captured_configs[0]
    assert captured_configs[0]["configurable"]["thread_id"] == resp["id"]


@pytest.mark.asyncio
async def test_create_with_previous_response_id_reuses_thread(handler):
    captured = []

    class CapturingGraph:
        async def ainvoke(self, input, config):
            captured.append(config)
            return {"messages": [{"role": "assistant", "content": "x"}]}

    h = ResponsesHandler(agent=_fake_agent(), graph=CapturingGraph(), store=None)
    await h.create({
        "model": "vystak/weather", "input": "p",
        "store": True, "previous_response_id": "resp_existing",
    })
    assert captured[0]["configurable"]["thread_id"] == "resp_existing"


@pytest.mark.asyncio
async def test_create_input_accepts_string_or_message_array(handler):
    r1 = await handler.create({"model": "vystak/weather", "input": "ping", "store": True})
    r2 = await handler.create({
        "model": "vystak/weather",
        "input": [{"role": "user", "content": "ping"}],
        "store": True,
    })
    assert r1["status"] == "completed"
    assert r2["status"] == "completed"
```

- [ ] **Step 2: Run, expect ImportError**

Run: `uv run pytest packages/python/vystak-template-langchain-python/tests/test_openai_responses_create.py -v`

- [ ] **Step 3: Implement non-streaming path**

Create `_vystak/runtime/openai/responses.py`:
```python
"""Stateful /v1/responses handler."""

import time
import uuid
from typing import Any


class ResponsesHandler:
    """OpenAI Responses API — stateful via previous_response_id (LangGraph thread_id)."""

    def __init__(self, agent: Any, graph: Any, *, store: Any | None) -> None:
        self.agent = agent
        self.graph = graph
        self.store = store

    async def create(self, body: dict) -> dict | Any:
        if body.get("stream"):
            return self._create_stream(body)
        return await self._create_non_stream(body)

    async def _create_non_stream(self, body: dict) -> dict:
        thread_id = body.get("previous_response_id") or _new_response_id()
        messages = _normalize_input(body.get("input"))
        config = {"configurable": {"thread_id": thread_id}}

        result = await self.graph.ainvoke({"messages": messages}, config)
        last = result["messages"][-1]
        content = last["content"] if isinstance(last, dict) else getattr(last, "content", "")

        return {
            "id": thread_id,
            "object": "response",
            "created_at": int(time.time()),
            "model": body.get("model", f"vystak/{self.agent.name}"),
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": content}],
                }
            ],
        }

    def _create_stream(self, body: dict):
        # Filled in by Task 2.3.
        raise NotImplementedError("streaming added in Task 2.3")


def _new_response_id() -> str:
    return f"resp_{uuid.uuid4().hex[:24]}"


def _normalize_input(value: Any) -> list[dict]:
    if isinstance(value, str):
        return [{"role": "user", "content": value}]
    if isinstance(value, list):
        return value
    return []
```

- [ ] **Step 4: Run, expect 4 passed**

Run: `uv run pytest packages/python/vystak-template-langchain-python/tests/test_openai_responses_create.py -v`

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-template-langchain-python/_vystak/runtime/openai/responses.py packages/python/vystak-template-langchain-python/tests/test_openai_responses_create.py
git commit -m "feat(template): ResponsesHandler.create non-streaming"
```

### Task 2.3: ResponsesHandler — streaming SSE event shapes

**Files:**
- Modify: `packages/python/vystak-template-langchain-python/_vystak/runtime/openai/responses.py`
- Create: `packages/python/vystak-template-langchain-python/tests/test_openai_responses_stream.py`

- [ ] **Step 1: Write failing test for SSE event sequence**

```python
"""ResponsesHandler streaming — assert OpenAI Responses SSE event sequence."""

import json
import pytest

from _vystak.runtime.openai.responses import ResponsesHandler


class FakeStreamingGraph:
    def __init__(self, events: list[dict]) -> None:
        self._events = events

    async def astream_events(self, input, config, version="v2"):  # noqa: ANN001
        for ev in self._events:
            yield ev


def _fake_agent():
    class _A:
        name = "weather"
    return _A()


def _parse_sse(frames: list[str]) -> list[dict]:
    out = []
    for f in frames:
        for line in f.splitlines():
            if line.startswith("data: ") and not line.endswith("[DONE]"):
                out.append(json.loads(line[len("data: "):]))
    return out


@pytest.mark.asyncio
async def test_streaming_emits_created_then_deltas_then_completed():
    events = [
        {"event": "on_chat_model_stream", "data": {"chunk": {"content": "he"}}},
        {"event": "on_chat_model_stream", "data": {"chunk": {"content": "llo"}}},
    ]
    h = ResponsesHandler(agent=_fake_agent(), graph=FakeStreamingGraph(events), store=None)
    body = {"model": "vystak/weather", "input": "hi", "stream": True, "store": True}

    frames = []
    async for f in await h.create(body):
        frames.append(f)

    parsed = _parse_sse(frames)
    types = [p.get("type") for p in parsed]
    assert types[0] == "response.created"
    assert "response.output_text.delta" in types
    assert "response.completed" in types
    assert any(f.strip() == "data: [DONE]" for f in frames)


@pytest.mark.asyncio
async def test_streaming_delta_events_carry_text():
    events = [
        {"event": "on_chat_model_stream", "data": {"chunk": {"content": "hi"}}},
    ]
    h = ResponsesHandler(agent=_fake_agent(), graph=FakeStreamingGraph(events), store=None)
    body = {"model": "vystak/weather", "input": "x", "stream": True, "store": True}

    frames = []
    async for f in await h.create(body):
        frames.append(f)
    parsed = _parse_sse(frames)
    deltas = [p for p in parsed if p.get("type") == "response.output_text.delta"]
    assert any(d.get("delta") == "hi" for d in deltas)


@pytest.mark.asyncio
async def test_streaming_response_id_threaded_through_events():
    events = [{"event": "on_chat_model_stream", "data": {"chunk": {"content": "x"}}}]
    h = ResponsesHandler(agent=_fake_agent(), graph=FakeStreamingGraph(events), store=None)
    body = {"model": "vystak/weather", "input": "x", "stream": True, "store": True}

    frames = []
    async for f in await h.create(body):
        frames.append(f)
    parsed = _parse_sse(frames)
    response_ids = {p["response"]["id"] for p in parsed if p.get("type") == "response.created"}
    assert len(response_ids) == 1
    rid = response_ids.pop()
    assert rid.startswith("resp_")
```

- [ ] **Step 2: Run, expect NotImplementedError**

Run: `uv run pytest packages/python/vystak-template-langchain-python/tests/test_openai_responses_stream.py -v`
Expected: `NotImplementedError: streaming added in Task 2.3`.

- [ ] **Step 3: Replace `_create_stream` placeholder with real impl**

In `_vystak/runtime/openai/responses.py`, replace the `_create_stream` method with:

```python
    async def _create_stream(self, body: dict):
        return self._stream_iterator(body)

    async def _stream_iterator(self, body: dict):
        thread_id = body.get("previous_response_id") or _new_response_id()
        model = body.get("model", f"vystak/{self.agent.name}")
        created = int(time.time())

        yield _sse({
            "type": "response.created",
            "response": {
                "id": thread_id,
                "object": "response",
                "created_at": created,
                "model": model,
                "status": "in_progress",
            },
        })

        messages = _normalize_input(body.get("input"))
        config = {"configurable": {"thread_id": thread_id}}
        full_text = []
        item_id = f"msg_{uuid.uuid4().hex[:12]}"

        try:
            async for ev in self.graph.astream_events(
                {"messages": messages}, config, version="v2"
            ):
                if ev.get("event") == "on_chat_model_stream":
                    chunk = ev.get("data", {}).get("chunk")
                    text = chunk["content"] if isinstance(chunk, dict) else getattr(chunk, "content", "")
                    if text:
                        full_text.append(text)
                        yield _sse({
                            "type": "response.output_text.delta",
                            "item_id": item_id,
                            "output_index": 0,
                            "content_index": 0,
                            "delta": text,
                        })
        except Exception as e:  # noqa: BLE001
            yield _sse({
                "type": "response.failed",
                "response": {"id": thread_id, "status": "failed", "error": {"message": str(e)}},
            })
            yield "data: [DONE]\n\n"
            return

        final_text = "".join(full_text)
        yield _sse({
            "type": "response.output_text.done",
            "item_id": item_id,
            "output_index": 0,
            "content_index": 0,
            "text": final_text,
        })
        yield _sse({
            "type": "response.completed",
            "response": {
                "id": thread_id,
                "object": "response",
                "created_at": created,
                "model": model,
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": final_text}],
                    }
                ],
            },
        })
        yield "data: [DONE]\n\n"
```

Add `_sse` helper at module bottom:
```python
def _sse(payload: dict) -> str:
    import json
    return f"data: {json.dumps(payload)}\n\n"
```

- [ ] **Step 4: Run, expect 3 passed**

Run: `uv run pytest packages/python/vystak-template-langchain-python/tests/test_openai_responses_stream.py -v`

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-template-langchain-python/_vystak/runtime/openai/responses.py packages/python/vystak-template-langchain-python/tests/test_openai_responses_stream.py
git commit -m "feat(template): ResponsesHandler streaming SSE events"
```

### Task 2.4: ResponsesHandler — `get(response_id)` retrieval

**Files:**
- Modify: `packages/python/vystak-template-langchain-python/_vystak/runtime/openai/responses.py`
- Create: `packages/python/vystak-template-langchain-python/tests/test_openai_responses_get.py`

- [ ] **Step 1: Write failing test**

```python
"""ResponsesHandler.get(response_id) — retrieve stored response."""

import pytest

from _vystak.runtime.openai.responses import ResponsesHandler


class FakeGraph:
    def __init__(self) -> None:
        self.checkpoint_seen = None

    async def aget_state(self, config):  # noqa: ANN001
        self.checkpoint_seen = config
        # LangGraph's get_state returns a StateSnapshot; mock the relevant fields.
        class _Snapshot:
            values = {"messages": [{"role": "assistant", "content": "stored"}]}
            config = {"configurable": {"thread_id": "resp_abc"}}
        return _Snapshot()


def _fake_agent():
    class _A:
        name = "weather"
    return _A()


@pytest.mark.asyncio
async def test_get_returns_stored_response():
    graph = FakeGraph()
    h = ResponsesHandler(agent=_fake_agent(), graph=graph, store=None)
    resp = await h.get("resp_abc")
    assert resp["id"] == "resp_abc"
    assert resp["status"] == "completed"
    assert resp["output"][0]["content"][0]["text"] == "stored"


@pytest.mark.asyncio
async def test_get_unknown_response_raises():
    class EmptyGraph:
        async def aget_state(self, config):
            class _S:
                values = {}
            return _S()

    h = ResponsesHandler(agent=_fake_agent(), graph=EmptyGraph(), store=None)
    with pytest.raises(KeyError):
        await h.get("resp_missing")
```

- [ ] **Step 2: Run, expect AttributeError**

Run: `uv run pytest packages/python/vystak-template-langchain-python/tests/test_openai_responses_get.py -v`

- [ ] **Step 3: Add `get` method to `ResponsesHandler`**

In `_vystak/runtime/openai/responses.py`, add:
```python
    async def get(self, response_id: str) -> dict:
        config = {"configurable": {"thread_id": response_id}}
        snapshot = await self.graph.aget_state(config)
        messages = (snapshot.values or {}).get("messages")
        if not messages:
            raise KeyError(f"Unknown response: {response_id}")

        last = messages[-1]
        text = last["content"] if isinstance(last, dict) else getattr(last, "content", "")

        return {
            "id": response_id,
            "object": "response",
            "model": f"vystak/{self.agent.name}",
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": text}],
                }
            ],
        }
```

- [ ] **Step 4: Run, expect 2 passed**

Run: `uv run pytest packages/python/vystak-template-langchain-python/tests/test_openai_responses_get.py -v`

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-template-langchain-python/_vystak/runtime/openai/responses.py packages/python/vystak-template-langchain-python/tests/test_openai_responses_get.py
git commit -m "feat(template): ResponsesHandler.get(response_id)"
```

### Task 2.5: Golden-file event-stream parity test

This is the highest-risk gate of the migration. Replay a recorded LangGraph event stream through both the codegen path (current `vystak_adapter_langchain.responses`) and the new `ResponsesHandler`. Byte-compare SSE outputs.

**Files:**
- Create: `packages/python/vystak-template-langchain-python/tests/golden/recorded_stream.json`
- Create: `packages/python/vystak-template-langchain-python/tests/test_codegen_parity.py`

- [ ] **Step 1: Capture a recorded LangGraph event stream**

Run a one-off script to capture canonical events from the existing codegen path. From the repo root:

```bash
uv run python -c "
import asyncio, json, sys
from pathlib import Path

# Replay a representative sequence: text deltas + one tool call + final.
events = [
    {'event': 'on_chat_model_stream', 'data': {'chunk': {'content': 'Let me check.'}}},
    {'event': 'on_tool_start', 'data': {'name': 'get_weather', 'input': {'city': 'Tokyo'}}},
    {'event': 'on_tool_end', 'data': {'name': 'get_weather', 'output': '22C, sunny'}},
    {'event': 'on_chat_model_stream', 'data': {'chunk': {'content': 'It is 22C.'}}},
]
out = Path('packages/python/vystak-template-langchain-python/tests/golden/recorded_stream.json')
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(events, indent=2))
"
```

- [ ] **Step 2: Write parity test**

Create `tests/test_codegen_parity.py`:
```python
"""Golden-file parity: new ResponsesHandler vs codegen path emit identical SSE shapes.

This test is the gate that lets us delete the codegen path in Phase 9 with
confidence. If it ever fails, the new template diverged from documented
OpenAI Responses semantics; investigate before merging.
"""

import json
import re
from pathlib import Path

import pytest

from _vystak.runtime.openai.responses import ResponsesHandler


GOLDEN = Path(__file__).parent / "golden" / "recorded_stream.json"


class ReplayGraph:
    def __init__(self, events: list[dict]) -> None:
        self._events = events

    async def astream_events(self, input, config, version="v2"):  # noqa: ANN001
        for ev in self._events:
            yield ev


def _agent():
    class _A:
        name = "weather"
    return _A()


def _normalize(payload: dict) -> dict:
    """Strip volatile fields (timestamps, random IDs) before comparison."""
    if "created_at" in payload:
        payload["created_at"] = 0
    if "response" in payload and isinstance(payload["response"], dict):
        if "created_at" in payload["response"]:
            payload["response"]["created_at"] = 0
        if "id" in payload["response"]:
            payload["response"]["id"] = "resp_NORMALIZED"
    if "item_id" in payload:
        payload["item_id"] = "msg_NORMALIZED"
    return payload


@pytest.mark.asyncio
async def test_response_stream_matches_documented_event_sequence():
    events = json.loads(GOLDEN.read_text())
    h = ResponsesHandler(agent=_agent(), graph=ReplayGraph(events), store=None)

    frames = []
    async for f in await h.create({"model": "vystak/weather", "input": "x", "stream": True, "store": True}):
        frames.append(f)

    parsed = []
    for f in frames:
        for line in f.splitlines():
            if line.startswith("data: "):
                payload = line[len("data: "):].strip()
                if payload == "[DONE]":
                    parsed.append({"type": "[DONE]"})
                else:
                    parsed.append(_normalize(json.loads(payload)))

    types = [p.get("type") for p in parsed]
    # Required event sequence per OpenAI Responses spec.
    assert types[0] == "response.created"
    assert "response.output_text.delta" in types
    assert "response.output_text.done" in types
    assert "response.completed" in types
    assert types[-1] == "[DONE]"

    # Concatenated delta text must equal the final completed text.
    deltas = "".join(p.get("delta", "") for p in parsed if p.get("type") == "response.output_text.delta")
    final = next(p for p in parsed if p.get("type") == "response.output_text.done")["text"]
    assert deltas == final
```

- [ ] **Step 3: Run parity test, expect pass**

Run: `uv run pytest packages/python/vystak-template-langchain-python/tests/test_codegen_parity.py -v`
Expected: 1 passed.

- [ ] **Step 4: Commit**

```bash
git add packages/python/vystak-template-langchain-python/tests/golden/ packages/python/vystak-template-langchain-python/tests/test_codegen_parity.py
git commit -m "test(template): golden-file parity for Responses SSE event stream"
```

### Task 2.6: Phase 2 release gate

- [ ] **Step 1: Run all template tests**

Run: `uv run pytest packages/python/vystak-template-langchain-python/ -v`
Expected: all green.

- [ ] **Step 2: Run global CI**

Run: `just lint-python && just test-python`
Expected: all green.

- [ ] **Step 3: Tag**

```bash
git tag -a phase-2-openai-extracted -m "Phase 2 complete: OpenAI Chat + Responses extracted"
```

---

## Phase 3 — Extract Compaction + Memory

Layer 1 prune (head-and-tail truncate of oversized ToolMessages), Layer 3 threshold compaction, MemoryManager. Compaction *stores* (Postgres / SQLite / in-mem) already live in `vystak.compaction.stores` in core; this phase moves the orchestration logic.

### Task 3.1: PreCallPruner — Layer 1 head-and-tail tool-output prune

**Files:**
- Create: `packages/python/vystak-template-langchain-python/_vystak/runtime/compaction/__init__.py`
- Create: `packages/python/vystak-template-langchain-python/_vystak/runtime/compaction/pruner.py`
- Create: `packages/python/vystak-template-langchain-python/tests/test_compaction_pruner.py`

- [ ] **Step 1: Write failing tests**

```python
"""PreCallPruner — Layer 1 head-and-tail truncate of oversized ToolMessages."""

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from _vystak.runtime.compaction.pruner import PreCallPruner


def _make_compaction(threshold_bytes: int = 4096):
    class _C:
        prune_tool_output_bytes = threshold_bytes
    return _C()


def test_prune_leaves_short_tool_outputs_alone():
    msgs = [
        HumanMessage(content="hi"),
        AIMessage(content="ok"),
        ToolMessage(content="short", tool_call_id="t1"),
    ]
    pruned = PreCallPruner(_make_compaction()).prune(msgs)
    assert pruned[-1].content == "short"


def test_prune_truncates_oversized_old_tool_output():
    big = "x" * 10_000
    msgs = [
        HumanMessage(content="q1"),
        AIMessage(content=""),
        ToolMessage(content=big, tool_call_id="t1"),
        HumanMessage(content="q2"),
        AIMessage(content="a2"),
        HumanMessage(content="q3"),
        AIMessage(content="a3"),
        HumanMessage(content="q4"),
        AIMessage(content="a4"),
    ]
    pruner = PreCallPruner(_make_compaction(threshold_bytes=100))
    pruned = pruner.prune(msgs)
    truncated = pruned[2]
    assert isinstance(truncated, ToolMessage)
    assert len(truncated.content) < 200
    assert "..." in truncated.content


def test_prune_preserves_recent_tool_output_even_if_oversized():
    big = "y" * 10_000
    msgs = [
        HumanMessage(content="q1"),
        AIMessage(content=""),
        ToolMessage(content=big, tool_call_id="t1"),
    ]
    pruner = PreCallPruner(_make_compaction(threshold_bytes=100))
    pruned = pruner.prune(msgs)
    assert len(pruned[-1].content) == 10_000


def test_prune_never_touches_human_or_ai_messages():
    big = "z" * 10_000
    msgs = [
        HumanMessage(content=big),
        AIMessage(content=big),
        HumanMessage(content="q2"),
        AIMessage(content="a2"),
        HumanMessage(content="q3"),
        AIMessage(content="a3"),
        HumanMessage(content="q4"),
        AIMessage(content="a4"),
    ]
    pruner = PreCallPruner(_make_compaction(threshold_bytes=100))
    pruned = pruner.prune(msgs)
    assert len(pruned[0].content) == 10_000
    assert len(pruned[1].content) == 10_000
```

- [ ] **Step 2: Run, expect ImportError**

Run: `uv run pytest packages/python/vystak-template-langchain-python/tests/test_compaction_pruner.py -v`

- [ ] **Step 3: Implement**

Create `_vystak/runtime/compaction/__init__.py`:
```python
"""Compaction runtime: Layer 1 prune + Layer 3 threshold summarize."""
```

Create `_vystak/runtime/compaction/pruner.py`:
```python
"""Layer 1 — head-and-tail prune of oversized ToolMessages."""

from typing import Any

from langchain_core.messages import BaseMessage, ToolMessage

KEEP_RECENT_TURNS = 3


class PreCallPruner:
    """Pure transform applied to messages before each LLM call."""

    def __init__(self, compaction: Any) -> None:
        self._threshold = compaction.prune_tool_output_bytes

    def prune(self, messages: list[BaseMessage]) -> list[BaseMessage]:
        if not messages:
            return messages

        recent_cutoff = self._find_recent_cutoff(messages)
        out: list[BaseMessage] = []
        for i, msg in enumerate(messages):
            if isinstance(msg, ToolMessage) and i < recent_cutoff:
                content = str(msg.content)
                if len(content) > self._threshold:
                    half = self._threshold // 2 - 10
                    truncated = (
                        content[:half]
                        + f"\n... [truncated {len(content) - 2 * half} bytes] ...\n"
                        + content[-half:]
                    )
                    out.append(ToolMessage(
                        content=truncated,
                        tool_call_id=getattr(msg, "tool_call_id", ""),
                    ))
                    continue
            out.append(msg)
        return out

    def _find_recent_cutoff(self, messages: list[BaseMessage]) -> int:
        """Find the index N such that messages[N:] are 'recent' (last 3 turns)."""
        from langchain_core.messages import HumanMessage

        human_indices = [i for i, m in enumerate(messages) if isinstance(m, HumanMessage)]
        if len(human_indices) <= KEEP_RECENT_TURNS:
            return 0
        return human_indices[-KEEP_RECENT_TURNS]
```

- [ ] **Step 4: Run, expect 4 passed**

Run: `uv run pytest packages/python/vystak-template-langchain-python/tests/test_compaction_pruner.py -v`

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-template-langchain-python/_vystak/runtime/compaction/ packages/python/vystak-template-langchain-python/tests/test_compaction_pruner.py
git commit -m "feat(template): PreCallPruner (Layer 1 tool-output prune)"
```

### Task 3.2: ThresholdCompactor — Layer 3 summarize older slice

The compactor uses the existing `vystak.compaction.stores` (Postgres / SQLite / in-mem). It produces a summary of older messages when prefill estimate ≥ `trigger_pct × context_window`, with a 60-second + 70%-coverage idempotency guard.

**Files:**
- Create: `packages/python/vystak-template-langchain-python/_vystak/runtime/compaction/compactor.py`
- Create: `packages/python/vystak-template-langchain-python/tests/test_compaction_compactor.py`

- [ ] **Step 1: Write failing tests for trigger conditions**

```python
"""ThresholdCompactor — Layer 3 prefill-threshold summarize."""

from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from _vystak.runtime.compaction.compactor import ThresholdCompactor


class FakeStore:
    def __init__(self) -> None:
        self.rows: list[dict] = []

    async def write(self, **row) -> None:
        self.rows.append(row)

    async def latest(self, thread_id: str) -> dict | None:
        rows = [r for r in self.rows if r["thread_id"] == thread_id]
        return max(rows, key=lambda r: r["generation"]) if rows else None


def _fake_summarizer(text: str = "summary text"):
    s = AsyncMock()
    s.ainvoke = AsyncMock(return_value=AIMessage(content=text))
    return s


def _make_agent(trigger_pct=0.5, keep_recent_pct=0.2, context_window=1000):
    class _C:
        mode = "conservative"
        prune_tool_output_bytes = 4096
    c = _C()
    c.trigger_pct = trigger_pct
    c.keep_recent_pct = keep_recent_pct
    c.target_tokens = None
    c.context_window = context_window

    class _A:
        name = "test"
        compaction = c
    return _A()


@pytest.mark.asyncio
async def test_below_threshold_returns_messages_unchanged():
    msgs = [HumanMessage(content="hi"), AIMessage(content="ok")]
    store = FakeStore()
    cmp = ThresholdCompactor(_make_agent(), store, _fake_summarizer())
    result = await cmp.maybe_compact("t1", msgs, prefill_token_estimate=100)
    assert result == msgs
    assert store.rows == []


@pytest.mark.asyncio
async def test_above_threshold_summarizes_older_slice():
    msgs = [HumanMessage(content=f"q{i}") for i in range(10)]
    store = FakeStore()
    cmp = ThresholdCompactor(_make_agent(context_window=1000), store, _fake_summarizer("summarized"))
    result = await cmp.maybe_compact("t1", msgs, prefill_token_estimate=600)
    assert len(result) < len(msgs)
    assert any(getattr(m, "content", "") == "summarized" for m in result)
    assert len(store.rows) == 1


@pytest.mark.asyncio
async def test_idempotency_guard_blocks_summary_within_60s():
    msgs = [HumanMessage(content=f"q{i}") for i in range(10)]
    store = FakeStore()
    store.rows.append({
        "thread_id": "t1",
        "generation": 1,
        "summary": "prior",
        "created_at": datetime.now(timezone.utc),
        "covered_message_count": 7,
    })
    cmp = ThresholdCompactor(_make_agent(context_window=1000), store, _fake_summarizer())
    result = await cmp.maybe_compact("t1", msgs, prefill_token_estimate=600)
    assert len(store.rows) == 1


@pytest.mark.asyncio
async def test_idempotency_guard_allows_after_60s():
    msgs = [HumanMessage(content=f"q{i}") for i in range(10)]
    store = FakeStore()
    store.rows.append({
        "thread_id": "t1",
        "generation": 1,
        "summary": "prior",
        "created_at": datetime.now(timezone.utc) - timedelta(seconds=120),
        "covered_message_count": 1,  # < 70% coverage
    })
    cmp = ThresholdCompactor(_make_agent(context_window=1000), store, _fake_summarizer())
    await cmp.maybe_compact("t1", msgs, prefill_token_estimate=600)
    assert len(store.rows) == 2
```

- [ ] **Step 2: Run, expect ImportError**

Run: `uv run pytest packages/python/vystak-template-langchain-python/tests/test_compaction_compactor.py -v`

- [ ] **Step 3: Implement**

Create `_vystak/runtime/compaction/compactor.py`:
```python
"""Layer 3 — threshold-driven summarize."""

from datetime import datetime, timezone
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage


SUMMARY_PROMPT = (
    "You are summarizing a conversation between a user and an AI assistant. "
    "Produce a concise summary that preserves all facts, decisions, and "
    "context the assistant would need to continue the conversation. "
    "Do not include filler, greetings, or meta-commentary."
)


class ThresholdCompactor:
    def __init__(self, agent: Any, store: Any, summarizer: Any) -> None:
        self.agent = agent
        self.store = store
        self.summarizer = summarizer

    async def maybe_compact(
        self,
        thread_id: str,
        messages: list[BaseMessage],
        prefill_token_estimate: int,
    ) -> list[BaseMessage]:
        cmp = self.agent.compaction
        threshold = int(cmp.trigger_pct * cmp.context_window)
        if prefill_token_estimate < threshold:
            return messages

        if await self._idempotency_blocks(thread_id, messages):
            return messages

        keep_count = max(1, int(len(messages) * cmp.keep_recent_pct))
        older = messages[:-keep_count]
        recent = messages[-keep_count:]
        if not older:
            return messages

        summary_text = await self._summarize(older)
        await self._persist(thread_id, summary_text, len(older))

        return [SystemMessage(content=f"[Summary of earlier conversation]\n{summary_text}"), *recent]

    async def _idempotency_blocks(self, thread_id: str, messages: list[BaseMessage]) -> bool:
        latest = await self.store.latest(thread_id)
        if not latest:
            return False
        age = (datetime.now(timezone.utc) - latest["created_at"]).total_seconds()
        coverage = latest["covered_message_count"] / max(len(messages), 1)
        return age < 60 or coverage >= 0.7

    async def _summarize(self, older: list[BaseMessage]) -> str:
        text = "\n".join(_render(m) for m in older)
        prompt = [SystemMessage(content=SUMMARY_PROMPT), HumanMessage(content=text)]
        result = await self.summarizer.ainvoke(prompt)
        return result.content if isinstance(result, AIMessage) else str(result)

    async def _persist(self, thread_id: str, summary: str, covered: int) -> None:
        latest = await self.store.latest(thread_id)
        gen = (latest["generation"] + 1) if latest else 1
        await self.store.write(
            thread_id=thread_id,
            generation=gen,
            summary=summary,
            created_at=datetime.now(timezone.utc),
            covered_message_count=covered,
        )


def _render(m: BaseMessage) -> str:
    role = m.__class__.__name__.replace("Message", "").lower()
    return f"{role}: {m.content}"
```

- [ ] **Step 4: Run, expect 4 passed**

Run: `uv run pytest packages/python/vystak-template-langchain-python/tests/test_compaction_compactor.py -v`

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-template-langchain-python/_vystak/runtime/compaction/compactor.py packages/python/vystak-template-langchain-python/tests/test_compaction_compactor.py
git commit -m "feat(template): ThresholdCompactor (Layer 3 summarize)"
```

### Task 3.3: MemoryManager — long-term memory recall + save/forget tool dispatch

**Files:**
- Create: `packages/python/vystak-template-langchain-python/_vystak/runtime/memory.py`
- Create: `packages/python/vystak-template-langchain-python/tests/test_memory.py`

- [ ] **Step 1: Write failing tests**

```python
"""MemoryManager — recall + save/forget sentinel parsing."""

import pytest

from _vystak.runtime.memory import MemoryManager


class FakeStore:
    def __init__(self) -> None:
        self.entries: dict[tuple, list[dict]] = {}

    async def aput(self, namespace: tuple, key: str, value: dict) -> None:
        self.entries.setdefault(namespace, []).append({"key": key, "value": value})

    async def asearch(self, namespace: tuple, query: str) -> list:
        results = []
        for e in self.entries.get(namespace, []):
            if query.lower() in str(e["value"]).lower():
                class _R:
                    def __init__(self, key, value):
                        self.key = key
                        self.value = value
                results.append(_R(e["key"], e["value"]))
        return results

    async def adelete(self, namespace: tuple, key: str) -> None:
        ns = self.entries.get(namespace, [])
        self.entries[namespace] = [e for e in ns if e["key"] != key]


def _agent():
    class _A:
        memory = "configured"
    return _A()


@pytest.mark.asyncio
async def test_recall_returns_matching_memories():
    store = FakeStore()
    await store.aput(("user", "u1"), "m1", {"content": "User likes pizza"})
    mgr = MemoryManager(_agent(), store=store)
    out = await mgr.recall(user_id="u1", query="pizza")
    assert any("pizza" in str(m) for m in out)


@pytest.mark.asyncio
async def test_save_via_sentinel():
    store = FakeStore()
    mgr = MemoryManager(_agent(), store=store)
    handled = await mgr.handle_tool_output(
        "__SAVE_MEMORY__|user|likes pizza",
        user_id="u1",
        project_id="p1",
    )
    assert handled is True
    assert ("user", "u1") in store.entries
    assert "pizza" in str(store.entries[("user", "u1")][0]["value"])


@pytest.mark.asyncio
async def test_forget_via_sentinel():
    store = FakeStore()
    await store.aput(("user", "u1"), "m1", {"content": "old"})
    mgr = MemoryManager(_agent(), store=store)
    handled = await mgr.handle_tool_output(
        "__FORGET_MEMORY__|m1",
        user_id="u1",
        project_id="p1",
    )
    assert handled is True
    assert store.entries[("user", "u1")] == []


@pytest.mark.asyncio
async def test_non_sentinel_passes_through():
    mgr = MemoryManager(_agent(), store=FakeStore())
    handled = await mgr.handle_tool_output("regular tool output", user_id="u1", project_id="p1")
    assert handled is False
```

- [ ] **Step 2: Run, expect ImportError**

Run: `uv run pytest packages/python/vystak-template-langchain-python/tests/test_memory.py -v`

- [ ] **Step 3: Implement**

Create `_vystak/runtime/memory.py`:
```python
"""MemoryManager — long-term memory recall and save/forget sentinel handling."""

import uuid
from typing import Any


SAVE_SENTINEL = "__SAVE_MEMORY__|"
FORGET_SENTINEL = "__FORGET_MEMORY__|"


class MemoryManager:
    def __init__(self, agent: Any, store: Any) -> None:
        self.agent = agent
        self.store = store

    async def recall(self, *, user_id: str, query: str = "", project_id: str = "default") -> list[str]:
        scopes = [
            ("user", user_id),
            ("project", project_id),
            ("global", "global"),
        ]
        out: list[str] = []
        for ns in scopes:
            results = await self.store.asearch(ns, query)
            for r in results:
                content = r.value.get("content") if isinstance(r.value, dict) else str(r.value)
                out.append(f"[{ns[0]}/{r.key}] {content}")
        return out

    async def handle_tool_output(
        self,
        output: str,
        *,
        user_id: str,
        project_id: str = "default",
    ) -> bool:
        if output.startswith(SAVE_SENTINEL):
            _, scope, content = output.split("|", 2)
            ns = self._namespace_for(scope, user_id=user_id, project_id=project_id)
            await self.store.aput(ns, str(uuid.uuid4()), {"content": content})
            return True
        if output.startswith(FORGET_SENTINEL):
            memory_id = output[len(FORGET_SENTINEL):]
            for scope in ("user", "project", "global"):
                ns = self._namespace_for(scope, user_id=user_id, project_id=project_id)
                await self.store.adelete(ns, memory_id)
            return True
        return False

    @staticmethod
    def _namespace_for(scope: str, *, user_id: str, project_id: str) -> tuple[str, str]:
        if scope == "user":
            return ("user", user_id)
        if scope == "project":
            return ("project", project_id)
        return ("global", "global")
```

- [ ] **Step 4: Run, expect 4 passed**

Run: `uv run pytest packages/python/vystak-template-langchain-python/tests/test_memory.py -v`

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-template-langchain-python/_vystak/runtime/memory.py packages/python/vystak-template-langchain-python/tests/test_memory.py
git commit -m "feat(template): MemoryManager with sentinel-based save/forget"
```

### Task 3.4: Phase 3 release gate

- [ ] **Step 1: Full template test pass**

Run: `uv run pytest packages/python/vystak-template-langchain-python/ -v`
Expected: all green.

- [ ] **Step 2: Global CI**

Run: `just lint-python && just test-python`
Expected: green.

- [ ] **Step 3: Tag**

```bash
git tag -a phase-3-compaction-memory -m "Phase 3 complete: compaction + memory extracted"
```

---

## Phase 4 — Extract graph + checkpointer + MCP + tools + prompt callable

### Task 4.1: build_checkpointer — session store factory

**Files:**
- Create: `packages/python/vystak-template-langchain-python/_vystak/runtime/store.py`
- Create: `packages/python/vystak-template-langchain-python/tests/test_store.py`

- [ ] **Step 1: Write failing tests**

```python
"""build_checkpointer factory dispatches on agent.sessions.engine."""

from _vystak.runtime.store import build_checkpointer


class _Sessions:
    def __init__(self, engine: str | None = None, connection_string: str | None = None):
        self.engine = engine
        self.connection_string = connection_string


def _agent(sessions=None):
    class _A:
        pass
    a = _A()
    a.sessions = sessions
    return a


def test_no_sessions_returns_in_memory_saver():
    cp = build_checkpointer(_agent(sessions=None))
    assert cp.__class__.__name__ == "MemorySaver"


def test_sqlite_returns_async_sqlite_saver_factory():
    cp = build_checkpointer(_agent(sessions=_Sessions(engine="sqlite")))
    assert cp.__class__.__name__ in {"AsyncSqliteSaver", "_LazyCheckpointer"}


def test_postgres_returns_postgres_saver_factory():
    sessions = _Sessions(engine="postgres", connection_string="postgresql://x")
    cp = build_checkpointer(_agent(sessions=sessions))
    assert cp.__class__.__name__ in {"AsyncPostgresSaver", "_LazyCheckpointer"}
```

- [ ] **Step 2: Run, expect ImportError**

Run: `uv run pytest packages/python/vystak-template-langchain-python/tests/test_store.py -v`

- [ ] **Step 3: Implement**

Create `_vystak/runtime/store.py`:
```python
"""Session checkpointer factory."""

from typing import Any


class _LazyCheckpointer:
    """Wraps an async-only saver behind a sync factory; resolved at app startup."""

    def __init__(self, factory):  # noqa: ANN001
        self._factory = factory

    async def aresolve(self):
        return await self._factory()


def build_checkpointer(agent: Any):
    sessions = getattr(agent, "sessions", None)
    if sessions is None:
        from langgraph.checkpoint.memory import MemorySaver
        return MemorySaver()

    engine = getattr(sessions, "engine", None)
    if engine == "sqlite":
        async def _make():
            from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
            return AsyncSqliteSaver.from_conn_string(":memory:")
        return _LazyCheckpointer(_make)

    if engine == "postgres":
        async def _make():
            from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
            return AsyncPostgresSaver.from_conn_string(sessions.connection_string)
        return _LazyCheckpointer(_make)

    from langgraph.checkpoint.memory import MemorySaver
    return MemorySaver()
```

- [ ] **Step 4: Run, expect 3 passed**

Run: `uv run pytest packages/python/vystak-template-langchain-python/tests/test_store.py -v`

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-template-langchain-python/_vystak/runtime/store.py packages/python/vystak-template-langchain-python/tests/test_store.py
git commit -m "feat(template): build_checkpointer factory"
```

### Task 4.2: load_user_tools — discover and import `tools/*.py`

**Files:**
- Create: `packages/python/vystak-template-langchain-python/_vystak/runtime/tools.py`
- Create: `packages/python/vystak-template-langchain-python/tests/test_tools.py`

- [ ] **Step 1: Write failing tests**

```python
"""load_user_tools — import @tool functions from tools/<name>.py."""

from _vystak.runtime.tools import load_user_tools


def _agent_with_tool_names(names):
    from vystak.schema.skill import Skill

    class _A:
        skills = [Skill(name="s1", tools=names)]
    return _A()


def test_load_returns_empty_when_no_tools_dir(tmp_path):
    agent = _agent_with_tool_names([])
    tools = load_user_tools(agent, tmp_path / "missing")
    assert tools == []


def test_load_imports_tool_function(tmp_path):
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir()
    (tools_dir / "__init__.py").write_text("")
    (tools_dir / "weather.py").write_text(
        "from langchain_core.tools import tool\n"
        "@tool\n"
        "def weather(city: str) -> str:\n"
        "    '''Get the weather.'''\n"
        "    return f'sunny in {city}'\n"
    )
    agent = _agent_with_tool_names(["weather"])
    tools = load_user_tools(agent, tools_dir)
    assert len(tools) == 1
    assert tools[0].name == "weather"


def test_load_skips_tools_not_in_skills(tmp_path):
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir()
    (tools_dir / "__init__.py").write_text("")
    (tools_dir / "unused.py").write_text(
        "from langchain_core.tools import tool\n"
        "@tool\n"
        "def unused() -> str:\n"
        "    '''.'''\n"
        "    return 'x'\n"
    )
    agent = _agent_with_tool_names(["other"])
    tools = load_user_tools(agent, tools_dir)
    assert tools == []
```

- [ ] **Step 2: Run, expect ImportError**

Run: `uv run pytest packages/python/vystak-template-langchain-python/tests/test_tools.py -v`

- [ ] **Step 3: Implement**

Create `_vystak/runtime/tools.py`:
```python
"""Discover and import user-defined @tool functions from tools/."""

import importlib.util
import sys
from pathlib import Path
from typing import Any


def load_user_tools(agent: Any, tools_dir: Path) -> list[Any]:
    if not tools_dir.exists() or not tools_dir.is_dir():
        return []

    needed: set[str] = set()
    for skill in getattr(agent, "skills", []):
        needed.update(skill.tools)

    found: list[Any] = []
    for name in needed:
        candidate = tools_dir / f"{name}.py"
        if not candidate.exists():
            continue
        module = _load_module(candidate, f"_vystak_user_tools.{name}")
        fn = getattr(module, name, None)
        if fn is not None:
            found.append(fn)
    return found


def _load_module(path: Path, qualified_name: str) -> Any:
    spec = importlib.util.spec_from_file_location(qualified_name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[qualified_name] = module
    spec.loader.exec_module(module)
    return module
```

- [ ] **Step 4: Run, expect 3 passed**

Run: `uv run pytest packages/python/vystak-template-langchain-python/tests/test_tools.py -v`

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-template-langchain-python/_vystak/runtime/tools.py packages/python/vystak-template-langchain-python/tests/test_tools.py
git commit -m "feat(template): load_user_tools discovery"
```

### Task 4.3: attach_mcp_servers — MCP integration

**Files:**
- Create: `packages/python/vystak-template-langchain-python/_vystak/runtime/mcp.py`
- Create: `packages/python/vystak-template-langchain-python/tests/test_mcp.py`

- [ ] **Step 1: Write failing tests**

```python
"""attach_mcp_servers — wire langchain-mcp-adapters from agent.mcp_servers."""

from unittest.mock import AsyncMock, patch

import pytest

from _vystak.runtime.mcp import attach_mcp_servers


class _Mcp:
    def __init__(self, name, command=None, args=None, transport="stdio", url=None):
        self.name = name
        self.command = command
        self.args = args or []
        self.transport = transport
        self.url = url


def _agent(mcps):
    class _A:
        mcp_servers = mcps
    return _A()


@pytest.mark.asyncio
async def test_no_mcp_returns_empty_tool_list():
    tools = await attach_mcp_servers(_agent([]))
    assert tools == []


@pytest.mark.asyncio
async def test_mcp_servers_invoke_adapter_with_correct_config():
    captured = {}

    class FakeClient:
        def __init__(self, config):
            captured["config"] = config

        async def get_tools(self):
            return ["tool1", "tool2"]

    with patch("_vystak.runtime.mcp.MultiServerMCPClient", FakeClient):
        mcps = [_Mcp(name="files", command="mcp-fs", args=["/tmp"], transport="stdio")]
        tools = await attach_mcp_servers(_agent(mcps))
        assert tools == ["tool1", "tool2"]
        assert "files" in captured["config"]
        assert captured["config"]["files"]["command"] == "mcp-fs"
```

- [ ] **Step 2: Run, expect ImportError**

Run: `uv run pytest packages/python/vystak-template-langchain-python/tests/test_mcp.py -v`

- [ ] **Step 3: Implement**

Create `_vystak/runtime/mcp.py`:
```python
"""MCP server wiring via langchain-mcp-adapters."""

from typing import Any

try:
    from langchain_mcp_adapters.client import MultiServerMCPClient
except ImportError:  # pragma: no cover
    MultiServerMCPClient = None


async def attach_mcp_servers(agent: Any) -> list[Any]:
    mcps = getattr(agent, "mcp_servers", []) or []
    if not mcps:
        return []
    if MultiServerMCPClient is None:
        return []

    config: dict[str, dict] = {}
    for m in mcps:
        if m.transport == "stdio":
            config[m.name] = {
                "transport": "stdio",
                "command": m.command,
                "args": m.args,
            }
        elif m.transport in ("sse", "http"):
            config[m.name] = {"transport": m.transport, "url": m.url}

    client = MultiServerMCPClient(config)
    return await client.get_tools()
```

- [ ] **Step 4: Run, expect 2 passed**

Run: `uv run pytest packages/python/vystak-template-langchain-python/tests/test_mcp.py -v`

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-template-langchain-python/_vystak/runtime/mcp.py packages/python/vystak-template-langchain-python/tests/test_mcp.py
git commit -m "feat(template): attach_mcp_servers integration"
```

### Task 4.4: build_prompt — prompt callable wires recall + prune + summary

**Files:**
- Create: `packages/python/vystak-template-langchain-python/_vystak/runtime/prompt_callable.py`
- Create: `packages/python/vystak-template-langchain-python/tests/test_prompt_callable.py`

- [ ] **Step 1: Write failing tests**

```python
"""build_prompt — system prompt assembly with memory + summary + prune."""

import pytest
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

from _vystak.runtime.prompt_callable import build_prompt


class _Compaction:
    mode = "conservative"
    prune_tool_output_bytes = 100
    trigger_pct = 0.5
    keep_recent_pct = 0.2
    target_tokens = None
    context_window = 1000


def _agent(instructions="You are helpful.", compaction=None):
    class _A:
        name = "weather"
    a = _A()
    a.instructions = instructions
    a.compaction = compaction
    a.memory = None
    return a


@pytest.mark.asyncio
async def test_prompt_builds_system_message_from_instructions():
    fn = build_prompt(_agent(), memory_mgr=None, compactor=None, pruner=None)
    state = {"messages": [HumanMessage(content="hi")]}
    config = {"configurable": {"thread_id": "t1", "user_id": "u1"}}
    result = await fn(state, config)
    assert isinstance(result[0], SystemMessage)
    assert "You are helpful." in result[0].content


@pytest.mark.asyncio
async def test_prompt_appends_recalled_memories():
    class FakeMemory:
        async def recall(self, *, user_id, query="", project_id="default"):
            return ["[user/m1] User likes pizza"]

    fn = build_prompt(_agent(), memory_mgr=FakeMemory(), compactor=None, pruner=None)
    state = {"messages": [HumanMessage(content="hi")]}
    config = {"configurable": {"thread_id": "t1", "user_id": "u1"}}
    result = await fn(state, config)
    sys_msg = result[0]
    assert "pizza" in sys_msg.content


@pytest.mark.asyncio
async def test_prompt_prunes_oversized_tool_messages():
    from _vystak.runtime.compaction.pruner import PreCallPruner

    big = "x" * 10_000
    msgs = [
        HumanMessage(content="q1"),
        ToolMessage(content=big, tool_call_id="t1"),
        HumanMessage(content="q2"),
        HumanMessage(content="q3"),
        HumanMessage(content="q4"),
    ]
    pruner = PreCallPruner(_Compaction())
    fn = build_prompt(_agent(compaction=_Compaction()), memory_mgr=None, compactor=None, pruner=pruner)
    state = {"messages": msgs}
    config = {"configurable": {"thread_id": "t1", "user_id": "u1"}}
    result = await fn(state, config)
    tool_msgs = [m for m in result if isinstance(m, ToolMessage)]
    assert len(tool_msgs[0].content) < 200
```

- [ ] **Step 2: Run, expect ImportError**

Run: `uv run pytest packages/python/vystak-template-langchain-python/tests/test_prompt_callable.py -v`

- [ ] **Step 3: Implement**

Create `_vystak/runtime/prompt_callable.py`:
```python
"""Build the prompt callable for LangGraph create_react_agent.

Per LangMem canonical pattern: this function is invoked fresh for every
turn, reconstructs the system message, applies Layer 1 prune, and inlines
any compaction summary as a SystemMessage at the top of the message list.
"""

from typing import Any

from langchain_core.messages import BaseMessage, SystemMessage


def build_prompt(agent: Any, *, memory_mgr: Any, compactor: Any, pruner: Any):
    instructions = (agent.instructions or "").strip()

    async def _prompt(state: dict, config: dict) -> list[BaseMessage]:
        messages: list[BaseMessage] = list(state.get("messages", []))

        if pruner is not None:
            messages = pruner.prune(messages)

        sys_parts = [instructions] if instructions else []

        if memory_mgr is not None:
            user_id = (config.get("configurable") or {}).get("user_id", "default")
            query = _last_human_text(messages)
            recalled = await memory_mgr.recall(user_id=user_id, query=query)
            if recalled:
                sys_parts.append("## Memory\n" + "\n".join(recalled))

        if compactor is not None:
            thread_id = (config.get("configurable") or {}).get("thread_id")
            if thread_id:
                latest = await compactor.store.latest(thread_id)
                if latest:
                    sys_parts.append(f"## Earlier conversation summary\n{latest['summary']}")

        sys_msg = SystemMessage(content="\n\n".join(sys_parts) or " ")
        return [sys_msg, *messages]

    return _prompt


def _last_human_text(messages: list[BaseMessage]) -> str:
    from langchain_core.messages import HumanMessage
    for m in reversed(messages):
        if isinstance(m, HumanMessage):
            return str(m.content)
    return ""
```

- [ ] **Step 4: Run, expect 3 passed**

Run: `uv run pytest packages/python/vystak-template-langchain-python/tests/test_prompt_callable.py -v`

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-template-langchain-python/_vystak/runtime/prompt_callable.py packages/python/vystak-template-langchain-python/tests/test_prompt_callable.py
git commit -m "feat(template): build_prompt callable"
```

### Task 4.5: build_graph — LangGraph react agent construction

**Files:**
- Create: `packages/python/vystak-template-langchain-python/_vystak/runtime/graph.py`
- Create: `packages/python/vystak-template-langchain-python/tests/test_graph.py`

- [ ] **Step 1: Write failing tests**

```python
"""build_graph — assembles create_react_agent from agent + tools + prompt."""

import pytest

from _vystak.runtime.graph import build_graph, build_model


def _agent(model_provider="anthropic"):
    from vystak.schema.agent import Agent
    from vystak.schema.model import Model
    from vystak.schema.provider import Provider
    return Agent(
        name="test",
        model=Model(
            provider=Provider(type=model_provider, api_key="test-key"),
            model_name="claude-sonnet-4-6",
        ),
    )


def test_build_model_returns_chat_anthropic_for_anthropic_provider():
    model = build_model(_agent("anthropic"))
    assert model.__class__.__name__ == "ChatAnthropic"


def test_build_model_returns_chat_openai_for_openai_provider():
    model = build_model(_agent("openai"))
    assert model.__class__.__name__ == "ChatOpenAI"


def test_build_graph_returns_compiled_graph():
    async def fake_prompt(state, config):
        return state["messages"]

    g = build_graph(_agent(), prompt=fake_prompt, tools=[], checkpointer=None)
    assert hasattr(g, "ainvoke") or hasattr(g, "invoke")
```

- [ ] **Step 2: Run, expect ImportError**

Run: `uv run pytest packages/python/vystak-template-langchain-python/tests/test_graph.py -v`

- [ ] **Step 3: Implement**

Create `_vystak/runtime/graph.py`:
```python
"""LangGraph react agent assembly."""

from typing import Any


PROVIDER_FACTORIES = {
    "anthropic": ("langchain_anthropic", "ChatAnthropic"),
    "openai": ("langchain_openai", "ChatOpenAI"),
}


def build_model(agent: Any):
    provider_type = agent.model.provider.type
    if provider_type not in PROVIDER_FACTORIES:
        raise ValueError(f"Unsupported provider: {provider_type}")
    module_name, cls_name = PROVIDER_FACTORIES[provider_type]
    module = __import__(module_name, fromlist=[cls_name])
    cls = getattr(module, cls_name)
    kwargs: dict[str, Any] = {"model": agent.model.model_name}
    api_key = getattr(agent.model.provider, "api_key", None)
    if api_key:
        kwargs["api_key"] = api_key
    base_url = getattr(agent.model.provider, "base_url", None)
    if base_url:
        kwargs["base_url"] = base_url
    return cls(**kwargs)


def build_graph(agent: Any, *, prompt, tools: list[Any], checkpointer: Any | None):
    from langgraph.prebuilt import create_react_agent

    model = build_model(agent)
    return create_react_agent(
        model=model,
        tools=tools,
        prompt=prompt,
        checkpointer=checkpointer,
    )
```

- [ ] **Step 4: Run, expect 3 passed**

Run: `uv run pytest packages/python/vystak-template-langchain-python/tests/test_graph.py -v`

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-template-langchain-python/_vystak/runtime/graph.py packages/python/vystak-template-langchain-python/tests/test_graph.py
git commit -m "feat(template): build_graph + build_model"
```

### Task 4.6: config — load_agent loader

**Files:**
- Create: `packages/python/vystak-template-langchain-python/_vystak/runtime/config.py`
- Create: `packages/python/vystak-template-langchain-python/tests/test_config.py`

- [ ] **Step 1: Write failing tests**

```python
"""load_agent reads vystak.yaml or vystak.py."""

from _vystak.runtime.config import load_agent


def test_load_yaml(tmp_path):
    f = tmp_path / "vystak.yaml"
    f.write_text(
        "name: test\n"
        "framework: langchain-python\n"
        "model:\n"
        "  provider:\n"
        "    type: anthropic\n"
        "  model_name: claude-sonnet-4-6\n"
    )
    a = load_agent(str(f))
    assert a.name == "test"


def test_load_py_module(tmp_path):
    f = tmp_path / "vystak.py"
    f.write_text(
        "from vystak.schema.agent import Agent\n"
        "from vystak.schema.model import Model\n"
        "from vystak.schema.provider import Provider\n"
        "agent = Agent(name='test', framework='langchain-python', "
        "model=Model(provider=Provider(type='anthropic'), model_name='claude-sonnet-4-6'))\n"
    )
    a = load_agent(str(f))
    assert a.name == "test"
```

- [ ] **Step 2: Run, expect ImportError**

Run: `uv run pytest packages/python/vystak-template-langchain-python/tests/test_config.py -v`

- [ ] **Step 3: Implement**

Create `_vystak/runtime/config.py`:
```python
"""Agent config loader — dispatches by extension to vystak.schema.loader."""

from pathlib import Path

from vystak.schema.agent import Agent
from vystak.schema.loader import load_agent as _load_yaml


def load_agent(path: str | Path) -> Agent:
    p = Path(path)
    if p.suffix in {".yaml", ".yml"}:
        return _load_yaml(p)
    if p.suffix == ".py":
        return _load_py(p)
    raise ValueError(f"Unsupported agent definition: {p}")


def _load_py(path: Path) -> Agent:
    import importlib.util
    spec = importlib.util.spec_from_file_location("_vystak_user_agent", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    agent = getattr(module, "agent", None)
    if agent is None:
        raise ValueError(f"{path} does not define a module-level `agent` binding")
    return agent
```

- [ ] **Step 4: Run, expect 2 passed**

Run: `uv run pytest packages/python/vystak-template-langchain-python/tests/test_config.py -v`

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-template-langchain-python/_vystak/runtime/config.py packages/python/vystak-template-langchain-python/tests/test_config.py
git commit -m "feat(template): load_agent for yaml + py"
```

### Task 4.7: Phase 4 release gate

- [ ] **Step 1: Full template tests**

Run: `uv run pytest packages/python/vystak-template-langchain-python/ -v`
Expected: all green.

- [ ] **Step 2: Global CI**

Run: `just lint-python && just test-python`

- [ ] **Step 3: Tag**

```bash
git tag -a phase-4-graph-extracted -m "Phase 4 complete: graph + checkpointer + mcp + tools + prompt + config"
```

---

## Phase 5 — Wire app_factory.build_agent_app

Compose all extracted components into one FastAPI app. This is what `server.py` calls at boot.

### Task 5.1: build_agent_app — FastAPI composition

**Files:**
- Create: `packages/python/vystak-template-langchain-python/_vystak/runtime/app_factory.py`
- Create: `packages/python/vystak-template-langchain-python/tests/test_app_factory.py`

- [ ] **Step 1: Write failing integration test**

```python
"""build_agent_app integration test — TestClient hits all routes."""

import pytest
from fastapi.testclient import TestClient

from _vystak.runtime.app_factory import build_agent_app


def _agent():
    from vystak.schema.agent import Agent
    from vystak.schema.model import Model
    from vystak.schema.provider import Provider
    return Agent(
        name="weather",
        framework="langchain-python",
        instructions="A weather agent.",
        model=Model(
            provider=Provider(type="anthropic", api_key="test-key"),
            model_name="claude-sonnet-4-6",
        ),
    )


def test_app_exposes_agent_card():
    app = build_agent_app(_agent())
    client = TestClient(app)
    r = client.get("/.well-known/agent.json")
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "weather"


def test_app_exposes_v1_models():
    app = build_agent_app(_agent())
    client = TestClient(app)
    r = client.get("/v1/models")
    assert r.status_code == 200
    body = r.json()
    assert any(m["id"] == "vystak/weather" for m in body["data"])


def test_app_healthz():
    app = build_agent_app(_agent())
    client = TestClient(app)
    r = client.get("/healthz")
    assert r.status_code == 200


def test_app_chat_completions_route_exists():
    app = build_agent_app(_agent())
    routes = [r.path for r in app.routes]
    assert "/v1/chat/completions" in routes
    assert "/v1/responses" in routes
    assert "/v1/responses/{response_id}" in routes
    assert "/a2a" in routes
```

- [ ] **Step 2: Run, expect ImportError**

Run: `uv run pytest packages/python/vystak-template-langchain-python/tests/test_app_factory.py -v`

- [ ] **Step 3: Implement**

Create `_vystak/runtime/app_factory.py`:
```python
"""FastAPI app composition. Single entry point: build_agent_app(agent)."""

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from _vystak.runtime.a2a.card import AgentCard
from _vystak.runtime.a2a.handler import A2AHandler
from _vystak.runtime.a2a.tasks import TaskManager
from _vystak.runtime.compaction.compactor import ThresholdCompactor
from _vystak.runtime.compaction.pruner import PreCallPruner
from _vystak.runtime.graph import build_graph
from _vystak.runtime.memory import MemoryManager
from _vystak.runtime.openai.chat import ChatCompletionsHandler
from _vystak.runtime.openai.responses import ResponsesHandler
from _vystak.runtime.prompt_callable import build_prompt
from _vystak.runtime.store import build_checkpointer
from _vystak.runtime.tools import load_user_tools


def build_agent_app(agent: Any) -> FastAPI:
    app = FastAPI()

    checkpointer = build_checkpointer(agent)
    user_tools = load_user_tools(agent, Path("tools"))
    memory_mgr = MemoryManager(agent, store=None) if agent.memory else None

    pruner = PreCallPruner(agent.compaction) if agent.compaction else None
    compactor = ThresholdCompactor(agent, store=None, summarizer=None) if agent.compaction else None

    prompt = build_prompt(agent, memory_mgr=memory_mgr, compactor=compactor, pruner=pruner)
    graph = build_graph(agent, prompt=prompt, tools=user_tools, checkpointer=checkpointer)

    a2a_handler = A2AHandler(agent=agent, graph=graph, task_manager=TaskManager())
    responses_handler = ResponsesHandler(agent=agent, graph=graph, store=None)
    chat_handler = ChatCompletionsHandler(agent=agent, graph=graph)

    @app.get("/healthz")
    async def healthz():
        return {"status": "ok"}

    @app.get("/.well-known/agent.json")
    async def agent_card():
        return AgentCard(agent).render()

    @app.get("/v1/models")
    async def list_models():
        return {
            "object": "list",
            "data": [{"id": f"vystak/{agent.name}", "object": "model", "owned_by": "vystak"}],
        }

    @app.post("/a2a")
    async def a2a(request: Request):
        payload = await request.json()
        if payload.get("method") == "tasks/sendSubscribe":
            async def gen():
                async for frame in a2a_handler.stream_dispatch(payload):
                    yield frame
            return StreamingResponse(gen(), media_type="text/event-stream")
        return JSONResponse(await a2a_handler.dispatch(payload))

    @app.post("/v1/chat/completions")
    async def chat_completions(request: Request):
        body = await request.json()
        return await chat_handler.create(body)

    @app.post("/v1/responses")
    async def create_response(request: Request):
        body = await request.json()
        result = await responses_handler.create(body)
        if hasattr(result, "__aiter__"):
            return StreamingResponse(result, media_type="text/event-stream")
        return result

    @app.get("/v1/responses/{response_id}")
    async def get_response(response_id: str):
        try:
            return await responses_handler.get(response_id)
        except KeyError:
            raise HTTPException(status_code=404, detail=f"Response not found: {response_id}")

    return app
```

- [ ] **Step 4: Run, expect 4 passed**

Run: `uv run pytest packages/python/vystak-template-langchain-python/tests/test_app_factory.py -v`

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-template-langchain-python/_vystak/runtime/app_factory.py packages/python/vystak-template-langchain-python/tests/test_app_factory.py
git commit -m "feat(template): build_agent_app FastAPI composition"
```

### Task 5.2: server.py imports and runs end-to-end

**Files:**
- Verify: `packages/python/vystak-template-langchain-python/server.py` (already exists from Task 0.1)

- [ ] **Step 1: Smoke test the entrypoint**

Run from the package directory:
```bash
cd packages/python/vystak-template-langchain-python && uv run python -c "
from _vystak.runtime.config import load_agent
from _vystak.runtime.app_factory import build_agent_app
agent = load_agent('vystak.yaml')
app = build_agent_app(agent)
print('OK: app built with', len(app.routes), 'routes')
"
```
Expected: prints `OK: app built with N routes` (N ≥ 7).

- [ ] **Step 2: Phase 5 release gate**

Run: `uv run pytest packages/python/vystak-template-langchain-python/ -v && just lint-python && just test-python`
Expected: all green.

- [ ] **Step 3: Tag**

```bash
git tag -a phase-5-app-factory-wired -m "Phase 5 complete: app_factory composes all components"
```

---

## Phase 6a — Add `Agent.framework` field + hash contribution

### Task 6a.1: Schema field with default

**Files:**
- Modify: `packages/python/vystak/src/vystak/schema/agent.py`
- Modify: `packages/python/vystak/tests/test_agent.py` (or wherever Agent tests live — verify with `find packages/python/vystak/tests -name "test_agent*.py"`)

- [ ] **Step 1: Write failing test**

Append to the existing Agent test file:
```python
def test_agent_framework_defaults_to_langchain_python():
    agent = _minimal_agent()
    assert agent.framework == "langchain-python"


def test_agent_framework_is_serialized_in_dump():
    agent = _minimal_agent()
    data = agent.model_dump()
    assert data["framework"] == "langchain-python"


def test_agent_framework_can_be_overridden():
    agent = Agent(
        name="t",
        framework="mastra-typescript",
        model=Model(provider=Provider(type="anthropic"), model_name="claude-sonnet-4-6"),
    )
    assert agent.framework == "mastra-typescript"
```

Where `_minimal_agent` is whatever fixture/helper already exists in that test module — match the existing pattern.

- [ ] **Step 2: Run, expect AttributeError on `agent.framework`**

Run: `uv run pytest packages/python/vystak/tests/test_agent.py -k framework -v`
Expected: failures because the field doesn't exist yet.

- [ ] **Step 3: Add field to Agent model**

In `packages/python/vystak/src/vystak/schema/agent.py`, add after the `name`-related fields and before `instructions`:
```python
    framework: str = "langchain-python"
```

- [ ] **Step 4: Run, expect 3 passed**

Run: `uv run pytest packages/python/vystak/tests/test_agent.py -k framework -v`

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak/src/vystak/schema/agent.py packages/python/vystak/tests/test_agent.py
git commit -m "feat(schema): add Agent.framework field (default langchain-python)"
```

### Task 6a.2: Hash contribution

**Files:**
- Modify: `packages/python/vystak/src/vystak/hash/tree.py`
- Modify: `packages/python/vystak/tests/test_hash_tree.py` (verify path with `find ... -name "test_hash*"`)

- [ ] **Step 1: Write failing test**

```python
def test_changing_framework_changes_root_hash():
    a1 = Agent(
        name="t", framework="langchain-python",
        model=Model(provider=Provider(type="anthropic"), model_name="claude-sonnet-4-6"),
    )
    a2 = Agent(
        name="t", framework="mastra-typescript",
        model=Model(provider=Provider(type="anthropic"), model_name="claude-sonnet-4-6"),
    )
    h1 = build_agent_hash_tree(a1)
    h2 = build_agent_hash_tree(a2)
    assert h1.root != h2.root
```

(Verify the actual hash-tree builder function name with `grep -n "def build_agent_hash" packages/python/vystak/src/vystak/hash/tree.py` — adjust if different.)

- [ ] **Step 2: Run, expect failure (root hashes equal)**

Run: `uv run pytest packages/python/vystak/tests/test_hash_tree.py -k framework -v`

- [ ] **Step 3: Include framework in root hash composition**

In `packages/python/vystak/src/vystak/hash/tree.py`, locate the function that computes the `root` hash for an Agent. Find the part that hashes the agent's identity-affecting fields (model, skills, etc.), and add the framework string into the input. Search for `agent.name` or `agent.model` to find the spot.

Add a line that includes `agent.framework` in the bytes fed into the root hashlib. Example pattern (adjust to match existing code style):
```python
parts = [
    agent.name.encode(),
    agent.framework.encode(),  # NEW
    brain_hash.encode(),
    # ...existing...
]
root = hashlib.sha256(b"|".join(parts)).hexdigest()
```

- [ ] **Step 4: Run, expect pass**

Run: `uv run pytest packages/python/vystak/tests/test_hash_tree.py -k framework -v`

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak/src/vystak/hash/tree.py packages/python/vystak/tests/test_hash_tree.py
git commit -m "feat(hash): Agent.framework contributes to root hash"
```

### Task 6a.3: TemplateManifest schema module

**Files:**
- Create: `packages/python/vystak/src/vystak/schema/manifest.py`
- Create: `packages/python/vystak/tests/test_manifest.py`

- [ ] **Step 1: Write failing tests**

```python
"""TemplateManifest schema validation."""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from vystak.schema.manifest import TemplateManifest, TemplateRef, VystakCompat


def _ok_payload():
    return {
        "schema_version": 1,
        "template": {"name": "langchain-python", "version": "0.1.0"},
        "vystak": {"schema_version": "0.5", "min_compat": "0.4", "max_compat": "0.5"},
        "scaffolded_at": datetime.now(timezone.utc).isoformat(),
        "scaffolded_by_cli": "1.4.0",
        "files": {"_vystak/runtime/app_factory.py": "sha256:abc"},
    }


def test_valid_manifest_parses():
    m = TemplateManifest(**_ok_payload())
    assert m.template.name == "langchain-python"
    assert m.schema_version == 1


def test_missing_required_field_raises():
    bad = _ok_payload()
    del bad["template"]
    with pytest.raises(ValidationError):
        TemplateManifest(**bad)


def test_files_dict_required():
    bad = _ok_payload()
    bad["files"] = "not-a-dict"
    with pytest.raises(ValidationError):
        TemplateManifest(**bad)
```

- [ ] **Step 2: Run, expect ImportError**

Run: `uv run pytest packages/python/vystak/tests/test_manifest.py -v`

- [ ] **Step 3: Implement schema module**

Create `packages/python/vystak/src/vystak/schema/manifest.py`:
```python
"""TemplateManifest — schema for _vystak/manifest.json."""

from datetime import datetime

from pydantic import BaseModel, Field


class TemplateRef(BaseModel):
    name: str
    version: str


class VystakCompat(BaseModel):
    schema_version: str
    min_compat: str
    max_compat: str


class TemplateManifest(BaseModel):
    schema_version: int = 1
    template: TemplateRef
    vystak: VystakCompat
    scaffolded_at: datetime
    scaffolded_by_cli: str
    files: dict[str, str] = Field(default_factory=dict)
```

- [ ] **Step 4: Run, expect 3 passed**

Run: `uv run pytest packages/python/vystak/tests/test_manifest.py -v`

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak/src/vystak/schema/manifest.py packages/python/vystak/tests/test_manifest.py
git commit -m "feat(schema): TemplateManifest model"
```

### Task 6a.4: Phase 6a release gate

- [ ] **Step 1: Run full vystak tests**

Run: `uv run pytest packages/python/vystak/ -v`

- [ ] **Step 2: Tag**

```bash
git tag -a phase-6a-schema -m "Phase 6a complete: Agent.framework + TemplateManifest schemas"
```

---

## Phase 6b — CLI: registry, init --framework, update, manifest writing

### Task 6b.1: Template registry discovery

**Files:**
- Create: `packages/python/vystak-cli/src/vystak_cli/templates.py`
- Create: `packages/python/vystak-cli/tests/test_templates.py`

- [ ] **Step 1: Write failing tests**

```python
"""Template registry discovery — bundled and dev-fallback paths."""

from pathlib import Path

from vystak_cli.templates import TemplateInfo, list_templates, resolve_template


def test_list_templates_returns_langchain_python_in_dev_workspace():
    infos = list_templates()
    names = [i.name for i in infos]
    assert "langchain-python" in names


def test_resolve_template_returns_path():
    info = resolve_template("langchain-python")
    assert isinstance(info, TemplateInfo)
    assert info.path.exists()
    assert (info.path / "_vystak" / "manifest.template.json").exists()


def test_resolve_unknown_raises():
    import pytest
    with pytest.raises(ValueError, match="Unknown framework"):
        resolve_template("nonexistent-framework")
```

- [ ] **Step 2: Run, expect ImportError**

Run: `uv run pytest packages/python/vystak-cli/tests/test_templates.py -v`

- [ ] **Step 3: Implement**

Create `packages/python/vystak-cli/src/vystak_cli/templates.py`:
```python
"""Template registry — bundled wheel path + dev sibling fallback."""

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class TemplateInfo:
    name: str
    version: str
    path: Path


def _bundled_dir() -> Path | None:
    """Path to vystak_cli/templates/ inside the installed CLI wheel."""
    import vystak_cli
    cli_root = Path(vystak_cli.__file__).parent
    bundled = cli_root / "templates"
    return bundled if bundled.exists() else None


def _dev_workspace_dir() -> Path | None:
    """Path to packages/python/ in editable workspace install."""
    import vystak_cli
    cli_root = Path(vystak_cli.__file__).parent
    # In editable install: <repo>/packages/python/vystak-cli/src/vystak_cli/
    candidate = cli_root.parent.parent.parent
    if candidate.name == "vystak-cli":
        workspace = candidate.parent
        if workspace.name == "python" and (workspace / "vystak-template-langchain-python").exists():
            return workspace
    return None


def list_templates() -> list[TemplateInfo]:
    bundled = _bundled_dir()
    if bundled:
        return _scan_bundled(bundled)
    dev = _dev_workspace_dir()
    if dev:
        return _scan_dev(dev)
    return []


def _scan_bundled(root: Path) -> list[TemplateInfo]:
    out = []
    for child in sorted(root.iterdir()):
        if child.is_dir() and (child / "_vystak" / "manifest.template.json").exists():
            seed = json.loads((child / "_vystak" / "manifest.template.json").read_text())
            out.append(TemplateInfo(
                name=seed["template"]["name"],
                version=seed["template"]["version"],
                path=child,
            ))
    return out


def _scan_dev(workspace: Path) -> list[TemplateInfo]:
    out = []
    for child in sorted(workspace.iterdir()):
        if not child.is_dir() or not child.name.startswith("vystak-template-"):
            continue
        seed_path = child / "_vystak" / "manifest.template.json"
        if seed_path.exists():
            seed = json.loads(seed_path.read_text())
            out.append(TemplateInfo(
                name=seed["template"]["name"],
                version=seed["template"]["version"],
                path=child,
            ))
    return out


def resolve_template(name: str) -> TemplateInfo:
    for info in list_templates():
        if info.name == name:
            return info
    raise ValueError(f"Unknown framework: {name!r}. Run `vystak init --list-frameworks` to see registry.")
```

- [ ] **Step 4: Run, expect 3 passed**

Run: `uv run pytest packages/python/vystak-cli/tests/test_templates.py -v`

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-cli/src/vystak_cli/templates.py packages/python/vystak-cli/tests/test_templates.py
git commit -m "feat(cli): template registry with bundled + dev-fallback discovery"
```

### Task 6b.2: Manifest writer — copy + hash + write

**Files:**
- Create: `packages/python/vystak-cli/src/vystak_cli/manifest.py`
- Create: `packages/python/vystak-cli/tests/test_manifest_writer.py`

- [ ] **Step 1: Write failing tests**

```python
"""Manifest writer — scaffold _vystak/, hash files, write manifest.json."""

import json
from pathlib import Path

from vystak_cli.manifest import scaffold_template


def test_scaffold_copies_tree(tmp_path):
    src = tmp_path / "src_template"
    (src / "_vystak" / "runtime").mkdir(parents=True)
    (src / "_vystak" / "manifest.template.json").write_text(
        json.dumps({
            "schema_version": 1,
            "template": {"name": "test-tpl", "version": "0.1.0"},
            "vystak": {"schema_version": "0.5", "min_compat": "0.4", "max_compat": "0.5"},
        })
    )
    (src / "_vystak" / "runtime" / "app_factory.py").write_text("# stub")
    (src / "server.py").write_text("# stub server")
    (src / "tests").mkdir()
    (src / "tests" / "test_x.py").write_text("# excluded")

    target = tmp_path / "dest"
    scaffold_template(src, target, cli_version="1.4.0")

    assert (target / "server.py").exists()
    assert (target / "_vystak" / "runtime" / "app_factory.py").exists()
    assert not (target / "tests").exists()  # excluded


def test_scaffold_writes_manifest_with_file_hashes(tmp_path):
    src = tmp_path / "src_template"
    (src / "_vystak").mkdir(parents=True)
    (src / "_vystak" / "manifest.template.json").write_text(
        json.dumps({
            "schema_version": 1,
            "template": {"name": "test-tpl", "version": "0.1.0"},
            "vystak": {"schema_version": "0.5", "min_compat": "0.4", "max_compat": "0.5"},
        })
    )
    (src / "_vystak" / "runtime").mkdir()
    (src / "_vystak" / "runtime" / "x.py").write_text("# x")

    target = tmp_path / "dest"
    scaffold_template(src, target, cli_version="1.4.0")

    manifest = json.loads((target / "_vystak" / "manifest.json").read_text())
    assert manifest["template"]["name"] == "test-tpl"
    assert manifest["scaffolded_by_cli"] == "1.4.0"
    assert "_vystak/runtime/x.py" in manifest["files"]
    assert manifest["files"]["_vystak/runtime/x.py"].startswith("sha256:")


def test_scaffold_overwrites_when_force(tmp_path):
    src = tmp_path / "src_template"
    (src / "_vystak").mkdir(parents=True)
    (src / "_vystak" / "manifest.template.json").write_text(
        json.dumps({
            "schema_version": 1,
            "template": {"name": "test-tpl", "version": "0.2.0"},
            "vystak": {"schema_version": "0.5", "min_compat": "0.4", "max_compat": "0.5"},
        })
    )
    target = tmp_path / "dest"
    target.mkdir()
    (target / "_vystak").mkdir()
    (target / "_vystak" / "stale.py").write_text("# stale")

    scaffold_template(src, target, cli_version="1.4.0", force=True)
    assert not (target / "_vystak" / "stale.py").exists()
```

- [ ] **Step 2: Run, expect ImportError**

Run: `uv run pytest packages/python/vystak-cli/tests/test_manifest_writer.py -v`

- [ ] **Step 3: Implement**

Create `packages/python/vystak-cli/src/vystak_cli/manifest.py`:
```python
"""Scaffold a template tree into a target dir and write manifest.json."""

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

EXCLUDED = {"tests", "_test_assets", "__pycache__"}


def scaffold_template(
    source: Path,
    target: Path,
    *,
    cli_version: str,
    force: bool = False,
) -> None:
    if target.exists():
        if not force and any(target.iterdir()):
            raise FileExistsError(f"{target} is not empty. Pass force=True or use --force.")
        if force:
            shutil.rmtree(target / "_vystak", ignore_errors=True)
    target.mkdir(parents=True, exist_ok=True)

    for entry in source.iterdir():
        if entry.name in EXCLUDED:
            continue
        dest = target / entry.name
        if entry.is_dir():
            shutil.copytree(entry, dest, dirs_exist_ok=force)
        else:
            shutil.copy2(entry, dest)

    seed = json.loads((target / "_vystak" / "manifest.template.json").read_text())
    file_hashes = _hash_tree(target / "_vystak")

    manifest = {
        "schema_version": 1,
        "template": seed["template"],
        "vystak": seed["vystak"],
        "scaffolded_at": datetime.now(timezone.utc).isoformat(),
        "scaffolded_by_cli": cli_version,
        "files": file_hashes,
    }
    (target / "_vystak" / "manifest.json").write_text(json.dumps(manifest, indent=2))


def _hash_tree(root: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.name == "manifest.json":
            continue
        rel = path.relative_to(root.parent).as_posix()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        out[rel] = f"sha256:{digest}"
    return out
```

- [ ] **Step 4: Run, expect 3 passed**

Run: `uv run pytest packages/python/vystak-cli/tests/test_manifest_writer.py -v`

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-cli/src/vystak_cli/manifest.py packages/python/vystak-cli/tests/test_manifest_writer.py
git commit -m "feat(cli): scaffold_template with manifest writer"
```

### Task 6b.3: `vystak init --framework` CLI integration

**Files:**
- Modify: `packages/python/vystak-cli/src/vystak_cli/commands/init.py`
- Create: `packages/python/vystak-cli/tests/test_init_framework.py`

- [ ] **Step 1: Inspect current `init.py`**

Run: `cat packages/python/vystak-cli/src/vystak_cli/commands/init.py`

Read the file fully — note the existing argparse setup, the function signature, where the legacy `init` writes its starter `vystak.yaml`. Plan changes to fit existing patterns (e.g. if the CLI uses click vs argparse, follow that).

- [ ] **Step 2: Write failing CLI integration test**

```python
"""vystak init --framework — scaffolds template into target dir."""

import json
from pathlib import Path

from vystak_cli.commands.init import init_command


def test_init_with_framework_scaffolds_template(tmp_path):
    target = tmp_path / "my-agent"
    init_command(target=str(target), framework="langchain-python", force=False)

    assert (target / "vystak.yaml").exists()
    assert (target / "server.py").exists()
    assert (target / "Dockerfile").exists()
    assert (target / "_vystak" / "manifest.json").exists()

    manifest = json.loads((target / "_vystak" / "manifest.json").read_text())
    assert manifest["template"]["name"] == "langchain-python"


def test_init_default_framework_is_langchain_python(tmp_path):
    target = tmp_path / "my-agent"
    init_command(target=str(target), framework=None, force=False)
    manifest = json.loads((target / "_vystak" / "manifest.json").read_text())
    assert manifest["template"]["name"] == "langchain-python"


def test_init_unknown_framework_errors(tmp_path):
    import pytest
    target = tmp_path / "my-agent"
    with pytest.raises(ValueError, match="Unknown framework"):
        init_command(target=str(target), framework="nonexistent", force=False)


def test_init_existing_dir_without_force_errors(tmp_path):
    import pytest
    target = tmp_path / "my-agent"
    target.mkdir()
    (target / "existing.txt").write_text("don't clobber me")
    with pytest.raises(FileExistsError):
        init_command(target=str(target), framework="langchain-python", force=False)


def test_init_list_frameworks(capsys):
    from vystak_cli.commands.init import list_frameworks_command
    list_frameworks_command()
    captured = capsys.readouterr()
    assert "langchain-python" in captured.out
```

- [ ] **Step 3: Run, expect failure (functions don't exist yet)**

Run: `uv run pytest packages/python/vystak-cli/tests/test_init_framework.py -v`

- [ ] **Step 4: Add `init_command` and `list_frameworks_command` to commands/init.py**

In `packages/python/vystak-cli/src/vystak_cli/commands/init.py`, add (alongside any existing init impl):
```python
from pathlib import Path

from vystak_cli.manifest import scaffold_template
from vystak_cli.templates import list_templates, resolve_template


def init_command(target: str, framework: str | None = None, force: bool = False) -> None:
    """Scaffold a new agent project from a framework template."""
    framework = framework or "langchain-python"
    info = resolve_template(framework)

    target_path = Path(target).resolve()
    cli_version = _cli_version()
    scaffold_template(info.path, target_path, cli_version=cli_version, force=force)
    print(f"Scaffolded {framework}@{info.version} into {target_path}")


def list_frameworks_command() -> None:
    """Print bundled frameworks."""
    for info in list_templates():
        print(f"{info.name}\t{info.version}")


def _cli_version() -> str:
    try:
        from importlib.metadata import version
        return version("vystak-cli")
    except Exception:  # noqa: BLE001
        return "dev"
```

Wire these into the existing CLI argparse/click structure. If `init` uses argparse, add:
```python
parser.add_argument("--framework", default=None, help="Template registry name")
parser.add_argument("--list-frameworks", action="store_true")
parser.add_argument("--force", action="store_true")
parser.add_argument("target", nargs="?", default=".")
```

And dispatch to `init_command` / `list_frameworks_command` accordingly.

- [ ] **Step 5: Run tests, expect 5 passed**

Run: `uv run pytest packages/python/vystak-cli/tests/test_init_framework.py -v`

- [ ] **Step 6: Smoke test the CLI from a real shell**

```bash
TMP=$(mktemp -d)
uv run vystak init "$TMP/my-agent" --framework langchain-python
ls "$TMP/my-agent/_vystak/"
rm -rf "$TMP"
```
Expected: `_vystak/` exists with `manifest.json`, `runtime/`, etc.

- [ ] **Step 7: Commit**

```bash
git add packages/python/vystak-cli/src/vystak_cli/commands/init.py packages/python/vystak-cli/tests/test_init_framework.py
git commit -m "feat(cli): vystak init --framework + --list-frameworks"
```

### Task 6b.4: `vystak update` command

**Files:**
- Create: `packages/python/vystak-cli/src/vystak_cli/commands/update.py`
- Modify: `packages/python/vystak-cli/src/vystak_cli/cli.py` (register `update` subcommand)
- Create: `packages/python/vystak-cli/tests/test_update.py`

- [ ] **Step 1: Write failing tests**

```python
"""vystak update — refresh _vystak/ to bundled CLI's template version."""

import json
from pathlib import Path

import pytest

from vystak_cli.commands.init import init_command
from vystak_cli.commands.update import update_command


def _scaffold(tmp_path) -> Path:
    target = tmp_path / "my-agent"
    init_command(target=str(target), framework="langchain-python", force=False)
    return target


def test_update_no_change_is_noop(tmp_path, capsys):
    target = _scaffold(tmp_path)
    rc = update_command(target=str(target))
    captured = capsys.readouterr()
    assert "current" in captured.out.lower() or rc == 0


def test_update_check_returns_zero_when_current(tmp_path):
    target = _scaffold(tmp_path)
    rc = update_command(target=str(target), check=True)
    assert rc == 0


def test_update_errors_on_framework_mismatch(tmp_path):
    target = _scaffold(tmp_path)
    yaml_path = target / "vystak.yaml"
    yaml_path.write_text(yaml_path.read_text().replace(
        "framework: langchain-python", "framework: mastra-typescript"
    ))
    with pytest.raises(ValueError, match="framework"):
        update_command(target=str(target))


def test_update_force_re_stamps_manifest(tmp_path):
    target = _scaffold(tmp_path)
    manifest_path = target / "_vystak" / "manifest.json"
    before = json.loads(manifest_path.read_text())["scaffolded_at"]
    import time
    time.sleep(1)
    update_command(target=str(target), force=True)
    after = json.loads(manifest_path.read_text())["scaffolded_at"]
    assert before != after
```

- [ ] **Step 2: Run, expect ImportError**

Run: `uv run pytest packages/python/vystak-cli/tests/test_update.py -v`

- [ ] **Step 3: Implement update_command**

Create `packages/python/vystak-cli/src/vystak_cli/commands/update.py`:
```python
"""vystak update — refresh _vystak/ to bundled template version."""

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from vystak_cli.manifest import scaffold_template, _hash_tree
from vystak_cli.templates import resolve_template


def update_command(
    target: str = ".",
    *,
    check: bool = False,
    force: bool = False,
    strict: bool = False,
) -> int:
    target_path = Path(target).resolve()
    manifest_path = target_path / "_vystak" / "manifest.json"
    yaml_path = target_path / "vystak.yaml"

    if not manifest_path.exists():
        raise FileNotFoundError(f"_vystak/manifest.json not found at {target_path}. Run vystak init first.")

    current = json.loads(manifest_path.read_text())
    current_template_name = current["template"]["name"]
    current_version = current["template"]["version"]

    # Resolve framework from vystak.yaml.
    if yaml_path.exists():
        framework_in_yaml = _read_framework(yaml_path)
        if framework_in_yaml and framework_in_yaml != current_template_name:
            raise ValueError(
                f"framework in vystak.yaml ({framework_in_yaml}) does not match "
                f"_vystak/manifest.json template.name ({current_template_name}). "
                f"Run: vystak init --framework {framework_in_yaml} --force ."
            )

    info = resolve_template(current_template_name)
    bundled_version = info.version

    current_hashes = current.get("files", {})
    bundled_hashes = _hash_tree(info.path / "_vystak")
    bundled_hashes_normalized = {k.replace("src_template/", ""): v for k, v in bundled_hashes.items()}

    is_current = (current_version == bundled_version) and not _hashes_differ(current_hashes, bundled_hashes_normalized)

    if check:
        print(f"current={current_version}, bundled={bundled_version}, in_sync={is_current}")
        return 0 if is_current else 1

    if is_current and not force:
        print(f"_vystak/ is current ({current_version}). Use --force to re-stamp.")
        return 0

    cli_version = _cli_version()
    shutil.rmtree(target_path / "_vystak", ignore_errors=True)
    scaffold_template(info.path, target_path, cli_version=cli_version, force=True)
    print(f"Updated _vystak/ from {current_version} → {bundled_version}.")
    return 0


def _read_framework(yaml_path: Path) -> str | None:
    import yaml
    data = yaml.safe_load(yaml_path.read_text())
    return data.get("framework") if isinstance(data, dict) else None


def _hashes_differ(a: dict[str, str], b: dict[str, str]) -> bool:
    return set(a.items()) != set(b.items())


def _cli_version() -> str:
    try:
        from importlib.metadata import version
        return version("vystak-cli")
    except Exception:  # noqa: BLE001
        return "dev"
```

- [ ] **Step 4: Register update subcommand in CLI**

Modify `packages/python/vystak-cli/src/vystak_cli/cli.py` (or wherever subparsers are defined). Add:
```python
upd = subparsers.add_parser("update", help="Refresh _vystak/ from bundled template.")
upd.add_argument("--check", action="store_true")
upd.add_argument("--force", action="store_true")
upd.add_argument("--strict", action="store_true")
upd.set_defaults(func=lambda args: update_command(target=".", check=args.check, force=args.force, strict=args.strict))
```

(Match the existing CLI dispatch pattern.)

- [ ] **Step 5: Run tests, expect 4 passed**

Run: `uv run pytest packages/python/vystak-cli/tests/test_update.py -v`

- [ ] **Step 6: Commit**

```bash
git add packages/python/vystak-cli/src/vystak_cli/commands/update.py packages/python/vystak-cli/src/vystak_cli/cli.py packages/python/vystak-cli/tests/test_update.py
git commit -m "feat(cli): vystak update command"
```

### Task 6b.5: Build hook — copy template into vystak-cli wheel

**Files:**
- Modify: `packages/python/vystak-cli/pyproject.toml`
- Create: `packages/python/vystak-cli/_build_hooks/copy_templates.py`

- [ ] **Step 1: Add a hatchling build hook**

Modify `packages/python/vystak-cli/pyproject.toml` to add the custom build hook section. Append to the existing `[build-system]` block (or `[tool.hatch.build]`):

```toml
[tool.hatch.build.hooks.custom]
path = "_build_hooks/copy_templates.py"

[tool.hatch.build.targets.wheel]
include = ["src/vystak_cli", "src/vystak_cli/templates/**"]
```

- [ ] **Step 2: Write the hook**

Create `packages/python/vystak-cli/_build_hooks/copy_templates.py`:
```python
"""Hatchling build hook — copy bundled templates into the wheel at build time."""

import shutil
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CopyTemplatesHook(BuildHookInterface):
    PLUGIN_NAME = "custom"

    def initialize(self, version, build_data):
        cli_root = Path(self.root)
        workspace = cli_root.parent  # packages/python/
        target = cli_root / "src" / "vystak_cli" / "templates"

        if target.exists():
            shutil.rmtree(target)
        target.mkdir(parents=True)

        for entry in workspace.iterdir():
            if not entry.is_dir() or not entry.name.startswith("vystak-template-"):
                continue
            template_name = entry.name.replace("vystak-template-", "")
            dest = target / template_name
            shutil.copytree(
                entry,
                dest,
                ignore=shutil.ignore_patterns("tests", "_test_assets", "__pycache__", "*.pyc"),
            )
```

- [ ] **Step 3: Verify the hook runs at build**

```bash
cd packages/python/vystak-cli
uv build --wheel
unzip -l dist/vystak_cli-*.whl | grep templates/langchain-python/_vystak | head -5
cd ../../..
```
Expected: the wheel contains `vystak_cli/templates/langchain-python/_vystak/...`.

- [ ] **Step 4: Verify dev path still works**

```bash
TMP=$(mktemp -d)
uv run vystak init "$TMP/dev-test" --framework langchain-python
ls "$TMP/dev-test/_vystak/"
rm -rf "$TMP"
```
Expected: scaffold succeeds via the dev-workspace fallback (the build hook only fires at wheel build).

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-cli/pyproject.toml packages/python/vystak-cli/_build_hooks/
git commit -m "feat(cli): hatchling build hook copies templates into wheel"
```

### Task 6b.6: Schema compatibility check in `vystak update`

**Files:**
- Modify: `packages/python/vystak-cli/src/vystak_cli/commands/update.py`
- Modify: `packages/python/vystak-cli/tests/test_update.py`

- [ ] **Step 1: Add failing test for compat check**

Append to `tests/test_update.py`:
```python
def test_update_warns_on_minor_version_drift(tmp_path, capsys, monkeypatch):
    target = _scaffold(tmp_path)
    # Pretend installed core is 0.5.5 but bundled template caps at 0.5.0.
    monkeypatch.setattr("vystak_cli.commands.update._installed_vystak_version", lambda: "0.5.5")
    monkeypatch.setattr("vystak_cli.commands.update._max_compat_for", lambda info: "0.5.0")
    update_command(target=str(target), force=True)
    captured = capsys.readouterr()
    assert "compat" in captured.out.lower() or "warn" in captured.out.lower()


def test_update_strict_refuses_on_major_drift(tmp_path, monkeypatch):
    import pytest
    target = _scaffold(tmp_path)
    monkeypatch.setattr("vystak_cli.commands.update._installed_vystak_version", lambda: "1.0.0")
    monkeypatch.setattr("vystak_cli.commands.update._max_compat_for", lambda info: "0.5.0")
    with pytest.raises(RuntimeError, match="incompatible"):
        update_command(target=str(target), strict=True)
```

- [ ] **Step 2: Run, expect AttributeError on the missing helpers**

Run: `uv run pytest packages/python/vystak-cli/tests/test_update.py -v -k compat`

- [ ] **Step 3: Add helpers + compat check to update.py**

In `packages/python/vystak-cli/src/vystak_cli/commands/update.py`, add:

```python
def _installed_vystak_version() -> str:
    from importlib.metadata import version
    return version("vystak")


def _max_compat_for(info) -> str:
    seed = json.loads((info.path / "_vystak" / "manifest.template.json").read_text())
    return seed["vystak"]["max_compat"]


def _min_compat_for(info) -> str:
    seed = json.loads((info.path / "_vystak" / "manifest.template.json").read_text())
    return seed["vystak"]["min_compat"]


def _semver_major(v: str) -> int:
    return int(v.split(".")[0])


def _check_compat(info, *, strict: bool) -> None:
    installed = _installed_vystak_version()
    max_v = _max_compat_for(info)
    min_v = _min_compat_for(info)

    major_drift = (
        _semver_major(installed) > _semver_major(max_v)
        or _semver_major(installed) < _semver_major(min_v)
    )
    if major_drift:
        if strict:
            raise RuntimeError(
                f"incompatible: installed vystak={installed} outside template's "
                f"compat range [{min_v}, {max_v}]. See _vystak/CHANGELOG.md."
            )
        print(
            f"WARNING: installed vystak={installed} outside template's compat "
            f"range [{min_v}, {max_v}]. Proceeding anyway."
        )
        return

    if installed != max_v:
        print(f"Note: installed vystak={installed}; template's max_compat={max_v}.")
```

Then in the body of `update_command`, after resolving `info` and before the `is_current` calculation, call:
```python
    _check_compat(info, strict=strict)
```

- [ ] **Step 4: Run, expect 2 new compat tests pass**

Run: `uv run pytest packages/python/vystak-cli/tests/test_update.py -v`

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-cli/src/vystak_cli/commands/update.py packages/python/vystak-cli/tests/test_update.py
git commit -m "feat(cli): vystak update schema-version compat check"
```

### Task 6b.7: `vystak apply` validates `_vystak/` and framework match

**Files:**
- Modify: `packages/python/vystak-cli/src/vystak_cli/commands/apply.py`
- Create: `packages/python/vystak-cli/tests/test_apply_validation.py`

- [ ] **Step 1: Inspect current apply.py**

```bash
cat packages/python/vystak-cli/src/vystak_cli/commands/apply.py
```

Find the entry function (likely `apply_command` or similar). Plan the insertion point: validation runs after loading `vystak.yaml` and before deploying.

- [ ] **Step 2: Write failing tests**

```python
"""vystak apply — validates _vystak/ exists and framework matches manifest."""

import pytest

from vystak_cli.commands.apply import _validate_template_for_apply


def test_apply_errors_when_vystak_dir_missing(tmp_path):
    (tmp_path / "vystak.yaml").write_text(
        "name: t\nframework: langchain-python\n"
        "model:\n  provider:\n    type: anthropic\n  model_name: claude-sonnet-4-6\n"
    )
    with pytest.raises(FileNotFoundError, match="_vystak"):
        _validate_template_for_apply(tmp_path)


def test_apply_errors_when_framework_mismatch(tmp_path):
    (tmp_path / "vystak.yaml").write_text(
        "name: t\nframework: mastra-typescript\n"
        "model:\n  provider:\n    type: anthropic\n  model_name: claude-sonnet-4-6\n"
    )
    (tmp_path / "_vystak").mkdir()
    import json
    (tmp_path / "_vystak" / "manifest.json").write_text(json.dumps({
        "schema_version": 1,
        "template": {"name": "langchain-python", "version": "0.1.0"},
        "vystak": {"schema_version": "0.5", "min_compat": "0.4", "max_compat": "0.5"},
        "scaffolded_at": "2026-05-02T15:30:00Z",
        "scaffolded_by_cli": "1.4.0",
        "files": {},
    }))
    with pytest.raises(ValueError, match="framework"):
        _validate_template_for_apply(tmp_path)


def test_apply_passes_when_framework_matches(tmp_path):
    (tmp_path / "vystak.yaml").write_text(
        "name: t\nframework: langchain-python\n"
        "model:\n  provider:\n    type: anthropic\n  model_name: claude-sonnet-4-6\n"
    )
    (tmp_path / "_vystak").mkdir()
    import json
    (tmp_path / "_vystak" / "manifest.json").write_text(json.dumps({
        "schema_version": 1,
        "template": {"name": "langchain-python", "version": "0.1.0"},
        "vystak": {"schema_version": "0.5", "min_compat": "0.4", "max_compat": "0.5"},
        "scaffolded_at": "2026-05-02T15:30:00Z",
        "scaffolded_by_cli": "1.4.0",
        "files": {},
    }))
    _validate_template_for_apply(tmp_path)  # no exception
```

- [ ] **Step 3: Run, expect AttributeError on `_validate_template_for_apply`**

Run: `uv run pytest packages/python/vystak-cli/tests/test_apply_validation.py -v`

- [ ] **Step 4: Add validation function and call it from apply_command**

In `packages/python/vystak-cli/src/vystak_cli/commands/apply.py`, add:

```python
import json
from pathlib import Path


def _validate_template_for_apply(project_dir: Path) -> None:
    manifest_path = project_dir / "_vystak" / "manifest.json"
    yaml_path = project_dir / "vystak.yaml"

    if not manifest_path.exists():
        raise FileNotFoundError(
            f"_vystak/manifest.json not found at {project_dir}. "
            f"Scaffold first: `vystak init --framework <name> --force .`"
        )

    if yaml_path.exists():
        import yaml as _yaml
        data = _yaml.safe_load(yaml_path.read_text()) or {}
        framework = data.get("framework")
        manifest = json.loads(manifest_path.read_text())
        template_name = manifest["template"]["name"]
        if framework and framework != template_name:
            raise ValueError(
                f"framework in vystak.yaml ({framework}) does not match "
                f"_vystak/manifest.json template.name ({template_name}). "
                f"Run: vystak init --framework {framework} --force ."
            )
```

In the apply entrypoint (find by reading `apply.py`), call `_validate_template_for_apply(project_dir)` immediately after resolving the project directory and before invoking the provider's `apply()`.

- [ ] **Step 5: Run, expect 3 passed**

Run: `uv run pytest packages/python/vystak-cli/tests/test_apply_validation.py -v`

- [ ] **Step 6: Commit**

```bash
git add packages/python/vystak-cli/src/vystak_cli/commands/apply.py packages/python/vystak-cli/tests/test_apply_validation.py
git commit -m "feat(cli): vystak apply validates _vystak/ + framework match"
```

### Task 6b.8: Phase 6b release gate

- [ ] **Step 1: Full CLI tests**

Run: `uv run pytest packages/python/vystak-cli/ -v`

- [ ] **Step 2: Global CI**

Run: `just lint-python && just test-python`

- [ ] **Step 3: Tag**

```bash
git tag -a phase-6b-cli -m "Phase 6b complete: init --framework + update + manifest"
```

---

## Phase 7 — Migrate one example (`hello-agent`) and add release cell

The first real-world end-to-end exercise. Prove the template path deploys an agent that actually works before committing to migrate every example.

### Task 7.1: Migrate hello-agent to template scaffold

**Files:**
- Modify: `examples/hello-agent/` (entire directory rewritten by scaffold)

- [ ] **Step 1: Save snapshot for rollback**

```bash
cp -r examples/hello-agent /tmp/hello-agent.codegen-backup
```

- [ ] **Step 2: Identify what to preserve**

```bash
ls examples/hello-agent/
cat examples/hello-agent/vystak.yaml
ls examples/hello-agent/tools/ 2>/dev/null || echo "no tools/"
cat examples/hello-agent/.env.example 2>/dev/null || echo "no .env.example"
```

Note: the existing `vystak.yaml`, any `tools/*.py`, and `.env.example` must survive. The Dockerfile and any generated artifacts get replaced.

- [ ] **Step 3: Scaffold template into the dir**

```bash
# Wipe what we'll regenerate, keep what's user-owned.
rm -rf examples/hello-agent/.vystak
uv run vystak init examples/hello-agent --framework langchain-python --force
```

The `--force` rewrites `_vystak/`, `server.py`, `Dockerfile`, `requirements.txt`. The existing `vystak.yaml` is overwritten by the starter — restore it next.

- [ ] **Step 4: Restore the original vystak.yaml content + add framework field**

```bash
cp /tmp/hello-agent.codegen-backup/vystak.yaml examples/hello-agent/vystak.yaml
```

Open `examples/hello-agent/vystak.yaml` and verify it has `framework: langchain-python`. If it doesn't (the original was from before Phase 6a), add it as the second field after `name:`. Restore any `tools/`, `.env.example`.

- [ ] **Step 5: Verify the agent loads**

```bash
cd examples/hello-agent
uv run python -c "
from _vystak.runtime.config import load_agent
from _vystak.runtime.app_factory import build_agent_app
agent = load_agent('vystak.yaml')
print('Agent name:', agent.name)
print('Framework:', agent.framework)
app = build_agent_app(agent)
print('Routes:', len(app.routes))
"
cd ../..
```
Expected: prints agent details and route count without error.

- [ ] **Step 6: Deploy via vystak apply (Docker)**

```bash
cd examples/hello-agent
cp .env.example .env  # add a real or sentinel ANTHROPIC_API_KEY
uv run vystak apply
```
Expected: Docker container builds and runs. Plan, apply, and the lifecycle should still work — `apply` now uses the user dir as the build context.

- [ ] **Step 7: Smoke test the deployed agent**

```bash
curl -s http://localhost:8080/.well-known/agent.json | head -20
curl -s http://localhost:8080/v1/models
```
Expected: agent card + `vystak/hello-agent` model listed.

- [ ] **Step 8: Tear down**

```bash
cd examples/hello-agent && uv run vystak destroy && cd ../..
rm -rf /tmp/hello-agent.codegen-backup
```

- [ ] **Step 9: Commit**

```bash
git add examples/hello-agent/
git commit -m "feat(examples): migrate hello-agent to framework template"
```

### Task 7.2: Add release-tier test cell exercising template path

**Files:**
- Create: `packages/python/vystak-provider-docker/tests/release/test_template_smoke.py`

- [ ] **Step 1: Inspect existing release test pattern**

```bash
ls packages/python/vystak-provider-docker/tests/release/
cat packages/python/vystak-provider-docker/tests/release/test_D1_docker_default_chat_http.py | head -40
```

Note the existing fixture pattern, the `release_smoke` marker, the project / vault_clean / postgres_clean fixtures.

- [ ] **Step 2: Write a release cell that scaffolds + applies + destroys via the template path**

Create `packages/python/vystak-provider-docker/tests/release/test_template_smoke.py`:
```python
"""Release cell: template-scaffolded agent — full deploy → verify → destroy."""

import json
import subprocess
from pathlib import Path

import pytest


pytestmark = pytest.mark.release_smoke


def test_template_scaffold_full_lifecycle(tmp_path, project):
    """V1-V5 + V9: scaffold, apply, agent card, models, destroy."""
    target = tmp_path / "tpl-agent"
    subprocess.run(
        ["uv", "run", "vystak", "init", str(target), "--framework", "langchain-python"],
        check=True,
        cwd=Path.cwd(),
    )
    assert (target / "_vystak" / "manifest.json").exists()

    # Inject a valid sentinel model + ensure framework key present.
    yaml_path = target / "vystak.yaml"
    yaml_path.write_text(
        "name: tpl-agent\n"
        "framework: langchain-python\n"
        "instructions: A test agent.\n"
        "model:\n"
        "  provider:\n"
        "    type: anthropic\n"
        "  model_name: claude-sonnet-4-6\n"
    )

    # Apply
    apply = subprocess.run(
        ["uv", "run", "vystak", "apply"],
        cwd=target,
        capture_output=True, text=True,
    )
    assert apply.returncode == 0, apply.stderr

    # Verify agent card
    import time
    time.sleep(2)
    import urllib.request
    body = json.loads(
        urllib.request.urlopen("http://localhost:8080/.well-known/agent.json").read()
    )
    assert body["name"] == "tpl-agent"

    # Destroy
    subprocess.run(["uv", "run", "vystak", "destroy"], cwd=target, check=True)
```

- [ ] **Step 3: Run the cell**

Run: `uv run pytest packages/python/vystak-provider-docker/tests/release/test_template_smoke.py -v -m release_smoke`
Expected: 1 passed (Docker daemon required).

- [ ] **Step 4: Commit**

```bash
git add packages/python/vystak-provider-docker/tests/release/test_template_smoke.py
git commit -m "test(release): template scaffold lifecycle smoke cell"
```

### Task 7.3: Phase 7 release gate

- [ ] **Step 1: Verify codegen path still works for unmigrated examples**

Pick any `examples/*` directory that wasn't migrated (e.g. `examples/multi-agent/`). Run:
```bash
cd examples/multi-agent
uv run vystak plan
cd ../..
```
Expected: plans without error — codegen path still alive.

- [ ] **Step 2: Tag**

```bash
git tag -a phase-7-first-example-migrated -m "Phase 7 complete: hello-agent on template path; release cell green"
```

---

## Phase 8a — Migrate every example to template

Migrate each `examples/*/` directory using the same recipe as Phase 7 / Task 7.1. One commit per example. Examples are listed in dependency order (simplest first).

For each example below, repeat this recipe:
1. `cp -r examples/<name> /tmp/<name>.backup`
2. `rm -rf examples/<name>/.vystak`
3. `uv run vystak init examples/<name> --framework langchain-python --force`
4. `cp /tmp/<name>.backup/vystak.yaml examples/<name>/vystak.yaml` (and verify `framework: langchain-python` is present)
5. Restore any `tools/`, `.env.example`, custom config files
6. `cd examples/<name> && uv run vystak plan && cd ../..` (verify it loads)
7. `git add examples/<name>/ && git commit -m "feat(examples): migrate <name> to framework template"`
8. `rm -rf /tmp/<name>.backup`

**Order:**
- [ ] **Task 8a.1:** `examples/time-agent`
- [ ] **Task 8a.2:** `examples/weather-agent` (or whichever simple agents exist)
- [ ] **Task 8a.3:** `examples/memory-agent`
- [ ] **Task 8a.4:** `examples/sessions-postgres`
- [ ] **Task 8a.5:** `examples/sessions-sqlite`
- [ ] **Task 8a.6:** `examples/multi-agent` (each agent dir migrated independently)
- [ ] **Task 8a.7:** `examples/docker-mcp`
- [ ] **Task 8a.8:** `examples/docker-compaction`
- [ ] **Task 8a.9:** `examples/docker-slack`
- [ ] **Task 8a.10:** `examples/docker-multi-chat-nats`
- [ ] **Task 8a.11:** `examples/azure-*` (each Azure example)
- [ ] **Task 8a.12:** Any remaining examples

To enumerate the full list:
```bash
ls examples/
```

For each migration, run the example's existing release cell (if any) afterward to confirm parity:
```bash
uv run pytest packages/python/vystak-provider-docker/tests/release/ -v -m release_smoke -k <example-name>
```

### Task 8a.13: Phase 8a release gate

- [ ] **Step 1: Run full release suite locally**

```bash
uv run pytest packages/python/vystak-provider-docker/tests/release/ -v \
  -m "release_smoke or release_integration or release_live_chat"
```
Expected: green; auto-skipped Slack-gated and Azure-gated cells.

- [ ] **Step 2: Verify all examples load**

```bash
for ex in examples/*/; do
    if [ -f "$ex/vystak.yaml" ]; then
        echo "=== $ex ==="
        (cd "$ex" && uv run vystak plan 2>&1 | head -3)
    fi
done
```
Expected: every example plans without error.

- [ ] **Step 3: Tag**

```bash
git tag -a phase-8a-examples-migrated -m "Phase 8a complete: every example uses template scaffold"
```

---

## Phase 8b — Drop the `Agent.framework` default; field becomes required

Now that every example has explicit `framework: langchain-python`, the default can be removed.

### Task 8b.1: Remove default from schema; add migration error

**Files:**
- Modify: `packages/python/vystak/src/vystak/schema/agent.py`
- Modify: `packages/python/vystak/tests/test_agent.py`

- [ ] **Step 1: Update tests**

Replace the "defaults to langchain-python" test with:
```python
def test_agent_framework_field_is_required():
    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError, match="framework"):
        Agent(
            name="t",
            model=Model(provider=Provider(type="anthropic"), model_name="claude-sonnet-4-6"),
        )
```

Update any other test fixture / helper that constructs `Agent(...)` without `framework=` to include `framework="langchain-python"`. Search:
```bash
grep -rn "Agent(" packages/python/vystak/tests/ | grep -v "framework="
```

- [ ] **Step 2: Run tests, expect failures**

Run: `uv run pytest packages/python/vystak/tests/ -v`
Expected: failures because the field still has a default.

- [ ] **Step 3: Drop the default**

In `packages/python/vystak/src/vystak/schema/agent.py`, change:
```python
    framework: str = "langchain-python"
```
to:
```python
    framework: str
```

- [ ] **Step 4: Run vystak tests, expect green**

Run: `uv run pytest packages/python/vystak/tests/ -v`

- [ ] **Step 5: Run full Python tests; fix any callers in other packages**

Run: `just test-python`
Expected: any package that constructs an `Agent(...)` without `framework=` will fail. Add `framework="langchain-python"` to test fixtures across `vystak-cli`, `vystak-provider-docker`, `vystak-provider-azure`, `vystak-channel-*`, `vystak-gateway`, etc. as needed.

```bash
grep -rn "Agent(" packages/python/ --include="*.py" | grep -v "framework=" | grep "tests/"
```

For each match, add `framework="langchain-python"` (or whatever framework it represents) to the constructor.

- [ ] **Step 6: Run full tests again**

Run: `just test-python && just lint-python`
Expected: green.

- [ ] **Step 7: Commit**

```bash
git add packages/python/
git commit -m "feat(schema)!: Agent.framework is now required; drop default"
```

### Task 8b.2: Phase 8b release gate

- [ ] **Step 1: Tag**

```bash
git tag -a phase-8b-framework-required -m "Phase 8b complete: framework field required, no default"
```

---

## Phase 9 — Delete `vystak-adapter-langchain` and codegen wiring

Final cleanup. The codegen path is no longer reachable from any example or test; remove it and its bundling.

### Task 9.1: Remove `vystak_adapter_langchain` from Docker provider's bundling

**Files:**
- Modify: `packages/python/vystak-provider-docker/src/vystak_provider_docker/nodes/agent.py`

- [ ] **Step 1: Inspect the bundling block**

```bash
sed -n '110,145p' packages/python/vystak-provider-docker/src/vystak_provider_docker/nodes/agent.py
```

Note line numbers of the `_bundled_mods` tuple and the `import vystak_adapter_langchain` line.

- [ ] **Step 2: Remove the import and tuple entry**

Edit `packages/python/vystak-provider-docker/src/vystak_provider_docker/nodes/agent.py`:

Remove the line:
```python
            import vystak_adapter_langchain
```

Remove `vystak_adapter_langchain,` from the `_bundled_mods` tuple. Update the leading comment block (lines 119-122) to drop the reference to `vystak_adapter_langchain`.

The tuple should become:
```python
            _bundled_mods = (
                vystak,
                vystak_transport_http,
                vystak_transport_nats,
            )
```

- [ ] **Step 3: Run docker provider tests**

Run: `uv run pytest packages/python/vystak-provider-docker/ -v -m "not docker"`
Expected: green.

- [ ] **Step 4: Smoke test a deployed agent (template path) still works**

```bash
cd examples/hello-agent
uv run vystak apply
sleep 3
curl -s http://localhost:8080/healthz
uv run vystak destroy
cd ../..
```
Expected: `{"status": "ok"}` from healthz.

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-provider-docker/src/vystak_provider_docker/nodes/agent.py
git commit -m "refactor(provider-docker): drop vystak_adapter_langchain bundling"
```

### Task 9.2: Remove `LangChainAdapter` references from CLI provider factory

**Files:**
- Modify: `packages/python/vystak-cli/src/vystak_cli/provider_factory.py`
- Modify: any other files that import `vystak_adapter_langchain`

- [ ] **Step 1: Find all references**

```bash
grep -rn "vystak_adapter_langchain\|LangChainAdapter" packages/python/ --include="*.py" | grep -v "vystak-adapter-langchain/"
```

- [ ] **Step 2: Remove each reference**

For each match outside the to-be-deleted package, remove the import and any remaining usage. The CLI's apply path no longer calls `LangChainAdapter.generate()` — it just builds the user dir as Docker context.

- [ ] **Step 3: Run lint + tests**

Run: `just lint-python && just test-python`
Expected: green.

- [ ] **Step 4: Commit**

```bash
git add packages/python/
git commit -m "refactor: drop all LangChainAdapter references"
```

### Task 9.3: Delete the `vystak-adapter-langchain` package

**Files:**
- Delete: `packages/python/vystak-adapter-langchain/` (entire directory)
- Modify: top-level `pyproject.toml`

- [ ] **Step 1: Remove from workspace pyproject.toml**

In `/Users/akolodkin/Developer/work/AgentsStack/pyproject.toml`:
- Remove `"vystak-adapter-langchain",` from `[tool.uv]` `dev-dependencies`
- Remove `vystak-adapter-langchain = { workspace = true }` from `[tool.uv.sources]`

- [ ] **Step 2: Delete the package**

```bash
git rm -r packages/python/vystak-adapter-langchain
```

- [ ] **Step 3: Re-sync workspace**

```bash
uv sync
```
Expected: completes without error; `vystak-adapter-langchain` is gone from installed packages.

- [ ] **Step 4: Run full CI**

Run: `just ci`
Expected: lint + tests green for all packages. (Pre-existing pyright + lint-typescript issues from CLAUDE.md are not introduced by this change.)

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "feat!: delete vystak-adapter-langchain package (replaced by template)"
```

### Task 9.4: Remove `codegen` field from AgentHashTree

**Files:**
- Modify: `packages/python/vystak/src/vystak/hash/tree.py`
- Modify: `packages/python/vystak/tests/test_hash_tree.py`

The `AgentHashTree.codegen` field captured the codegen output digest. With codegen gone, replace it with a `template` digest (manifest hash).

- [ ] **Step 1: Update tests**

Replace any test referencing `AgentHashTree.codegen` with `AgentHashTree.template` (a digest of the user's `_vystak/manifest.json` `template.name + template.version`).

```python
def test_template_field_in_hash_tree():
    a = Agent(
        name="t", framework="langchain-python",
        model=Model(provider=Provider(type="anthropic"), model_name="claude-sonnet-4-6"),
    )
    tree = build_agent_hash_tree(a, template_ref={"name": "langchain-python", "version": "0.6.2"})
    assert tree.template
    assert tree.root
```

- [ ] **Step 2: Run tests, expect failure**

- [ ] **Step 3: Replace `codegen` field with `template` field**

In `packages/python/vystak/src/vystak/hash/tree.py`:
```python
@dataclass
class AgentHashTree:
    # ... other fields unchanged ...
    template: str   # was: codegen
    root: str
```

Update the builder function to take a `template_ref: dict` argument and hash `template_ref["name"] + "@" + template_ref["version"]` into the `template` field. Wire callers in `vystak-cli` and providers to pass the manifest's `template` block.

- [ ] **Step 4: Run hash tree tests**

Run: `uv run pytest packages/python/vystak/tests/test_hash_tree.py -v`

- [ ] **Step 5: Update all callers of build_agent_hash_tree**

```bash
grep -rn "build_agent_hash_tree\|AgentHashTree" packages/python/ --include="*.py"
```

For each caller, pass the template_ref dict from `_vystak/manifest.json`. Most callers are in `vystak-provider-docker` and `vystak-provider-azure`.

- [ ] **Step 6: Run global tests**

Run: `just test-python && just lint-python`

- [ ] **Step 7: Commit**

```bash
git add packages/python/
git commit -m "refactor(hash): replace codegen digest with template digest in AgentHashTree"
```

### Task 9.5: Phase 9 release gate

- [ ] **Step 1: Full release suite**

Run: `uv run pytest packages/python/vystak-provider-docker/tests/release/ -v -m "release_smoke or release_integration"`
Expected: green.

- [ ] **Step 2: Final smoke test on hello-agent**

```bash
cd examples/hello-agent
uv run vystak apply
sleep 3
curl -s http://localhost:8080/v1/models
uv run vystak destroy
cd ../..
```

- [ ] **Step 3: Tag**

```bash
git tag -a phase-9-codegen-deleted -m "Phase 9 complete: vystak-adapter-langchain deleted"
```

- [ ] **Step 4: Update PROJECT_PLAN.md**

Modify `PROJECT_PLAN.md`:
- Move Phase 18 from "Planned" to "Complete"
- Add a "Phase 18: Framework Template Scaffold (Complete — 2026-XX-XX)" section under "What We Built"
- Update package status table: `vystak-adapter-langchain` row → remove; `vystak-template-langchain-python` row → add as Complete

- [ ] **Step 5: Final commit**

```bash
git add PROJECT_PLAN.md
git commit -m "docs(plan): record Phase 18 — Framework Template Scaffold"
```

---

## Self-review checklist (run before declaring complete)

- [ ] Every phase's release gate (`just lint-python && just test-python`) passes.
- [ ] `examples/hello-agent` deploys, responds, destroys cleanly via `vystak apply` / `vystak destroy`.
- [ ] `vystak init my-agent --framework langchain-python` scaffolds a runnable agent project.
- [ ] `vystak update` refreshes `_vystak/` in place; warns on framework mismatch.
- [ ] `vystak update --check` exits 0 when current, 1 when changes pending.
- [ ] `vystak.yaml` files for every example contain explicit `framework: langchain-python`.
- [ ] `Agent.framework` is required (no default).
- [ ] `vystak-adapter-langchain/` directory does not exist.
- [ ] `_bundled_mods` in Docker provider does not reference `vystak_adapter_langchain`.
- [ ] `AgentHashTree` has `template` field instead of `codegen` field.
- [ ] Release-tier matrix (16 cells) passes for green-able combinations (gated cells auto-skip).

---

## Open follow-ups (not in scope, captured for later)

- TypeScript template (`mastra-typescript`) — separate plan, but the registry seam is in place.
- Third-party / external templates (`pip install`able) — extend `templates.list_templates()` to scan an entry-point group.
- Object-form `framework: { name: ..., version: ... }` — only when multi-version-per-CLI is real.
- Migration of in-place pre-Phase-9 deployments — explicitly out of scope; users `destroy && init && apply`.







