import pytest

from agentstack.schema.skill import Skill, SkillRequirements


class TestSkillRequirements:
    def test_defaults(self):
        req = SkillRequirements()
        assert req.session_store is False
        assert req.workspace is None
        assert req.mcp_servers is None

    def test_with_values(self):
        req = SkillRequirements(session_store=True, workspace={"filesystem": True, "terminal": True}, mcp_servers=["github", "filesystem"])
        assert req.session_store is True
        assert len(req.mcp_servers) == 2


class TestSkill:
    def test_minimal(self):
        skill = Skill(name="greeting")
        assert skill.tools == []
        assert skill.prompt is None
        assert skill.version == "0.1.0"

    def test_full(self):
        skill = Skill(
            name="refund-handling",
            tools=["lookup_order", "check_policy", "process_refund"],
            prompt="When handling refunds, always verify the order exists first.",
            guardrails={"max_amount": 500, "require_reason": True},
            requires=SkillRequirements(session_store=True, mcp_servers=["stripe"]),
            version="1.0.0",
            dependencies=["order-tracking"],
        )
        assert len(skill.tools) == 3
        assert skill.requires.session_store is True
        assert skill.dependencies == ["order-tracking"]

    def test_serialization_roundtrip(self):
        skill = Skill(name="test", tools=["tool_a", "tool_b"], prompt="Do the thing.", requires=SkillRequirements(session_store=True))
        data = skill.model_dump()
        restored = Skill.model_validate(data)
        assert restored == skill
