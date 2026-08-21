# Human-in-the-Loop Tool Approvals Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A skill can mark tools `needs_approval`; calling one parks the run durably before execution, a human approves/denies from the panel or Slack, and the turn resumes from its exact point — approval executes the tool, denial resolves it to a standardized denied result.

**Architecture:** A tool wrapper at the `app_factory` tool-assembly choke point calls LangGraph `interrupt()` with a structured payload before executing a gated tool. The existing durable-execution park/resume machinery carries the rest: the checkpoint endpoint exposes the interrupt payload, the NATS bridge publishes a non-terminal `vystak.approval.requested` event and guards `resumeDetached` to parked-only, the A2A executor returns an approval-pending reply for the Slack path, and both surfaces resume with `Command(resume={approved, decided_by, note})`.

**Tech Stack:** Python 3.11+, Pydantic, LangGraph (`interrupt`/`Command`), a2a-sdk, nats-py, FastAPI, slack-bolt (Socket Mode Block Kit), Next.js + AI SDK v5 (vendored AI Elements), pytest / vitest.

**Spec:** `docs/superpowers/specs/2026-08-20-hitl-tool-approvals-design.md`

## Global Constraints

- **Never edit `packages/python/vystak-cli/src/vystak_cli/templates/`** — build-hook output, gitignored. Source of truth is `packages/python/vystak-template-langchain-python/`.
- **Agent images pip-install bare `vystak` from PyPI, and pydantic's default `extra="ignore"` silently DROPS unknown fields.** The template runtime must therefore read `needs_approval` from the raw bundled `agent.json` (plain `json.load`), preferring the typed field only when the installed schema knows it. No agent-side code may *require* the new schema field to exist.
- **Channel containers install the `REQUIREMENTS` string in `server_template.py`, not `pyproject.toml`.** Any new runtime dependency for a channel package lands there in the same commit (none is expected).
- **The four live CI gates** — `just lint-python`, `just test-python`, `just typecheck-typescript`, `just test-typescript` — must stay green. `just typecheck-python` and `just lint-typescript` are known-red on main.
- **Never run repo-wide `just fmt-python`.** Public repo: placeholders in examples (`<your-api-key>`), obvious fakes in tests.
- Decision object (exact contract, used verbatim everywhere): `{"approved": bool, "decided_by": str, "note": str | null}`.
- Interrupt payload (exact contract): `{"kind": "tool_approval", "tool": str, "args": dict, "skill": str}`.
- Denied tool result (exact string): `f"Denied by {decided_by}: {note or 'no reason given'}"`.
- First decision wins: resuming a non-`parked` turn is a JSON-RPC error `-32602` with message `"turn is not parked"`.
- Deny is NOT an error: no `response.failed`, no `is_error` tool result; the turn completes normally.
- v1 non-goals: MCP tool gating, approver authorization lists, argument-conditional gates, auto-deny TTLs, Discord.

---

### Task 1: `Skill.needs_approval` schema field + validation + hashing

**Files:**
- Modify: `packages/python/vystak/src/vystak/schema/skill.py`
- Modify: `packages/python/vystak/src/vystak/schema/loader.py` (single-agent validation)
- Modify: `packages/python/vystak/src/vystak/schema/multi_loader.py` (multi-doc validation)
- Modify: `packages/python/vystak/src/vystak/hash/tree.py` (deploy-identity contribution)
- Test: `packages/python/vystak/tests/test_skill_needs_approval.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces: `Skill.needs_approval: list[str] = []`; loaders raise `ValueError` naming the offending skill/tool when a `needs_approval` entry is not in that skill's `tools`; the field contributes to the agent hash.

- [ ] **Step 1: Write the failing test**

```python
# packages/python/vystak/tests/test_skill_needs_approval.py
import pytest

from vystak.schema import Skill
from vystak.schema.skill import validate_needs_approval


def test_field_defaults_empty():
    s = Skill(name="ops", tools=["restart_service"])
    assert s.needs_approval == []


def test_field_accepts_subset_of_tools():
    s = Skill(name="ops", tools=["restart_service", "read_logs"],
              needs_approval=["restart_service"])
    assert s.needs_approval == ["restart_service"]


def test_validate_rejects_unknown_tool():
    s = Skill(name="ops", tools=["read_logs"], needs_approval=["restart_service"])
    with pytest.raises(ValueError, match="ops.*restart_service"):
        validate_needs_approval(s)


def test_validate_accepts_valid_skill():
    s = Skill(name="ops", tools=["restart_service"], needs_approval=["restart_service"])
    validate_needs_approval(s)  # no raise


def test_hash_changes_with_needs_approval():
    from vystak.hash.tree import AgentHashTree
    from vystak.schema import Agent

    base = dict(name="a", framework="langchain-python",
                skills=[Skill(name="ops", tools=["t"])])
    gated = dict(name="a", framework="langchain-python",
                 skills=[Skill(name="ops", tools=["t"], needs_approval=["t"])])
    h1 = AgentHashTree.from_agent(Agent(**base)).root
    h2 = AgentHashTree.from_agent(Agent(**gated)).root
    assert h1 != h2
```

Note: adapt the two hash-test lines mechanically to `AgentHashTree`'s real constructor/accessor (check `vystak/hash/tree.py` — the point is only "field changes hash"). `Agent(**base)` may need other required fields per current fixtures — copy whatever minimal kwargs existing `Agent` tests use.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/python/vystak/tests/test_skill_needs_approval.py -v`
Expected: FAIL — `Skill` has no field `needs_approval` / no `validate_needs_approval`.

- [ ] **Step 3: Write minimal implementation**

In `skill.py`, add to `Skill`:

```python
needs_approval: list[str] = []
```

and a module-level validator:

```python
def validate_needs_approval(skill: "Skill") -> None:
    """Every needs_approval entry must be one of the skill's own tools."""
    unknown = [t for t in skill.needs_approval if t not in skill.tools]
    if unknown:
        raise ValueError(
            f"skill '{skill.name}': needs_approval names tools not in its "
            f"tools list: {', '.join(unknown)}"
        )
```

Call `validate_needs_approval(skill)` for every skill wherever the loaders already run per-skill validation: in `loader.py`'s `load_agent` path and `multi_loader.py`'s agent resolution (find where `resolve_folder_skills` or equivalent per-skill processing runs and add the call beside it — same error-surfacing style as neighboring validations).

In `hash/tree.py`, include `needs_approval` in the skill hash contribution the same way `tools` is included (find where skill fields feed the tree and add the field alongside).

- [ ] **Step 4: Run tests to verify they pass, plus package suite**

Run: `uv run pytest packages/python/vystak/tests/ -v` and `uv run ruff check packages/python/vystak/`
Expected: PASS / clean. Fix any fixtures that enumerate Skill fields.

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak/src/vystak/schema/skill.py \
        packages/python/vystak/src/vystak/schema/loader.py \
        packages/python/vystak/src/vystak/schema/multi_loader.py \
        packages/python/vystak/src/vystak/hash/tree.py \
        packages/python/vystak/tests/test_skill_needs_approval.py
git commit -m "feat(schema): Skill.needs_approval with load-time validation"
```

---

### Task 2: Approval gate module in the template runtime

**Files:**
- Create: `packages/python/vystak-template-langchain-python/_vystak/runtime/approvals.py`
- Test: `packages/python/vystak-template-langchain-python/tests/test_approvals.py` (create)

**Interfaces:**
- Consumes: nothing (standalone module).
- Produces: `load_approval_map(agent, project_root) -> dict[str, str]` (tool name → skill name, for every gated tool); `wrap_tools_with_approval(tools: list, approval_map: dict[str, str]) -> list` (same-length list; gated tools wrapped, others returned as-is).

- [ ] **Step 1: Write the failing test**

```python
# packages/python/vystak-template-langchain-python/tests/test_approvals.py
import json

import pytest
from langchain_core.tools import tool

from _vystak.runtime.approvals import load_approval_map, wrap_tools_with_approval


class _Skill:
    def __init__(self, name, tools, needs_approval=None):
        self.name = name
        self.tools = tools
        self.needs_approval = needs_approval or []


class _Agent:
    def __init__(self, skills):
        self.skills = skills


def test_map_from_typed_field(tmp_path):
    agent = _Agent([_Skill("ops", ["restart"], needs_approval=["restart"])])
    assert load_approval_map(agent, tmp_path) == {"restart": "ops"}


def test_map_falls_back_to_raw_agent_json(tmp_path):
    # Simulates an older PyPI vystak whose Skill model dropped the field:
    # the typed object has no needs_approval, but the bundled JSON does.
    class _BareSkill:
        def __init__(self, name, tools):
            self.name = name
            self.tools = tools

    agent = _Agent([_BareSkill("ops", ["restart"])])
    (tmp_path / "agent.json").write_text(json.dumps({
        "name": "a",
        "skills": [{"name": "ops", "tools": ["restart"],
                    "needs_approval": ["restart"]}],
    }))
    assert load_approval_map(agent, tmp_path) == {"restart": "ops"}


def test_map_empty_when_nothing_gated(tmp_path):
    agent = _Agent([_Skill("ops", ["restart"])])
    assert load_approval_map(agent, tmp_path) == {}


@tool
async def dangerous(x: int) -> str:
    """Do something dangerous."""
    return f"did {x}"


def test_ungated_tools_pass_through_identically():
    out = wrap_tools_with_approval([dangerous], {})
    assert out == [dangerous]


