"""AgentCard renders the /.well-known/agent.json shape from an Agent schema."""

from _vystak.runtime.a2a.card import AgentCard
from vystak.schema.agent import Agent
from vystak.schema.model import Model
from vystak.schema.provider import Provider
from vystak.schema.skill import Skill


def _agent(skills: list[Skill] | None = None) -> Agent:
    return Agent(
        name="weather",
        instructions="A helpful weather agent.",
        model=Model(
            name="claude",
            provider=Provider(name="anthropic", type="anthropic"),
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
    skills = [Skill(name="forecast", tools=["get_weather"])]
    card = AgentCard(_agent(skills=skills)).render()
    assert len(card["skills"]) == 1
    assert card["skills"][0]["id"] == "forecast"
    assert card["skills"][0]["name"] == "forecast"
    assert card["skills"][0]["description"] == ""


def test_render_default_input_output_modes():
    card = AgentCard(_agent()).render()
    assert "text/plain" in card["defaultInputModes"]
    assert "text/plain" in card["defaultOutputModes"]


def test_render_omits_description_when_no_instructions():
    agent = _agent()
    agent.instructions = None
    card = AgentCard(agent).render()
    assert card["description"] == ""
