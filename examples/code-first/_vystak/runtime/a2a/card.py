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
                    "description": getattr(skill, "description", "") or "",
                }
                for skill in a.skills
            ],
        }