def test_wrapped_tool_preserves_metadata():
    (wrapped,) = wrap_tools_with_approval([dangerous], {"dangerous": "ops"})
    assert wrapped is not dangerous
    assert wrapped.name == "dangerous"
    assert wrapped.description == dangerous.description
    assert wrapped.args_schema is not None


@pytest.mark.asyncio
async def test_approved_decision_executes_tool(monkeypatch):
    seen = {}

    def fake_interrupt(payload):
        seen["payload"] = payload
        return {"approved": True, "decided_by": "qa@example.com", "note": None}

    monkeypatch.setattr("_vystak.runtime.approvals.interrupt", fake_interrupt)
    (wrapped,) = wrap_tools_with_approval([dangerous], {"dangerous": "ops"})
    result = await wrapped.ainvoke({"x": 7})
    assert result == "did 7"
    assert seen["payload"] == {
        "kind": "tool_approval", "tool": "dangerous",
        "args": {"x": 7}, "skill": "ops",
    }


@pytest.mark.asyncio
async def test_denied_decision_returns_denied_string(monkeypatch):
    monkeypatch.setattr(
        "_vystak.runtime.approvals.interrupt",
        lambda payload: {"approved": False, "decided_by": "qa@example.com",
                         "note": "too risky"},
    )
    (wrapped,) = wrap_tools_with_approval([dangerous], {"dangerous": "ops"})
    result = await wrapped.ainvoke({"x": 7})
    assert result == "Denied by qa@example.com: too risky"


