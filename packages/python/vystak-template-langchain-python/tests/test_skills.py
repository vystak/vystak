"""Folder-skill runtime — prompt section + load_skill / read_skill_file."""

import os
from pathlib import Path

import pytest
from _vystak.runtime.skills import build_skill_tools, skills_prompt_section
from langchain_core.messages import HumanMessage
from vystak.schema.skill import Skill


def _agent(skills):
    class _A:
        name = "support"

    a = _A()
    a.skills = skills
    return a


def _folder_skill(name="research", path=None, description="Deep-research workflow."):
    return Skill(
        name=name,
        description=description,
        path=path or f"skills/{name}",
        content_digest="abc",
    )


def _write_skill_folder(root, name="research", body="Research like this.\n"):
    folder = root / "skills" / name
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: Deep-research workflow.\n---\n{body}"
    )
    return folder


class TestSkillsPromptSection:
    def test_empty_without_skills(self):
        assert skills_prompt_section(_agent([])) == ""

    def test_lists_described_skills_with_preamble(self):
        section = skills_prompt_section(_agent([_folder_skill()]))
        assert "## Skills" in section
        assert "load_skill" in section
        assert "- research: Deep-research workflow." in section

    def test_inline_skill_without_description_not_listed(self):
        section = skills_prompt_section(_agent([Skill(name="ops", tools=["lookup_order"])]))
        assert section == ""

    def test_inline_prompt_appended(self):
        section = skills_prompt_section(
            _agent([Skill(name="ops", tools=["t"], prompt="Always verify orders.")])
        )
        assert "Always verify orders." in section

    def test_no_preamble_without_folder_skills(self):
        inline = Skill(name="ops", tools=["t"], description="Order handling.")
        section = skills_prompt_section(_agent([inline]))
        assert "- ops: Order handling." in section
        assert "load_skill" not in section


class TestBuildSkillTools:
    def test_no_folder_skills_no_tools(self):
        agent = _agent([Skill(name="ops", tools=["t"])])
        assert build_skill_tools(agent, Path(".")) == []

    def test_load_skill_returns_body_and_resources(self, tmp_path):
        folder = _write_skill_folder(tmp_path)
        (folder / "sources.md").write_text("List of sources.\n")
        tools = build_skill_tools(_agent([_folder_skill()]), tmp_path)
        assert sorted(t.name for t in tools) == ["load_skill", "read_skill_file"]
        load_skill = next(t for t in tools if t.name == "load_skill")
        out = load_skill.invoke({"name": "research"})
        assert "Research like this." in out
        assert "---" not in out  # frontmatter stripped
        assert "sources.md" in out

    def test_load_skill_unknown_name(self, tmp_path):
        _write_skill_folder(tmp_path)
        tools = build_skill_tools(_agent([_folder_skill()]), tmp_path)
        load_skill = next(t for t in tools if t.name == "load_skill")
        out = load_skill.invoke({"name": "nope"})
        assert "Unknown skill" in out
        assert "research" in out

    def test_read_skill_file(self, tmp_path):
        folder = _write_skill_folder(tmp_path)
        (folder / "sources.md").write_text("List of sources.\n")
        tools = build_skill_tools(_agent([_folder_skill()]), tmp_path)
        read = next(t for t in tools if t.name == "read_skill_file")
        out = read.invoke({"skill": "research", "path": "sources.md"})
        assert out == "List of sources.\n"

    def test_read_skill_file_missing_lists_available(self, tmp_path):
        folder = _write_skill_folder(tmp_path)
        (folder / "sources.md").write_text("x\n")
        tools = build_skill_tools(_agent([_folder_skill()]), tmp_path)
        read = next(t for t in tools if t.name == "read_skill_file")
        out = read.invoke({"skill": "research", "path": "nope.md"})
        assert "not found" in out
        assert "sources.md" in out

    def test_read_skill_file_rejects_traversal(self, tmp_path):
        _write_skill_folder(tmp_path)
        (tmp_path / "secret.txt").write_text("secret\n")
        tools = build_skill_tools(_agent([_folder_skill()]), tmp_path)
        read = next(t for t in tools if t.name == "read_skill_file")
        assert "Invalid path" in read.invoke({"skill": "research", "path": "../../secret.txt"})
        assert "Invalid path" in read.invoke(
            {"skill": "research", "path": str(tmp_path / "secret.txt")}
        )

    def test_read_skill_file_rejects_symlink_escape(self, tmp_path):
        folder = _write_skill_folder(tmp_path)
        (tmp_path / "secret.txt").write_text("secret\n")
        os.symlink(tmp_path / "secret.txt", folder / "link.md")
        tools = build_skill_tools(_agent([_folder_skill()]), tmp_path)
        read = next(t for t in tools if t.name == "read_skill_file")
        assert "Invalid path" in read.invoke({"skill": "research", "path": "link.md"})


class TestPromptWiring:
    @pytest.mark.asyncio
    async def test_prompt_includes_skills_section(self):
        from _vystak.runtime.prompt_callable import build_prompt

        agent = _agent([_folder_skill()])
        agent.instructions = "You are helpful."
        agent.compaction = None
        agent.memory = None
        fn = build_prompt(agent, memory_mgr=None, compactor=None, pruner=None)
        msgs = await fn({"messages": [HumanMessage(content="hi")]})
        assert "You are helpful." in msgs[0].content
        assert "- research: Deep-research workflow." in msgs[0].content
        assert "load_skill" in msgs[0].content

    @pytest.mark.asyncio
    async def test_prompt_appends_inline_skill_prompt(self):
        from _vystak.runtime.prompt_callable import build_prompt

        agent = _agent([Skill(name="ops", tools=["t"], prompt="Always verify orders.")])
        agent.instructions = "You are helpful."
        agent.compaction = None
        agent.memory = None
        fn = build_prompt(agent, memory_mgr=None, compactor=None, pruner=None)
        msgs = await fn({"messages": [HumanMessage(content="hi")]})
        assert "Always verify orders." in msgs[0].content


class TestAppFactoryWiring:
    def test_config_load_resolves_and_app_builds_with_skill_tools(self, tmp_path, monkeypatch):
        from _vystak.runtime.config import load_agent

        _write_skill_folder(tmp_path)
        (tmp_path / "vystak.yaml").write_text(
            "name: support\n"
            "framework: langchain-python\n"
            "default_model:\n"
            "  name: claude\n"
            "  provider: {name: anthropic, type: anthropic}\n"
            "  model_name: claude-sonnet-4-20250514\n"
            "skills: [research]\n"
        )
        agent = load_agent(str(tmp_path / "vystak.yaml"))
        assert agent.skills[0].content_digest

        tools = build_skill_tools(agent, tmp_path)
        assert sorted(t.name for t in tools) == ["load_skill", "read_skill_file"]

        monkeypatch.chdir(tmp_path)
        from _vystak.runtime.app_factory import build_agent_app

        app = build_agent_app(agent)
        assert len(app.routes) >= 7


class TestAgentCard:
    def test_card_carries_skill_description(self):
        from _vystak.runtime.a2a_native.card import build_agent_card

        agent = _agent([_folder_skill()])
        agent.instructions = "You are helpful."
        card = build_agent_card(agent, base_url="http://agent:8000")
        assert card.skills[0].description == "Deep-research workflow."
