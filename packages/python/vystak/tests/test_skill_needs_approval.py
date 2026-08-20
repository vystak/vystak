import pytest
import yaml
from vystak.hash.tree import hash_agent
from vystak.schema import Agent, Skill
from vystak.schema.loader import load_agent
from vystak.schema.model import Model
from vystak.schema.multi_loader import load_multi_yaml
from vystak.schema.provider import Provider
from vystak.schema.skill import validate_needs_approval


def make_agent(**overrides):
    anthropic = Provider(name="anthropic", type="anthropic")
    model = Model(name="claude", provider=anthropic, model_name="claude-sonnet-4-20250514")
    defaults = {"name": "bot", "framework": "langchain-python", "default_model": model}
    defaults.update(overrides)
    return Agent(**defaults)


def test_field_defaults_empty():
    s = Skill(name="ops", tools=["restart_service"])
    assert s.needs_approval == []


def test_field_accepts_subset_of_tools():
    s = Skill(
        name="ops",
        tools=["restart_service", "read_logs"],
        needs_approval=["restart_service"],
    )
    assert s.needs_approval == ["restart_service"]


def test_validate_rejects_unknown_tool():
    s = Skill(name="ops", tools=["read_logs"], needs_approval=["restart_service"])
    with pytest.raises(ValueError, match="ops.*restart_service"):
        validate_needs_approval(s)


def test_validate_accepts_valid_skill():
    s = Skill(name="ops", tools=["restart_service"], needs_approval=["restart_service"])
    validate_needs_approval(s)  # no raise


def test_hash_changes_with_needs_approval():
    base = make_agent(skills=[Skill(name="ops", tools=["t"])])
    gated = make_agent(skills=[Skill(name="ops", tools=["t"], needs_approval=["t"])])
    tree1 = hash_agent(base)
    tree2 = hash_agent(gated)
    assert tree1.root != tree2.root


def test_load_agent_rejects_unknown_approval_tool(tmp_path):
    data = {
        "name": "test-bot",
        "framework": "langchain-python",
        "default_model": {
            "name": "claude",
            "provider": {"name": "anthropic", "type": "anthropic"},
            "model_name": "claude-sonnet-4-20250514",
        },
        "skills": [
            {
                "name": "ops",
                "tools": ["read_logs"],
                "needs_approval": ["restart_service"],
            }
        ],
    }
    path = tmp_path / "agent.yaml"
    path.write_text(yaml.dump(data))
    with pytest.raises(ValueError, match="ops.*restart_service"):
        load_agent(path)


def test_load_multi_yaml_rejects_unknown_approval_tool():
    data = {
        "providers": {"anthropic": {"type": "anthropic"}},
        "models": {
            "claude": {"provider": "anthropic", "model_name": "claude-sonnet-4-20250514"},
        },
        "agents": [
            {
                "name": "bot-a",
                "framework": "langchain-python",
                "default_model": "claude",
                "skills": [
                    {
                        "name": "ops",
                        "tools": ["read_logs"],
                        "needs_approval": ["restart_service"],
                    }
                ],
            },
        ],
    }
    with pytest.raises(ValueError, match="ops.*restart_service"):
        load_multi_yaml(data)
