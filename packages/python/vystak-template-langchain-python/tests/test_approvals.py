import json

import pytest
from _vystak.runtime.approvals import load_approval_map, wrap_tools_with_approval
from langchain_core.tools import tool


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


async def _raw_restart(name: str) -> str:
    """Restart a service."""
    return f"restarted {name}"


def test_raw_callable_is_matched_and_coerced():
    """`load_user_tools` returns bare functions (no `.name`, only
    `__name__`) -- the common case for every `Skill.tools` entry, not an
    edge case. Regression test for a real bug caught live: `_dispatch_name`
    must fall back to `__name__` so these get matched against
    `approval_map` and coerced into a real tool before wrapping."""
    (wrapped,) = wrap_tools_with_approval([_raw_restart], {"_raw_restart": "ops"})
    assert wrapped is not _raw_restart
    assert wrapped.name == "_raw_restart"
    assert wrapped.args_schema is not None


@pytest.mark.asyncio
async def test_raw_callable_approved_decision_executes_original(monkeypatch):
    monkeypatch.setattr(
        "_vystak.runtime.approvals.interrupt",
        lambda payload: {"approved": True, "decided_by": "qa@example.com", "note": None},
    )
    (wrapped,) = wrap_tools_with_approval([_raw_restart], {"_raw_restart": "ops"})
    result = await wrapped.ainvoke({"name": "web"})
    assert result == "restarted web"


def test_raw_callable_ungated_passes_through_unchanged():
    out = wrap_tools_with_approval([_raw_restart], {"other": "ops"})
    assert out == [_raw_restart]


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