@pytest.mark.asyncio
async def test_denied_without_note_uses_default(monkeypatch):
    monkeypatch.setattr(
        "_vystak.runtime.approvals.interrupt",
        lambda payload: {"approved": False, "decided_by": "qa@example.com",
                         "note": None},
    )
    (wrapped,) = wrap_tools_with_approval([dangerous], {"dangerous": "ops"})
    assert (await wrapped.ainvoke({"x": 7})) == \
        "Denied by qa@example.com: no reason given"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/python/vystak-template-langchain-python/tests/test_approvals.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named '_vystak.runtime.approvals'`

- [ ] **Step 3: Write minimal implementation**

```python
# _vystak/runtime/approvals.py
"""Human-in-the-loop approval gate for skill tools.

A tool named in a skill's `needs_approval` is wrapped so the run parks
(via LangGraph interrupt()) BEFORE the tool executes. The resume value is
the decision: {"approved": bool, "decided_by": str, "note": str | null}.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from langchain_core.tools import StructuredTool
from langgraph.types import interrupt


def load_approval_map(agent: Any, project_root: Path | str) -> dict[str, str]:
    """tool name -> skill name for every gated tool.

    Prefers the typed `Skill.needs_approval` field; falls back to the raw
    bundled agent.json because a pip-installed `vystak` older than the
    field silently drops it (pydantic extra="ignore").
    """
    out: dict[str, str] = {}
    for skill in getattr(agent, "skills", None) or []:
        for tool_name in getattr(skill, "needs_approval", None) or []:
            out[tool_name] = skill.name
    if out:
        return out
    bundled = Path(project_root) / "agent.json"
    if bundled.exists():
        try:
            raw = json.loads(bundled.read_text())
        except (OSError, json.JSONDecodeError):
            return out
        for skill in raw.get("skills") or []:
            for tool_name in skill.get("needs_approval") or []:
                out[tool_name] = skill.get("name", "")
    return out


def _denied_result(decision: dict) -> str:
    who = decision.get("decided_by") or "unknown"
    note = decision.get("note") or "no reason given"
    return f"Denied by {who}: {note}"


def wrap_tools_with_approval(tools: list, approval_map: dict[str, str]) -> list:
    if not approval_map:
        return list(tools)

    wrapped = []
    for t in tools:
        name = getattr(t, "name", None)
        if name not in approval_map:
            wrapped.append(t)
            continue
        wrapped.append(_wrap_one(t, approval_map[name]))
    return wrapped


def _wrap_one(original: Any, skill_name: str) -> StructuredTool:
    async def _gated(**kwargs: Any) -> Any:
        decision = interrupt({
            "kind": "tool_approval",
            "tool": original.name,
            "args": kwargs,
            "skill": skill_name,
        })
        if isinstance(decision, dict) and decision.get("approved"):
            return await original.ainvoke(kwargs)
        return _denied_result(decision if isinstance(decision, dict) else {})

    return StructuredTool.from_function(
        coroutine=_gated,
        name=original.name,
        description=original.description,
        args_schema=original.args_schema,
    )
```

Adapt mechanically if `StructuredTool.from_function` requires different kwargs in the installed langchain-core; the contract is: same name/description/args schema, coroutine gates then delegates.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest packages/python/vystak-template-langchain-python/tests/test_approvals.py -v` then `uv run ruff check packages/python/vystak-template-langchain-python/`
Expected: PASS / clean.

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-template-langchain-python/_vystak/runtime/approvals.py \
        packages/python/vystak-template-langchain-python/tests/test_approvals.py
git commit -m "feat(template): approval gate wrapper parking gated tools via interrupt()"
```

---

### Task 3: Wire the gate into `app_factory` + expose interrupt payloads on the checkpoint route

**Files:**
- Modify: `packages/python/vystak-template-langchain-python/_vystak/runtime/app_factory.py`
- Test: `packages/python/vystak-template-langchain-python/tests/test_app_factory_approvals.py` (create)

**Interfaces:**
- Consumes: Task 2's `load_approval_map` / `wrap_tools_with_approval`.
- Produces: gated tools are wrapped at BOTH `build_graph` call sites (initial build ~line 120 and the lifespan MCP-rebuild ~line 169); `GET /v1/_vystak/checkpoint` response gains `"interrupts": [<payload>, ...]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_app_factory_approvals.py
import pytest
from httpx import ASGITransport, AsyncClient


@pytest.mark.asyncio
async def test_checkpoint_route_returns_interrupts(monkeypatch):
    """The checkpoint route surfaces snapshot.tasks[*].interrupts values."""
    from _vystak.runtime import app_factory

    payload = {"kind": "tool_approval", "tool": "dangerous",
               "args": {"x": 1}, "skill": "ops"}

    class _Interrupt:
        value = payload

    class _Task:
        interrupts = (_Interrupt(),)

    class _Snapshot:
        config = {"configurable": {"checkpoint_id": "ck-1"}}
        next = ("tools",)
        tasks = (_Task(),)

    app = app_factory.build_agent_app(_minimal_agent())  # reuse the fixture
    # the existing checkpoint tests in test_app_factory.py show how the
    # graph is stubbed; mirror that pattern:
    async def fake_aget_state(config):
        return _Snapshot()

    app.state.graph.aget_state = fake_aget_state  # adapt to the real seam
    async with AsyncClient(transport=ASGITransport(app=app),
                           base_url="http://t") as client:
        resp = await client.get("/v1/_vystak/checkpoint",
                                params={"thread_id": "t1"})
    body = resp.json()
    assert body["interrupted"] is True
    assert body["interrupts"] == [payload]
```

IMPORTANT: `tests/test_app_factory.py` already has three `/v1/_vystak/checkpoint` tests with a working stubbing pattern (real compiled graph + mocked `aget_state`) — copy that pattern exactly rather than inventing `_minimal_agent`; the sketch above shows only the assertion intent. Also add: a test that a gated tool in a skill's `needs_approval` produces a wrapped tool in the graph's tool set (assert via the tools passed to a monkeypatched `build_graph` — capture its `tools=` kwarg and check the gated tool object is not the original but has the same name), and that the wrap ALSO applies at the lifespan rebuild call site (drive the app lifespan the way `test_lifespan_wires_checkpoint_observer_onto_state` does, with a fake MCP attach returning one tool).

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/python/vystak-template-langchain-python/tests/test_app_factory_approvals.py -v`
Expected: FAIL — response has no `interrupts` key / tools not wrapped.

- [ ] **Step 3: Write minimal implementation**

In `app_factory.py`:

1. Import: `from _vystak.runtime.approvals import load_approval_map, wrap_tools_with_approval`.
2. After the five tool lists are built and before the FIRST `build_graph` call:

```python
approval_map = load_approval_map(agent, project_root)
all_tools = wrap_tools_with_approval(
    user_tools + workspace_tools + subagent_tools + skill_tools + schedule_tools,
    approval_map,
)
graph = build_graph(agent, prompt=prompt, tools=all_tools,
                    checkpointer=initial_checkpointer)
```

(`project_root` is whatever the factory already uses to locate the bundled config — see `config.py`'s loading; pass the same directory.)

3. At the lifespan rebuild site, apply the same wrapping to the concatenated list INCLUDING `mcp_tools` (MCP tools won't match the map in v1 — harmless):

```python
new_graph = build_graph(
    agent, prompt=prompt,
    tools=wrap_tools_with_approval(
        user_tools + workspace_tools + subagent_tools + skill_tools
        + schedule_tools + mcp_tools,
        approval_map,
    ),
    checkpointer=resolved,
)
```

4. Extend the checkpoint route:

```python
@app.get("/v1/_vystak/checkpoint")
async def _vystak_checkpoint(thread_id: str):
    config = {"configurable": {"thread_id": thread_id}}
    snapshot = await responses_handler.graph.aget_state(config)
    checkpoint_id = None
    interrupted = False
    interrupts: list = []
    if snapshot is not None:
        if snapshot.config:
            checkpoint_id = snapshot.config.get("configurable", {}).get("checkpoint_id")
        interrupted = bool(snapshot.next)
        for task in getattr(snapshot, "tasks", None) or ():
            for intr in getattr(task, "interrupts", None) or ():
                interrupts.append(getattr(intr, "value", None))
    return {"checkpoint_id": checkpoint_id, "interrupted": interrupted,
            "interrupts": interrupts}
```

- [ ] **Step 4: Run the full template suite**

Run: `uv run pytest packages/python/vystak-template-langchain-python/tests/ -v` and `uv run ruff check packages/python/vystak-template-langchain-python/`
Expected: PASS (existing checkpoint tests must be updated to expect the new `interrupts: []` key) / clean.

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-template-langchain-python/_vystak/runtime/app_factory.py \
        packages/python/vystak-template-langchain-python/tests/
git commit -m "feat(template): wrap gated tools at both graph builds; expose interrupt payloads"
```

---

### Task 4: Bridge — `vystak.approval.requested` event, turnStatus payload, parked-only resume guard

**Files:**
- Modify: `packages/python/vystak-template-langchain-python/_vystak/runtime/nats_bridge.py`
- Test: `packages/python/vystak-template-langchain-python/tests/test_nats_bridge_approvals.py` (create)

**Interfaces:**
- Consumes: Task 3's checkpoint-route `interrupts` field.
- Produces: on park, a non-terminal seq'd JetStream event `{"type": "vystak.approval.requested", "payload": <interrupt payload>}`; `responses/turnStatus` reply gains `"interrupt": <payload> | null` when status is `parked`; `_handle_resume_detached` rejects non-parked rows with JSON-RPC error `-32602` `"turn is not parked"`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_nats_bridge_approvals.py
import json

import pytest

from _vystak.runtime.turn_journal import InMemoryTurnJournal

PAYLOAD = {"kind": "tool_approval", "tool": "dangerous",
           "args": {"x": 1}, "skill": "ops"}


@pytest.mark.asyncio
async def test_park_publishes_approval_requested_event(bridge_factory):
    journal = InMemoryTurnJournal()
    bridge = bridge_factory(
        journal=journal,
        sse_events=[{"type": "response.created", "response": {"id": "resp_1"}}],
        checkpoint_state={"checkpoint_id": "ck", "interrupted": True,
                          "interrupts": [PAYLOAD]},
    )
    await journal.create("t1", "s.t1", {})
    await bridge._run_detached({"input": "hi"}, "s.t1", "t1")

    assert (await journal.get("t1")).status == "parked"
    events = [json.loads(p)["event"] for p in bridge.published_payloads]
    approvals = [e for e in events if e["type"] == "vystak.approval.requested"]
    assert approvals == [{"type": "vystak.approval.requested", "payload": PAYLOAD}]
    # non-terminal: no response.failed / response.completed after it
    assert "response.failed" not in [e["type"] for e in events]


@pytest.mark.asyncio
async def test_turn_status_carries_interrupt_when_parked(bridge_factory):
    journal = InMemoryTurnJournal()
    await journal.create("t1", "s.t1", {})
    await journal.set_thread_id("t1", "resp_1")
    await journal.set_status("t1", "parked")
    bridge = bridge_factory(
        journal=journal,
        checkpoint_state={"checkpoint_id": "ck", "interrupted": True,
                          "interrupts": [PAYLOAD]},
    )
    await bridge._handle_envelope_for_test(
        {"id": 1, "method": "responses/turnStatus", "params": {"turn_id": "t1"}},
        "reply.inbox",
    )
    result = json.loads(bridge.replies[-1])["result"]
    assert result["status"] == "parked"
    assert result["interrupt"] == PAYLOAD


@pytest.mark.asyncio
async def test_turn_status_interrupt_null_when_running(bridge_factory):
    journal = InMemoryTurnJournal()
    await journal.create("t1", "s.t1", {})
    bridge = bridge_factory(journal=journal)
    await bridge._handle_envelope_for_test(
        {"id": 1, "method": "responses/turnStatus", "params": {"turn_id": "t1"}},
        "reply.inbox",
    )
    result = json.loads(bridge.replies[-1])["result"]
    assert result["status"] == "running"
    assert result["interrupt"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["running", "done", "failed"])
async def test_resume_detached_rejects_non_parked(bridge_factory, status):
    journal = InMemoryTurnJournal()
    await journal.create("t1", "s.t1", {})
    if status != "running":
        await journal.set_status("t1", status)
    bridge = bridge_factory(journal=journal)
    await bridge._handle_envelope_for_test(
        {"id": 1, "method": "responses/resumeDetached",
         "params": {"turn_id": "t1", "resume": {"approved": True}}},
        "reply.inbox",
    )
    reply = json.loads(bridge.replies[-1])
    assert reply["error"]["code"] == -32602
    assert "not parked" in reply["error"]["message"]
    assert (await journal.get("t1")).status == status  # unchanged
```

The `bridge_factory` fixture (tests/conftest.py) already stubs the HTTP client; extend it so `checkpoint_state=` configures what `GET /v1/_vystak/checkpoint` returns (it already supports `resume_checkpoint_id` — follow that pattern and have the mock transport serve the full dict).

Also update the two EXISTING resumeDetached tests in `test_nats_bridge_rpcs.py` (`test_resume_detached_flips_parked_to_running`, `test_resume_detached_publishes_no_rewind`) if they create non-parked rows — they already set `parked`, so they should stay green; verify.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/python/vystak-template-langchain-python/tests/test_nats_bridge_approvals.py -v`
Expected: FAIL — no approval event published; no `interrupt` key; non-parked resume currently succeeds.

- [ ] **Step 3: Write minimal implementation**

In `nats_bridge.py`:

1. `_agent_checkpoint_state` already returns the checkpoint-route dict or `None` — it now naturally carries `interrupts` after Task 3; no change needed there.
2. In `_consume_response_stream`'s park branch, publish the event before returning:

```python
if state.get("interrupted"):
    await self._journal.set_status(turn_id, "parked")
    interrupts = state.get("interrupts") or []
    if interrupts:
        await self._publish_seq(
            stream_subject, seq_counter_next,   # the next seq, same accounting as other publishes
            {"type": "vystak.approval.requested", "payload": interrupts[0]},
        )
        # journal last_seq advances so a later resume continues after this event
        await self._journal.set_last_seq(turn_id, seq_counter_next)
    return
```

Use the real seq accounting at that site (the surrounding code holds the last published seq — publish at `last + 1` via the same `publish`/`_publish_seq` mechanism the truncated-tail failure event uses; mirror those lines exactly).

3. `_handle_turn_status`: when the row's status is `parked`, consult `_agent_checkpoint_state(rec.thread_id)` and include the first interrupt:

```python
interrupt_payload = None
if rec is not None and rec.status == "parked":
    state = await self._agent_checkpoint_state(rec.thread_id)
    if state and state.get("interrupts"):
        interrupt_payload = state["interrupts"][0]
await self._publish_result(reply_subject, envelope.get("id"),
                           {"status": rec.status if rec else "unknown",
                            "interrupt": interrupt_payload})
```

(Always include the `interrupt` key — `null` when not parked — so consumers need no key-existence checks.)

4. `_handle_resume_detached`: after the unknown-turn check, add:

```python
if rec.status != "parked":
    await self._publish_error_async(reply_subject, envelope.get("id"),
                                    code=-32602, message="turn is not parked")
    return
```

(Adapt to the real error-publish helper signature at that site.)

- [ ] **Step 4: Run the full template suite**

Run: `uv run pytest packages/python/vystak-template-langchain-python/tests/ -v` and ruff.
Expected: PASS / clean. NOTE: the crash-re-drive path (`redrive_unfinished`) resumes `running` rows via `_stream_from_resume_endpoint` directly, NOT via `_handle_resume_detached` — the guard must not break re-drive tests; confirm `test_nats_bridge_redrive.py` stays green.

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-template-langchain-python/_vystak/runtime/nats_bridge.py \
        packages/python/vystak-template-langchain-python/tests/
git commit -m "feat(template): approval.requested event, turnStatus interrupt payload, parked-only resume"
```

---

### Task 5: Bridge — `responses/resumeThread` RPC (Slack-NATS resume)

**Files:**
- Modify: `packages/python/vystak-template-langchain-python/_vystak/runtime/nats_bridge.py`
- Test: `packages/python/vystak-template-langchain-python/tests/test_nats_bridge_resume_thread.py` (create)

**Interfaces:**
- Consumes: the agent's `POST /v1/_vystak/resume` SSE endpoint (existing).
- Produces: JSON-RPC `responses/resumeThread {"thread_id": str, "resume": <decision>}` → reply `{"text": <final assistant text>}` after the resumed run completes; errors: `-32602 "thread_id required"`; `-32000 "resume failed: <reason>"` on HTTP failure.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_nats_bridge_resume_thread.py
import json

import pytest


@pytest.mark.asyncio
async def test_resume_thread_returns_final_text(bridge_factory):
    bridge = bridge_factory(
        sse_events=[
            {"type": "response.output_text.delta", "delta": "step done. "},
            {"type": "response.output_text.delta", "delta": "All good."},
            {"type": "response.completed", "response": {"id": "resp_1"}},
        ],
    )
    await bridge._handle_envelope_for_test(
        {"id": 9, "method": "responses/resumeThread",
         "params": {"thread_id": "resp_1", "resume": {"approved": True}}},
        "reply.inbox",
    )
    reply = json.loads(bridge.replies[-1])
    assert reply["result"] == {"text": "step done. All good."}
    # the resume POST carried thread_id + resume
    resume_posts = [r for r in bridge.requests if r["path"] == "/v1/_vystak/resume"]
    assert resume_posts and resume_posts[-1]["body"] == {
        "thread_id": "resp_1", "resume": {"approved": True}}


@pytest.mark.asyncio
async def test_resume_thread_requires_thread_id(bridge_factory):
    bridge = bridge_factory()
    await bridge._handle_envelope_for_test(
        {"id": 9, "method": "responses/resumeThread", "params": {}},
        "reply.inbox",
    )
    reply = json.loads(bridge.replies[-1])
    assert reply["error"]["code"] == -32602
```

(`bridge.requests` records method/path/body — added in the durable-execution work; verify the fixture exposes it, extend if the resume path wasn't recorded.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/python/vystak-template-langchain-python/tests/test_nats_bridge_resume_thread.py -v`
Expected: FAIL — unknown method falls through to the A2A forward path.

- [ ] **Step 3: Write minimal implementation**

Add a dispatch branch beside the existing `responses/resumeDetached` match:

```python
if method == "responses/resumeThread":
    await self._handle_resume_thread(envelope, reply_subject)
    return
```

and the handler:

```python
async def _handle_resume_thread(self, envelope: dict, reply_subject: str) -> None:
    """Resume a parked A2A-originated thread and reply with the final text.

    A2A turns have no detached-journal row, so this is thread-keyed. The
    caller (a channel runtime) blocks on the JSON-RPC reply the same way
    it blocks on message/send.
    """
    params = envelope.get("params") or {}
    thread_id = params.get("thread_id")
    if not thread_id:
        await self._publish_error_async(reply_subject, envelope.get("id"),
                                        code=-32602, message="thread_id required")
        return
    try:
        text = await self._resume_and_collect_text(thread_id, params.get("resume"))
    except Exception as e:  # noqa: BLE001 — surface as JSON-RPC error
        await self._publish_error_async(reply_subject, envelope.get("id"),
                                        code=-32000, message=f"resume failed: {e}")
        return
    await self._publish_result(reply_subject, envelope.get("id"), {"text": text})


async def _resume_and_collect_text(self, thread_id: str, resume) -> str:
    """POST /v1/_vystak/resume and concatenate output_text deltas."""
    chunks: list[str] = []
    async with self._http.stream(
        "POST", f"{self._base_url}/v1/_vystak/resume",
        json={"thread_id": thread_id, "resume": resume},
        timeout=self._resume_timeout,
    ) as resp:
        resp.raise_for_status()
        async for line in resp.aiter_lines():
            if not line.startswith("data:"):
                continue
            data = line[len("data:"):].strip()
            if data == "[DONE]":
                break
            event = json.loads(data)
            if event.get("type") == "response.output_text.delta":
                chunks.append(event.get("delta", ""))
    return "".join(chunks)
```

Adapt the HTTP-client attribute names (`self._http`, `self._base_url`, timeout) to what `_stream_from_resume_endpoint` actually uses at that site — reuse the same client/URL derivation, do not build a new client.

- [ ] **Step 4: Run the full template suite**

Run: `uv run pytest packages/python/vystak-template-langchain-python/tests/ -v` and ruff.
Expected: PASS / clean.

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-template-langchain-python/_vystak/runtime/nats_bridge.py \
        packages/python/vystak-template-langchain-python/tests/test_nats_bridge_resume_thread.py
git commit -m "feat(template): responses/resumeThread RPC for thread-keyed approval resumes"
```

---

### Task 6: A2A approval-pending reply (executor + channel-runtime `AgentReply`)

**Files:**
- Modify: `packages/python/vystak-template-langchain-python/_vystak/runtime/a2a_native/executor.py`
- Modify: `packages/python/vystak-channel-runtime/src/vystak_channel_runtime/types.py`
- Modify: `packages/python/vystak-channel-runtime/src/vystak_channel_runtime/agent_client.py`
- Test: `packages/python/vystak-template-langchain-python/tests/test_a2a_executor_approval.py` (create)
- Test: `packages/python/vystak-channel-runtime/tests/test_agent_client_approval.py` (create)

**Interfaces:**
- Consumes: the interrupt payload in graph state (`snapshot.tasks[*].interrupts`).
- Produces: on park, the executor ends the task with an `input_required` status whose message carries ONE text part containing the JSON string `{"kind": "approval_pending", "payload": <interrupt payload>, "thread_id": <task_id>}`; `AgentReply` gains `pending_approval: dict | None = None` (holding `{"payload": ..., "thread_id": ...}`); `_reply_from_jsonrpc` populates it when it sees that marker.

- [ ] **Step 1: Write the failing tests**

Executor side — model the test on the existing executor tests' fake-graph pattern (find them near `tests/` with `LangGraphExecutor`; if none exist, drive the executor with a stub graph + recording `EventQueue`/`TaskUpdater` the way a2a-sdk tests do — the recorded updater calls are the assertion surface):

```python
# tests/test_a2a_executor_approval.py — assertion intent
# Given a graph whose aget_state returns snapshot.next == ("tools",) and one
# task interrupt with value PAYLOAD, after execute():
#   - updater.complete() is NOT called
#   - updater.update_status(...) was called with the input-required state and
#     a message whose single text part json-decodes to
#     {"kind": "approval_pending", "payload": PAYLOAD, "thread_id": <task_id>}
```

Channel-runtime side:

```python
# packages/python/vystak-channel-runtime/tests/test_agent_client_approval.py
import json

from vystak_channel_runtime.agent_client import A2AAgentClient
from vystak_channel_runtime.types import AgentReply

PAYLOAD = {"kind": "tool_approval", "tool": "dangerous",
           "args": {"x": 1}, "skill": "ops"}
MARKER = json.dumps({"kind": "approval_pending", "payload": PAYLOAD,
                     "thread_id": "task-1"})


def _jsonrpc(state, text):
    return {"result": {"status": {"state": state,
                                  "message": {"parts": [{"text": text}]}}}}


def test_input_required_with_marker_sets_pending_approval():
    reply = A2AAgentClient._reply_from_jsonrpc(_jsonrpc("input-required", MARKER))
    assert isinstance(reply, AgentReply)
    assert reply.pending_approval == {"payload": PAYLOAD, "thread_id": "task-1"}
    assert reply.finish_reason == "approval_pending"


def test_normal_completion_has_no_pending_approval():
    reply = A2AAgentClient._reply_from_jsonrpc(_jsonrpc("completed", "hi"))
    assert reply.pending_approval is None
    assert reply.text == "hi"
```

Adapt `_jsonrpc`'s nesting to the REAL shapes `_reply_from_jsonrpc` parses (read it first — it handles `result.status.message.parts[].text`); the state string must match what a2a-sdk serializes for input-required (verify against the installed a2a-sdk's `TaskState` enum values, don't guess).

- [ ] **Step 2: Run tests to verify they fail**

Expected: FAIL — `AgentReply` has no `pending_approval`; executor never emits input-required.

- [ ] **Step 3: Write minimal implementation**

Executor (`executor.py`), after the stream ends and `snapshot = await self._graph.aget_state(config)`:

```python
interrupts = [
    getattr(i, "value", None)
    for task in (getattr(snapshot, "tasks", None) or ())
    for i in (getattr(task, "interrupts", None) or ())
]
if snapshot is not None and snapshot.next and interrupts:
    marker = json.dumps({
        "kind": "approval_pending",
        "payload": interrupts[0],
        "thread_id": context.task_id,
    })
    await updater.update_status(
        TaskState.input_required,          # verify exact enum member name
        message=updater.new_agent_message([Part(text=marker)]),
        final=True,
    )
    return
```

(Verify the a2a-sdk API for "end the task in input-required state" — `update_status(..., final=True)` vs a dedicated helper; the existing `updater.complete()` / `updater.failed()` calls in this file show the idiom. The graph state check replaces nothing — the success path below it is untouched.)

`types.py`:

```python
class AgentReply(BaseModel):
    text: str
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    finish_reason: str | None = None
    raw: dict[str, Any] | None = None
    pending_approval: dict[str, Any] | None = None
```

`agent_client.py` `_reply_from_jsonrpc`: where the status state and message text are extracted, add:

```python
if state_value in ("input-required", "input_required") and text:
    try:
        marker = json.loads(text)
    except (ValueError, TypeError):
        marker = None
    if isinstance(marker, dict) and marker.get("kind") == "approval_pending":
        return AgentReply(
            text="",
            finish_reason="approval_pending",
            pending_approval={"payload": marker.get("payload"),
                              "thread_id": marker.get("thread_id")},
            raw=data,
        )
```

(Adapt variable names to the function's real locals; place the check before the normal text-reply construction.)

- [ ] **Step 4: Run both package suites**

Run: `uv run pytest packages/python/vystak-template-langchain-python/tests/ packages/python/vystak-channel-runtime/tests/ -v` and ruff on both packages.
Expected: PASS / clean.

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-template-langchain-python/_vystak/runtime/a2a_native/executor.py \
        packages/python/vystak-channel-runtime/src/vystak_channel_runtime/ \
        packages/python/vystak-template-langchain-python/tests/test_a2a_executor_approval.py \
        packages/python/vystak-channel-runtime/tests/test_agent_client_approval.py
git commit -m "feat(a2a): approval-pending reply carries interrupt payload to channels"
```

---

### Task 7: Template integration test — real gated tool end-to-end

**Files:**
- Test: `packages/python/vystak-template-langchain-python/tests/test_approvals_end_to_end.py` (create)

**Interfaces:**
- Consumes: Tasks 2-4 (gate + bridge event + guard).
- Produces: proof that a REAL LangGraph run with a REAL wrapped tool parks, publishes the approval event, and completes on approve / continues with the denied string on deny.

- [ ] **Step 1: Write the test**

Model directly on `test_nats_bridge_rpcs.py`'s `test_resume_detached_drives_a_real_parked_graph_to_completion` (real `StateGraph` + `MemorySaver` behind a real ASGI transport, driven through the bridge). Differences: instead of a hand-written interrupting node, build a tiny real react agent (or a `StateGraph` with a tools node) whose tool is produced by `wrap_tools_with_approval` from Task 2, with a recording original tool:

```python
calls = []

@tool
async def restart_service(name: str) -> str:
    """Restart a service."""
    calls.append(name)
    return f"restarted {name}"

(gated,) = wrap_tools_with_approval([restart_service], {"restart_service": "ops"})
```

Two tests:
- **approve**: dispatch a detached turn that invokes the gated tool (drive the graph so the tool node runs — a `StateGraph` that always calls the tool, as in the existing real-graph test, avoids needing an LLM); assert the journal row goes `parked` and `vystak.approval.requested` was published with `tool == "restart_service"`; send `responses/resumeDetached` with `{"approved": True, "decided_by": "qa@example.com", "note": None}`; gather inflight; assert `calls == ["svc"]` (executed exactly once), row `done`, `response.completed` published.
- **deny**: same setup; resume with `{"approved": False, "decided_by": "qa@example.com", "note": "nope"}`; assert `calls == []`, row `done`, and the published output text (or the graph's final state message) contains `"Denied by qa@example.com: nope"`, and `response.failed` was NOT published.

- [ ] **Step 2: Run it**

Run: `uv run pytest packages/python/vystak-template-langchain-python/tests/test_approvals_end_to_end.py -v`
Expected: PASS (iterate until real behavior matches; this test is the feature's keystone — do not weaken assertions to pass).

- [ ] **Step 3: Run the full template suite + ruff, commit**

```bash
git add packages/python/vystak-template-langchain-python/tests/test_approvals_end_to_end.py
git commit -m "test(template): real gated tool parks and resumes end-to-end (approve + deny)"
```

---

### Task 8: Panel channel — approval event through stream, accumulator part, deadline pause

**Files:**
- Modify: `packages/python/vystak-channel-panel/src/vystak_channel_panel/responses_client.py` (`PanelStreamEvent`)
- Modify: `packages/python/vystak-channel-panel/src/vystak_channel_panel/turn_stream.py` (`translate_responses_event`, `browser_frame`, `TurnAccumulator`)
- Modify: `packages/python/vystak-channel-panel/src/vystak_channel_panel/turn_worker.py` (deadline pause)
- Test: `packages/python/vystak-channel-panel/tests/test_approval_stream.py` (create)

**Interfaces:**
- Consumes: the bridge's `vystak.approval.requested` JetStream event (Task 4) and `turn_status` (extended reply is consumed in Task 9).
- Produces: `PanelStreamEvent` type `"approval_requested"` with `approval: dict = {}` field; browser frame `{"type": "approval", "tool_call_id", "tool_name", "input", "turn_id", "seq"}` (turn_id/seq attached by the proxy like other frames); persisted part `{"type": "tool", "state": "approval-requested", "tool_call_id", "tool_name", "input", "output": "", "is_error": False}` for a pending gated call; `run_turn_persister` excludes parked time from the deadline.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_approval_stream.py
from vystak_channel_panel.responses_client import PanelStreamEvent
from vystak_channel_panel.turn_stream import (
    TurnAccumulator, browser_frame, translate_responses_event,
)

PAYLOAD = {"kind": "tool_approval", "tool": "restart_service",
           "args": {"name": "web"}, "skill": "ops"}


def test_translate_recognizes_approval_requested():
    ev = translate_responses_event(
        {"type": "vystak.approval.requested", "payload": PAYLOAD}, {})
    assert ev.type == "approval_requested"
    assert ev.approval == PAYLOAD


def test_browser_frame_for_approval():
    ev = PanelStreamEvent(type="approval_requested", approval=PAYLOAD)
    frame = browser_frame(ev)
    assert frame["type"] == "approval"
    assert frame["tool_name"] == "restart_service"
    assert frame["input"] == {"name": "web"}
    assert frame["tool_call_id"]  # stable non-empty id


def test_accumulator_persists_pending_approval_part():
    acc = TurnAccumulator()
    acc.feed_seq(0, PanelStreamEvent(type="token", text="working "))
    acc.feed_seq(1, PanelStreamEvent(type="approval_requested", approval=PAYLOAD))
    parts = acc.parts()
    assert parts[-1] == {
        "type": "tool", "state": "approval-requested",
        "tool_call_id": parts[-1]["tool_call_id"],
        "tool_name": "restart_service",
        "input": '{"name": "web"}',
        "output": "", "is_error": False,
    }


def test_resolved_approval_replaces_pending_part():
    """After resume, the real tool_call/tool_result pair supersedes the
    pending part (same tool name) so the transcript shows one entry."""
    acc = TurnAccumulator()
    acc.feed_seq(0, PanelStreamEvent(type="approval_requested", approval=PAYLOAD))
    acc.feed_seq(1, PanelStreamEvent(type="tool_call", tool_call_id="c1",
                                     tool_name="restart_service",
                                     arguments='{"name": "web"}'))
    acc.feed_seq(2, PanelStreamEvent(type="tool_result", tool_call_id="c1",
                                     output="restarted web", is_error=False))
    tool_parts = [p for p in acc.parts() if p["type"] == "tool"]
    assert len(tool_parts) == 1
    assert tool_parts[0].get("state") != "approval-requested"
```

Deadline pause (extend the existing `persister_harness` in tests/conftest.py — it already supports `turn_status` and an injectable clock):

```python
# appended to tests/test_turn_worker_idle.py
@pytest.mark.asyncio
async def test_parked_time_does_not_count_toward_deadline(persister_harness):
    """Idle 10 times while parked with the clock far past the deadline —
    the persister keeps waiting because parked time is excluded."""
    h = persister_harness(
        event_batches=[[]] * 10 + [[("done", "resp_1")]],
        turn_status="parked",
        clock=[0.0] + [10_000.0] * 12,   # way past 900s, but parked
    )
    await run_turn_persister(h.rt, "c1", "t1", "s.t1")
    assert h.persisted_rows and h.persisted_rows[0]["response_id"] == "resp_1"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/python/vystak-channel-panel/tests/test_approval_stream.py -v`
Expected: FAIL — unknown event type / no `approval` field.

- [ ] **Step 3: Write minimal implementation**

`responses_client.py`: extend the Literal and add the field:

```python
type: Literal["token", "done", "error", "tool_call", "tool_result", "rewind",
              "approval_requested"]
approval: dict = {}
```

`turn_stream.py`:
- `translate_responses_event`: new branch
  `if event_type == "vystak.approval.requested": return PanelStreamEvent(type="approval_requested", approval=data.get("payload") or {})`.
- `browser_frame`: new case emitting
  `{"type": "approval", "tool_call_id": _approval_call_id(ev), "tool_name": ev.approval.get("tool", ""), "input": ev.approval.get("args", {})}` where `_approval_call_id(ev)` is a deterministic id, e.g. `f"approval:{ev.approval.get('tool','')}"` (one pending approval per park in v1).
- `TurnAccumulator.feed`: on `approval_requested`, flush open text and append the pending part (shape in the test above; `input` is `json.dumps(args)` to match the existing tool-part `input` string convention). On a later `tool_call` whose `tool_name` matches a pending `approval-requested` part, REMOVE the pending part (the resolved pair supersedes it).

`turn_worker.py` — exclude parked time from the deadline. Replace the fixed `started` comparison:

```python
started = rt.monotonic()
parked_since: float | None = None
...
    except TurnStreamIdle:
        now = rt.monotonic()
        active = (now - started) - _parked_total
        if active >= deadline_s:
            errored = True
            break
        try:
            status = await rt.nats_client.turn_status(agent_name, turn_id)
        except Exception:
            continue
        if status == "parked":
            if parked_since is None:
                parked_since = now
            continue
        if parked_since is not None:
            _parked_total += now - parked_since
            parked_since = None
        if status in WAITING_STATUSES:
            continue
        errored = True
        break
```

(Initialize `_parked_total = 0.0` beside `started`; keep the rest of the loop untouched. `turn_status` returning a dict after Task 4 — see Task 9's client change; at THIS task's point `turn_status` still returns a plain string, keep it that way here and let Task 9 adapt.)

- [ ] **Step 4: Run the full panel suite**

Run: `uv run pytest packages/python/vystak-channel-panel/tests/ -v` and `uv run ruff check packages/python/vystak-channel-panel/`
Expected: PASS / clean.

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-channel-panel/src/vystak_channel_panel/ \
        packages/python/vystak-channel-panel/tests/
git commit -m "feat(panel): approval event through stream, pending part, parked deadline pause"
```

---

### Task 9: Panel channel — resume sender, approval endpoint, HTTP-path park handling

**Files:**
- Modify: `packages/python/vystak-channel-panel/src/vystak_channel_panel/nats_client.py`
- Modify: `packages/python/vystak-channel-panel/src/vystak_channel_panel/routes_messages.py`
- Modify: `packages/python/vystak-channel-panel/src/vystak_channel_panel/responses_client.py` (HTTP resume helper)
- Test: `packages/python/vystak-channel-panel/tests/test_approval_endpoint.py` (create)

**Interfaces:**
- Consumes: bridge `responses/resumeDetached` (guarded, Task 4); agent `GET /v1/_vystak/checkpoint` + `POST /v1/_vystak/resume` (HTTP transport).
- Produces: `PanelNatsClient.resume_detached(agent_name: str, turn_id: str, resume: dict) -> None` (raises on JSON-RPC error, message surfaced); route `POST /api/conversations/{conv_id}/approval` body `{"turn_id": str, "approved": bool, "note": str | null}` → `{"ok": true}`; 409 with the bridge's message when already resolved; `decided_by` = acting user's email. HTTP transport: the same route consults the agent checkpoint endpoint and POSTs `/v1/_vystak/resume` (fire-and-forget task that re-runs the message-stream consumption to persist the continuation).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_approval_endpoint.py — drive the FastAPI app the way existing
# routes tests do (find the app/client fixture in tests/ for routes_*).
import pytest


@pytest.mark.asyncio
async def test_approval_resumes_parked_turn_nats(panel_app_harness):
    """POST approval -> resume_detached called with the decision object."""
    h = panel_app_harness(transport="nats")
    conv = await h.create_conversation(agent="durable-agent")
    await h.set_active_turn(conv.id, "t1")

    resp = await h.client.post(
        f"/api/conversations/{conv.id}/approval",
        json={"turn_id": "t1", "approved": True, "note": None},
        headers=h.auth_headers,
    )
    assert resp.status_code == 200
    assert h.nats_client.resume_calls == [
        ("durable-agent", "t1",
         {"approved": True, "decided_by": h.user_email, "note": None}),
    ]


@pytest.mark.asyncio
async def test_approval_conflict_when_already_resolved(panel_app_harness):
    h = panel_app_harness(transport="nats",
                          resume_error="turn is not parked")
    conv = await h.create_conversation(agent="durable-agent")
    await h.set_active_turn(conv.id, "t1")
    resp = await h.client.post(
        f"/api/conversations/{conv.id}/approval",
        json={"turn_id": "t1", "approved": False, "note": "no"},
        headers=h.auth_headers,
    )
    assert resp.status_code == 409
    assert "not parked" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_approval_rejects_mismatched_turn(panel_app_harness):
    h = panel_app_harness(transport="nats")
    conv = await h.create_conversation(agent="durable-agent")
    await h.set_active_turn(conv.id, "other-turn")
    resp = await h.client.post(
        f"/api/conversations/{conv.id}/approval",
        json={"turn_id": "t1", "approved": True, "note": None},
        headers=h.auth_headers,
    )
    assert resp.status_code == 422
```

Build `panel_app_harness` in conftest modeled on however existing routes tests construct the app + store + fake `rt` (there are existing tests for conversations/messages routes — mirror their fixture; `resume_calls` is a recording list on the fake nats client; `resume_error` makes it raise a `RuntimeError` with that message).

Also add a `PanelNatsClient.resume_detached` unit test mirroring the existing `turn_status` tests (fake `nc.request` returning `{"result": {"turn_id": "t1"}}` → returns None; returning `{"error": {"code": -32602, "message": "turn is not parked"}}` → raises `RuntimeError("turn is not parked")`).

- [ ] **Step 2: Run tests to verify they fail**

Expected: FAIL — no route, no `resume_detached`.

- [ ] **Step 3: Write minimal implementation**

`nats_client.py` — mirror `turn_status`'s envelope pattern exactly:

```python
async def resume_detached(self, agent_name: str, turn_id: str, resume: dict) -> None:
    nc = await self._transport.nats_connection()
    subject = self._transport.resolve_address(agent_name)
    payload = json.dumps({
        "jsonrpc": "2.0", "id": str(uuid.uuid4()),
        "method": "responses/resumeDetached",
        "params": {"turn_id": turn_id, "resume": resume},
    }).encode()
    reply = await nc.request(subject, payload, timeout=self._status_timeout)
    body = json.loads(reply.data)
    if body.get("error"):
        raise RuntimeError(body["error"].get("message", "resume failed"))
```

`routes_messages.py` (or a new `routes_approvals.py` if the messages router is crowded — match the file-size convention; register in `routes_registry.py` either way):

```python
class ApprovalIn(BaseModel):
    turn_id: str
    approved: bool
    note: str | None = None


@router.post("/conversations/{conv_id}/approval")
async def post_approval(
    conv_id: str,
    body: ApprovalIn,
    user: PanelUser = Depends(current_user),
) -> dict:
    conv = await rt.panel_store.get_conversation(conv_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="unknown conversation")
    await require_project_access(rt, conv.project_id, user)
    if conv.active_turn_id != body.turn_id:
        raise HTTPException(status_code=422, detail="turn is not this conversation's active turn")
    decision = {"approved": body.approved, "decided_by": user.email,
                "note": body.note}
    route = rt.routes.get(conv.agent_name)
    if _is_nats(rt):
        try:
            await rt.nats_client.resume_detached(conv.agent_name, body.turn_id, decision)
        except RuntimeError as e:
            raise HTTPException(status_code=409, detail=str(e))
    else:
        base_url = route.url  # adapt to the real route-record shape
        await _resume_http(rt, conv_id, base_url, decision)
    return {"ok": True}
```

(`_is_nats(rt)` — reuse however `post_message` decides NATS vs HTTP; adapt the attribute names to that code.)

HTTP path `_resume_http`: add to `responses_client.py`:

```python
async def resume_stream(self, base_url: str, thread_id: str, resume: dict):
    """POST /v1/_vystak/resume and yield PanelStreamEvents (same parsing
    as stream_message)."""
```

— implement by factoring `stream_message`'s SSE-consumption loop into a shared private helper both methods call, with `resume_stream` POSTing `{base_url}/v1/_vystak/resume` with `{"thread_id": thread_id, "resume": resume}`. In the route, `_resume_http` resolves the conversation's `last_response_id` as the thread id, spawns a background task that consumes `resume_stream` through a fresh `TurnAccumulator` and persists the assistant continuation via `rt.panel_store.add_message` (mirror `post_message`'s `persist()` closure), and clears `active_turn_id`. Also in `post_message`'s HTTP branch: when the stream ends with no terminal event, consult `GET {base_url}/v1/_vystak/checkpoint?thread_id=...`; if `interrupted`, persist the pending approval part (feed a synthetic `approval_requested` event into the accumulator from `interrupts[0]`) and emit the `approval` browser frame instead of the synthetic `"done"`.

- [ ] **Step 4: Run the full panel suite**

Run: `uv run pytest packages/python/vystak-channel-panel/tests/ -v` and ruff.
Expected: PASS / clean.

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-channel-panel/src/vystak_channel_panel/ \
        packages/python/vystak-channel-panel/tests/
git commit -m "feat(panel): approval endpoint + resume senders for both transports"
```

---

### Task 10: Panel TS — approval card UI + Next API route

**Files:**
- Modify: `packages/typescript/vystak-panel/lib/stream.ts`
- Modify: `packages/typescript/vystak-panel/lib/messageParts.ts`
- Modify: `packages/typescript/vystak-panel/lib/types.ts`
- Modify: `packages/typescript/vystak-panel/lib/panel.ts`
- Modify: `packages/typescript/vystak-panel/components/chat.tsx`
- Create: `packages/typescript/vystak-panel/app/api/conversations/[id]/approval/route.ts`
- Test: `packages/typescript/vystak-panel/tests/stream.test.ts` (extend), `tests/messageParts.test.ts` (extend)

**Interfaces:**
- Consumes: browser frame `{"type": "approval", tool_call_id, tool_name, input, turn_id, seq}` (Task 8) and the panel endpoint `POST /api/conversations/{conv_id}/approval` (Task 9).
- Produces: on an `approval` frame, `stream.ts` emits `tool-input-start` + `tool-input-available` (dynamic) for the pending call AND a non-transient `{type: 'data-approval', data: {toolCallId, turnId}}` chunk; `chat.tsx` renders Approve/Deny buttons + note input on a dynamic-tool part whose id has a matching unresolved `data-approval` marker; clicking POSTs the Next route, which proxies to the panel endpoint with the session user.

- [ ] **Step 1: Write the failing tests**

```ts
// tests/stream.test.ts — extend with:
it('emits tool input and a data-approval marker on approval frame', async () => {
  const chunks = await collect(panelStreamToUIChunks(frames([
    { type: 'approval', tool_call_id: 'approval:restart_service',
      tool_name: 'restart_service', input: { name: 'web' },
      turn_id: 't1', seq: 5 },
  ])));
  const types = chunks.map(c => c.type);
  expect(types).toContain('tool-input-start');
  expect(types).toContain('tool-input-available');
  const marker = chunks.find(c => c.type === 'data-approval');
  expect(marker.data).toEqual({ toolCallId: 'approval:restart_service', turnId: 't1' });
});

it('tool result for the same call resolves the approval (no dangling marker semantics change)', async () => {
  // approval frame then real tool_call/tool_result with the SAME tool name:
  // the UI keys resolution off the tool part states; assert both the pending
  // input chunks and the later output chunk appear with their own ids.
  const chunks = await collect(panelStreamToUIChunks(frames([
    { type: 'approval', tool_call_id: 'approval:restart_service',
      tool_name: 'restart_service', input: { name: 'web' }, turn_id: 't1', seq: 5 },
    { type: 'tool_call', tool_call_id: 'c1', tool_name: 'restart_service',
      arguments: '{"name":"web"}', turn_id: 't1', seq: 6 },
    { type: 'tool_result', tool_call_id: 'c1', output: 'restarted web',
      is_error: false, turn_id: 't1', seq: 7 },
  ])));
  expect(chunks.some(c => c.type === 'tool-output-available')).toBe(true);
});
```

```ts
// tests/messageParts.test.ts — extend with:
it('maps a persisted approval-requested part to an awaiting-approval tool part', () => {
  const parts = mapPersistedParts([
    { type: 'tool', state: 'approval-requested', tool_call_id: 'a1',
      tool_name: 'restart_service', input: '{"name":"web"}',
      output: '', is_error: false },
  ], '');
  expect(parts[0].type).toBe('dynamic-tool');
  expect(parts[0].state).toBe('approval-requested');
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pnpm --filter vystak-panel test`
Expected: FAIL — unknown frame type / unknown persisted state.

- [ ] **Step 3: Write minimal implementation**

`lib/stream.ts` — new branch in the frame switch (before the fallthrough):

```ts
} else if (payload.type === 'approval') {
  closeTextIfOpen();
  const toolCallId = outgoingToolCallId(payload.tool_call_id ?? '');
  controller.enqueue({ type: 'tool-input-start', toolCallId,
                       toolName: payload.tool_name ?? '', dynamic: true });
  controller.enqueue({ type: 'tool-input-available', toolCallId,
                       toolName: payload.tool_name ?? '',
                       input: payload.input ?? {}, dynamic: true });
  controller.enqueue({ type: 'data-approval',
                       data: { toolCallId, turnId: payload.turn_id ?? '' } });
}
```

`lib/types.ts`: add `state?: string` to `ToolMessagePart`. `lib/messageParts.ts`: `mapPersistedParts` maps `state === 'approval-requested'` to a dynamic-tool part with `state: 'approval-requested'` and no output (local type augmentation for the AI SDK v5 union: cast via the same `// @ts-expect-error` convention the vendored `tool.tsx` already uses — do NOT upgrade the `ai` package in this task).

`lib/panel.ts`:

```ts
export const postApproval = (
  email: string, convId: string,
  body: { turn_id: string; approved: boolean; note: string | null },
) =>
  panelFetch(email, `/api/conversations/${convId}/approval`, {
    method: 'POST', body: JSON.stringify(body),
  });
```

`app/api/conversations/[id]/approval/route.ts` — mirror `app/api/chat/route.ts`'s auth shape:

```ts
import { auth } from '@/auth';
import { postApproval } from '@/lib/panel';

export async function POST(req: Request, { params }: { params: Promise<{ id: string }> }) {
  const session = await auth();
  const email = session?.user?.email?.toLowerCase();
  if (!email) return new Response('Unauthorized', { status: 401 });
  const { id } = await params;
  const body = await req.json();
  const upstream = await postApproval(email, id, body);
  return new Response(await upstream.text(), { status: upstream.status });
}
```

(Adapt import paths/`params` handling to the repo's Next version conventions — copy from the existing route file.)

`components/chat.tsx`: when rendering a `dynamic-tool` part, look for an unresolved approval: the part's `state === 'approval-requested'` (persisted path) OR a `data-approval` part exists with this `toolCallId` and the tool part has no output yet (live path). In that case render inside `<ToolContent>`:

```tsx
<div className="flex items-center gap-2 p-3">
  <Input placeholder="Note (optional)" value={note} onChange={...} />
  <Button size="sm" onClick={() => decide(true)}>Approve</Button>
  <Button size="sm" variant="destructive" onClick={() => decide(false)}>Deny</Button>
</div>
```

with `decide(approved)` POSTing `/api/conversations/${conversationId}/approval` with `{turn_id, approved, note}` (turn_id from the `data-approval` marker or, on the persisted path, from the conversation's active turn passed down as a prop — follow how `chat.tsx` already receives conversation metadata), disabling the buttons while in flight, and showing the error text on a non-200 (toast or inline). Extract the button block into a small component in `components/` if `chat.tsx` grows past ~40 new lines.

- [ ] **Step 4: Run tests + typecheck**

Run: `pnpm --filter vystak-panel test && pnpm --filter vystak-panel run typecheck && just typecheck-typescript`
Expected: PASS / clean.

- [ ] **Step 5: Commit**

```bash
git add packages/typescript/vystak-panel/
git commit -m "feat(panel-ui): approval card with approve/deny driving the panel endpoint"
```

---

### Task 11: Slack — approval-pending reply → Block Kit buttons → resume

**Files:**
- Modify: `packages/python/vystak-channel-slack/src/vystak_channel_slack/runtime.py`
- Modify: `packages/python/vystak-channel-runtime/src/vystak_channel_runtime/agent_client.py` (resume senders)
- Test: `packages/python/vystak-channel-slack/tests/test_approvals.py` (create)
- Test: `packages/python/vystak-channel-runtime/tests/test_agent_client_resume.py` (create)

**Interfaces:**
- Consumes: `AgentReply.pending_approval` (Task 6); agent `POST /v1/_vystak/resume` (HTTP) / bridge `responses/resumeThread` (NATS, Task 5).
- Produces: `A2AAgentClient.resume_turn(thread_id: str, resume: dict) -> str` (final text; POSTs `{base}/v1/_vystak/resume`, concatenates `response.output_text.delta`); `NatsAgentClient.resume_turn(thread_id, resume) -> str` (sends `responses/resumeThread`, returns `result["text"]`); Slack runtime posts a Block Kit approval message on `pending_approval`, registers `@app.action("vystak_approve")` / `@app.action("vystak_deny")`, and on action: edits the message to "Approved/Denied by @user", calls `resume_turn`, posts the final text in-thread.

- [ ] **Step 1: Write the failing tests**

Client senders (`test_agent_client_resume.py`): for `A2AAgentClient.resume_turn`, use `httpx.MockTransport` serving an SSE body of two deltas + `response.completed` + `[DONE]`, assert the returned string is the concatenation and the POST body was `{"thread_id": "t1", "resume": {...}}`. For `NatsAgentClient.resume_turn`, fake the `nc.request` (as existing NatsAgentClient tests do) returning `{"result": {"text": "done"}}`, assert `"done"` and the envelope method was `responses/resumeThread`; an `{"error": {...}}` reply raises `RuntimeError` with the message.

Slack runtime (`test_approvals.py`) — model on existing slack runtime tests' stubbing (fake `say`, fake app client):
- `test_pending_approval_posts_block_kit`: build the runtime with a fake agent client whose `send_turn` returns `AgentReply(text="", finish_reason="approval_pending", pending_approval={"payload": PAYLOAD, "thread_id": "task-1"})`; drive one inbound message; assert `say` (or `chat_postMessage`) was called with `blocks` containing two buttons whose `action_id`s are `vystak_approve`/`vystak_deny` and whose `value` json-decodes to `{"thread_id": "task-1", "tool": "restart_service"}`, and the text mentions the tool name + args.
- `test_approve_action_resumes_and_posts_reply`: invoke the registered action handler directly with a fake `ack`, `body` (containing `user.username`/`user.id`, the button `value`, `channel.id`, `message.ts`), and a fake client; agent client's `resume_turn` returns `"All done."`; assert `ack` awaited, `resume_turn` called with `("task-1", {"approved": True, "decided_by": "@<username>", "note": None})`, `chat_update` called replacing the buttons with text containing "Approved by", and the final reply posted in-thread.
- `test_deny_action_sends_denied_decision`: same with `vystak_deny` → `{"approved": False, ...}` and "Denied by".
- `test_second_click_reports_already_resolved`: `resume_turn` raises `RuntimeError("turn is not parked")` → handler posts an ephemeral (`chat_postEphemeral`) containing "already resolved" and does NOT post a reply.

- [ ] **Step 2: Run tests to verify they fail**

Expected: FAIL — no `resume_turn`, no block kit, no action handlers.

- [ ] **Step 3: Write minimal implementation**

`agent_client.py`:

```python
# on A2AAgentClient
async def resume_turn(self, thread_id: str, resume: dict) -> str:
    chunks: list[str] = []
    async with self._client.stream(          # reuse the class's httpx client + base URL idiom
        "POST", f"{self._base_url}/v1/_vystak/resume",
        json={"thread_id": thread_id, "resume": resume},
    ) as resp:
        resp.raise_for_status()
        async for line in resp.aiter_lines():
            if not line.startswith("data:"):
                continue
            data = line[len("data:"):].strip()
            if data == "[DONE]":
                break
            event = json.loads(data)
            if event.get("type") == "response.output_text.delta":
                chunks.append(event.get("delta", ""))
    return "".join(chunks)

# on NatsAgentClient
async def resume_turn(self, thread_id: str, resume: dict) -> str:
    payload = json.dumps({
        "jsonrpc": "2.0", "id": str(uuid.uuid4()),
        "method": "responses/resumeThread",
        "params": {"thread_id": thread_id, "resume": resume},
    }).encode()
    reply = await self._nc_request(payload)   # reuse send_turn's request idiom/subject
    body = json.loads(reply.data)
    if body.get("error"):
        raise RuntimeError(body["error"].get("message", "resume failed"))
    return (body.get("result") or {}).get("text", "")
```

(Adapt attribute names — base URL, httpx client, NATS request path — to the class's real internals; `send_turn` shows both.)

`runtime.py` — in the reply-posting path (`post_reply` caller or wherever the `AgentReply` lands), branch first:

```python
if reply.pending_approval:
    await self._post_approval_request(event, reply.pending_approval)
    return
```

with:

```python
async def _post_approval_request(self, event, pending: dict) -> None:
    payload = pending.get("payload") or {}
    value = json.dumps({"thread_id": pending.get("thread_id"),
                        "tool": payload.get("tool", "")})
    blocks = [
        {"type": "section", "text": {"type": "mrkdwn", "text":
            f":lock: *Approval required* — `{payload.get('tool', '?')}`\n"
            f"```{json.dumps(payload.get('args', {}), indent=2)}```"}},
        {"type": "actions", "elements": [
            {"type": "button", "action_id": "vystak_approve",
             "text": {"type": "plain_text", "text": "Approve"},
             "style": "primary", "value": value},
            {"type": "button", "action_id": "vystak_deny",
             "text": {"type": "plain_text", "text": "Deny"},
             "style": "danger", "value": value},
        ]},
    ]
    # post via the same say/thread_ts mechanics post_reply uses:
    ...
```

In `start()`, beside the event handlers:

```python
@self._app.action("vystak_approve")
async def _approve(ack, body, client):
    await ack()
    await self._handle_approval_action(body, client, approved=True)

@self._app.action("vystak_deny")
async def _deny(ack, body, client):
    await ack()
    await self._handle_approval_action(body, client, approved=False)
```

`_handle_approval_action(body, client, approved)`: parse `value` from `body["actions"][0]["value"]`; `decided_by = "@" + (body["user"].get("username") or body["user"]["id"])`; decision object per the global contract with `note=None` (Slack note input is v2); call `self._agent_client(...).resume_turn(thread_id, decision)` (resolve the agent client the same way the message path does); on success `client.chat_update(channel=..., ts=body["message"]["ts"], text=f"{'Approved' if approved else 'Denied'} by {decided_by}", blocks=[])` then post the final text in-thread via the same mechanics as `post_reply`; on `RuntimeError` post `chat_postEphemeral(channel=..., user=body["user"]["id"], text=f"Already resolved: {e}")`.

- [ ] **Step 4: Run both package suites**

Run: `uv run pytest packages/python/vystak-channel-slack/tests/ packages/python/vystak-channel-runtime/tests/ -v` (non-release tests only) and ruff on both.
Expected: PASS / clean. No new REQUIREMENTS entries needed (slack-bolt already bundled).

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-channel-slack/ packages/python/vystak-channel-runtime/
git commit -m "feat(slack): approval buttons via Block Kit driving thread resume"
```

---

### Task 12: Example — `examples/docker-approvals`

**Files:**
- Create: `examples/docker-approvals/vystak.py`, `tools/read_status.py`, `tools/restart_service.py`, `README.md`, `.env.example`

- [ ] **Step 1: Build the example**

Base on `examples/docker-panel-durable` (copy, adapt; NEVER commit `_vystak/`, `.vystak/`, `.env`, lockfiles). Agent `approvals-agent`, NATS transport, panel channel, and:

```python
ops = ast.Skill(
    name="ops",
    tools=["read_status", "restart_service"],
    needs_approval=["restart_service"],
)
```

`tools/read_status.py`: returns a canned status string. `tools/restart_service.py`:

```python
async def restart_service(name: str) -> str:
    """Restart the named service. Destructive: requires approval."""
    return f"service {name} restarted"
```

Instructions: "When asked to fix the service, first call read_status, then call restart_service for the failing service, then summarize." `.env.example`: `ANTHROPIC_API_KEY=sk-ant-your-key-here` only.

- [ ] **Step 2: README walkthrough**

Document: init (`vystak init --framework langchain-python --force .` + the recovery recipe the durable example's README established), apply, open the panel, send "the web service looks broken — fix it", watch `read_status` run ungated, then the **Awaiting Approval card** appear for `restart_service` with the model-chosen args; click Approve → tool runs, turn completes; repeat in a new conversation clicking Deny → agent reports it couldn't proceed ("Denied by …" visible in its reasoning). Note the park is durable: closing the browser or restarting the agent container leaves the approval waiting. Placeholders only.

- [ ] **Step 3: Verify plan**

Run: `uv sync --reinstall-package vystak-cli`, then from the example dir `uv run vystak init --framework langchain-python --force .`, remove the stray scaffolded `vystak.yaml`, `uv run vystak plan` with a sentinel `.env`.
Expected: clean plan (agent + panel + NATS + data volume). A `needs_approval` entry naming a nonexistent tool must fail the plan — verify once by temporarily editing, then revert.

- [ ] **Step 4: Commit**

```bash
git add examples/docker-approvals
git commit -m "example: docker-approvals exercising human-in-the-loop tool gates"
```

---

### Task 13: Release cells — `test_approvals.py`

**Files:**
- Create: `packages/python/vystak-provider-docker/tests/release/test_approvals.py`

**Interfaces:**
- Consumes: `project`, `docker_required`, `durable_volume_clean`, `panel_durable_clean` fixtures (conftest); the deployed example shape from Task 12.

- [ ] **Step 1: Write the live panel approval cell**

Marked `release_live_chat` (real key; auto-skips on sentinels — reuse the `live_credentials` fixture pattern from `test_durable_turns.py`, including passing `ANTHROPIC_API_URL` through to the agent). Deploy a Task-12-shaped project (inline `vystak.py` with the gated tool writing a `/data/restart_invocations.log` side-effect line per execution, mirroring `_SLOW_STEP_LIVE`'s pattern). Drive via the panel API (`_bootstrap_panel_conversation` / `_dispatch_turn_and_get_id` patterns from `test_durable_turns.py`): send the fix-it prompt; poll `responses/turnStatus`-backed panel state until the journal row is `parked` (read `/data/turns.db` via `docker exec python`, as `_journal_rows` does); assert the persisted conversation shows the approval part; POST the approval endpoint (`/api/conversations/{conv_id}/approval`, service token + `X-Panel-User`) with approve; assert the turn concludes, exactly one line in the side-effect log, `active_turn_id` cleared, and the final assistant row exists. Second test: same flow with deny → zero side-effect lines, final row contains "Denied by".

- [ ] **Step 2: Write the Slack cell**

Marked `release_slack` (needs `SLACK_BOT_TOKEN`/`SLACK_APP_TOKEN`; skips without). Deploy with a slack channel + gated tool; this cell can only assert deploy-side mechanics without a live Slack workspace interaction — keep it to: deploy succeeds, agent healthy, and the runtime's action handlers are registered (assert via container logs or skip if unverifiable; if nothing meaningful can be asserted without a human Slack click, write the cell as the deploy smoke + a documented manual walkthrough in the example README and note that in the cell docstring).

- [ ] **Step 3: Run the live cell**

Run: `set -a; source examples/docker-panel/.env; set +a; uv run pytest packages/python/vystak-provider-docker/tests/release/test_approvals.py -v -m release_live_chat`
Expected: PASS (both approve and deny tests). Also verify sentinel auto-skip: run without the env and expect SKIP.

- [ ] **Step 4: Commit**

```bash
git add packages/python/vystak-provider-docker/tests/release/test_approvals.py
git commit -m "test(release): live human-in-the-loop approval cells (approve + deny)"
```

---

### Task 14: Documentation + final verification

**Files:**
- Create: `docs/approvals.md`
- Create: `website/docs/concepts/approvals.md` (+ sidebar registration)
- Modify: `CLAUDE.md` (examples list + release-cell map)

- [ ] **Step 1: Write `docs/approvals.md`**

Cover (accuracy over completeness — match the implementation): the `needs_approval` field + validation; the decision/payload/denied-string contracts (verbatim from Global Constraints); park-indefinitely semantics + the panel deadline exclusion; first-decision-wins; both surfaces (panel card walkthrough, Slack buttons) and both transports; the PyPI-schema caveat (an agent image whose installed `vystak` predates the field still works — the template reads the bundled agent.json — but `vystak plan` validation requires the local dev environment's vystak to know the field); durability (restart while parked keeps the approval); v1 non-goals (MCP tools, approver lists, TTLs, Discord).

- [ ] **Step 2: Website concept page + CLAUDE.md**

Concept page mirrors `website/docs/concepts/durable-execution.md`'s structure; register in `website/sidebars.js` beside it. CLAUDE.md: add `docker-approvals` to the examples list and `test_approvals.py` to the Docker release-cell list (bump the file count).

- [ ] **Step 3: Build + gates**

Run: `just docs-build` (clean) and `just ci-live` (all four gates green).

- [ ] **Step 4: Commit**

```bash
git add docs/approvals.md website/ CLAUDE.md
git commit -m "docs: human-in-the-loop tool approvals"
```

---

## Final verification

- [ ] `just ci-live` green at HEAD.
- [ ] `uv run pytest packages/python/vystak-provider-docker/tests/release/ -v -m "release_smoke or release_integration"` — no regressions (17 passed / skips as before).
- [ ] Live approval cells green with real key (Task 13 Step 3).
- [ ] Browser walkthrough of `examples/docker-approvals` (approve AND deny paths) — the approval card renders, buttons work, denied turn completes with the denied text visible.
- [ ] No edits under `packages/python/vystak-cli/src/vystak_cli/templates/`; credential scan of the full diff before push.
