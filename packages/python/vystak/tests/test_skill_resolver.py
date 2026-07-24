"""resolve_folder_skills — SKILL.md parsing, digest, and error cases."""

import pytest
from vystak.schema.agent import Agent
from vystak.schema.model import Model
from vystak.schema.provider import Provider
from vystak.schema.skill import Skill
from vystak.schema.skill_resolver import (
    compute_skill_digest,
    parse_skill_md,
    resolve_folder_skills,
)


def make_agent(**overrides):
    anthropic = Provider(name="anthropic", type="anthropic")
    model = Model(name="claude", provider=anthropic, model_name="claude-sonnet-4-20250514")
    defaults = {
        "name": "support",
        "framework": "langchain-python",
        "default_model": model,
    }
    defaults.update(overrides)
    return Agent(**defaults)


SKILL_MD = (
    "---\n"
    "name: research\n"
    "description: Deep-research workflow.\n"
    "tools: [web_search]\n"
    "---\n"
    "When asked to research, follow this process.\n"
)


def write_skill(root, name="research", text=SKILL_MD):
    folder = root / "skills" / name
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text(text)
    return folder


class TestParseSkillMd:
    def test_happy_path(self):
        meta, body = parse_skill_md(SKILL_MD)
        assert meta["name"] == "research"
        assert meta["description"] == "Deep-research workflow."
        assert meta["tools"] == ["web_search"]
        assert body.startswith("When asked to research")

    def test_missing_frontmatter_raises(self):
        with pytest.raises(ValueError, match="frontmatter"):
            parse_skill_md("no frontmatter here\n")

    def test_unclosed_frontmatter_raises(self):
        with pytest.raises(ValueError, match="not closed"):
            parse_skill_md("---\nname: x\n")

    def test_unknown_keys_rejected(self):
        text = "---\nname: x\ndescription: d\nbogus: 1\n---\nbody\n"
        with pytest.raises(ValueError, match="bogus"):
            parse_skill_md(text)


class TestComputeSkillDigest:
    def test_deterministic(self, tmp_path):
        folder = write_skill(tmp_path)
        assert compute_skill_digest(folder) == compute_skill_digest(folder)

    def test_edit_changes_digest(self, tmp_path):
        folder = write_skill(tmp_path)
        d1 = compute_skill_digest(folder)
        (folder / "SKILL.md").write_text(SKILL_MD + "more\n")
        assert compute_skill_digest(folder) != d1

    def test_added_resource_changes_digest(self, tmp_path):
        folder = write_skill(tmp_path)
        d1 = compute_skill_digest(folder)
        (folder / "sources.md").write_text("some sources\n")
        assert compute_skill_digest(folder) != d1

    def test_rename_changes_digest(self, tmp_path):
        folder = write_skill(tmp_path)
        (folder / "a.md").write_text("x\n")
        d1 = compute_skill_digest(folder)
        (folder / "a.md").rename(folder / "b.md")
        assert compute_skill_digest(folder) != d1


class TestResolveFolderSkills:
    def test_shorthand_resolves_folder(self, tmp_path):
        write_skill(tmp_path)
        agent = make_agent(skills=["research"])
        resolve_folder_skills([agent], tmp_path)
        skill = agent.skills[0]
        assert skill.description == "Deep-research workflow."
        assert skill.tools == ["web_search"]
        assert skill.path == "skills/research"
        assert skill.content_digest

    def test_missing_folder_raises(self, tmp_path):
        agent = make_agent(skills=["research"])
        with pytest.raises(ValueError, match="skills/research/SKILL.md"):
            resolve_folder_skills([agent], tmp_path)

    def test_frontmatter_name_mismatch_raises(self, tmp_path):
        write_skill(tmp_path, name="other", text=SKILL_MD)
        agent = make_agent(skills=["other"])
        with pytest.raises(ValueError, match="does not match"):
            resolve_folder_skills([agent], tmp_path)

    def test_missing_description_raises(self, tmp_path):
        write_skill(tmp_path, text="---\nname: research\n---\nbody\n")
        agent = make_agent(skills=["research"])
        with pytest.raises(ValueError, match="description"):
            resolve_folder_skills([agent], tmp_path)

    def test_explicit_path(self, tmp_path):
        folder = tmp_path / "shared" / "deep-research"
        folder.mkdir(parents=True)
        (folder / "SKILL.md").write_text(SKILL_MD)
        agent = make_agent(skills=[Skill(name="research", path="shared/deep-research")])
        resolve_folder_skills([agent], tmp_path)
        assert agent.skills[0].description == "Deep-research workflow."
        assert agent.skills[0].path == "shared/deep-research"

    def test_explicit_path_missing_raises(self, tmp_path):
        agent = make_agent(skills=[Skill(name="research", path="nope/research")])
        with pytest.raises(ValueError, match="nope/research"):
            resolve_folder_skills([agent], tmp_path)

    def test_inline_skill_untouched_even_with_matching_folder(self, tmp_path):
        write_skill(tmp_path)
        agent = make_agent(skills=[Skill(name="research", tools=["my_tool"])])
        resolve_folder_skills([agent], tmp_path)
        assert agent.skills[0].description is None
        assert agent.skills[0].path is None
        assert agent.skills[0].tools == ["my_tool"]

    def test_inline_prompt_skill_untouched(self, tmp_path):
        agent = make_agent(skills=[Skill(name="ops", prompt="Verify orders.")])
        resolve_folder_skills([agent], tmp_path)  # no folder needed, no error
        assert agent.skills[0].content_digest is None

    def test_idempotent(self, tmp_path):
        write_skill(tmp_path)
        agent = make_agent(skills=["research"])
        resolve_folder_skills([agent], tmp_path)
        digest = agent.skills[0].content_digest
        tools = list(agent.skills[0].tools)
        resolve_folder_skills([agent], tmp_path)
        assert agent.skills[0].content_digest == digest
        assert agent.skills[0].tools == tools  # no duplicate merge

    def test_subagents_resolved(self, tmp_path):
        write_skill(tmp_path)
        sub = make_agent(name="researcher", skills=["research"])
        agent = make_agent(subagents=[sub])
        resolve_folder_skills([agent], tmp_path)
        assert agent.subagents[0].skills[0].content_digest


class TestLoaderIntegration:
    def test_load_agent_resolves_folder_skills(self, tmp_path):
        from vystak.schema.loader import load_agent

        write_skill(tmp_path)
        (tmp_path / "agent.yaml").write_text(
            "name: support\n"
            "framework: langchain-python\n"
            "default_model:\n"
            "  name: claude\n"
            "  provider: {name: anthropic, type: anthropic}\n"
            "  model_name: claude-sonnet-4-20250514\n"
            "skills: [research]\n"
        )
        agent = load_agent(tmp_path / "agent.yaml")
        assert agent.skills[0].description == "Deep-research workflow."
        assert agent.skills[0].content_digest
