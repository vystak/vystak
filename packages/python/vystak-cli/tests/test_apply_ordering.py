"""Deploy ordering: subagents must deploy before the agents that call them."""

from vystak.schema.agent import Agent
from vystak.schema.model import Model
from vystak.schema.provider import Provider
from vystak_cli.commands.apply import _order_agents_for_deploy


def _model():
    return Model(
        name="m",
        provider=Provider(name="anthropic", type="anthropic"),
        model_name="claude-sonnet-4-6",
    )


def _agent(name, subagents=()):
    return Agent(
        name=name,
        framework="langchain-python",
        default_model=_model(),
        subagents=list(subagents),
    )


def test_child_deploys_before_parent():
    child = _agent("child")
    parent = _agent("parent", subagents=[child])
    ordered = _order_agents_for_deploy([parent, child])
    assert [a.name for a in ordered] == ["child", "parent"]


def test_chain_orders_deepest_first():
    leaf = _agent("leaf")
    mid = _agent("mid", subagents=[leaf])
    top = _agent("top", subagents=[mid])
    ordered = _order_agents_for_deploy([top, mid, leaf])
    assert [a.name for a in ordered] == ["leaf", "mid", "top"]


def test_independent_agents_keep_declaration_order():
    a, b, c = _agent("a"), _agent("b"), _agent("c")
    ordered = _order_agents_for_deploy([a, b, c])
    assert [x.name for x in ordered] == ["a", "b", "c"]


def test_subagent_not_in_batch_is_ignored():
    ghost = _agent("ghost")
    parent = _agent("parent", subagents=[ghost])
    ordered = _order_agents_for_deploy([parent])
    assert [a.name for a in ordered] == ["parent"]


def test_cycle_falls_back_without_hanging():
    a = _agent("a")
    b = _agent("b", subagents=[a])
    # Force a cycle post-validation (schema only rejects self-reference).
    object.__setattr__(a, "subagents", [b])
    ordered = _order_agents_for_deploy([a, b])
    assert sorted(x.name for x in ordered) == ["a", "b"]
