"""LangChain/LangGraph framework adapter."""

from agentstack.providers.base import FrameworkAdapter, GeneratedCode, ValidationError
from agentstack.schema.agent import Agent

from agentstack_adapter_langchain.templates import (
    MODEL_PROVIDERS,
    _get_session_store,
    generate_agent_py,
    generate_requirements_txt,
    generate_server_py,
    generate_store_py,
)


class LangChainAdapter(FrameworkAdapter):
    """Generates LangGraph agent code + FastAPI harness from an Agent schema."""

    def generate(self, agent: Agent) -> GeneratedCode:
        """Generate deployable LangGraph agent code."""
        files = {
            "agent.py": generate_agent_py(agent),
            "server.py": generate_server_py(agent),
            "requirements.txt": generate_requirements_txt(agent),
        }

        # Bundle AsyncSqliteStore for SQLite deployments
        session_store = _get_session_store(agent)
        if session_store and session_store.engine == "sqlite":
            files["store.py"] = generate_store_py()

        return GeneratedCode(files=files, entrypoint="server.py")

    def validate(self, agent: Agent) -> list[ValidationError]:
        """Validate that the agent can be deployed with LangChain."""
        errors = []

        provider_type = agent.model.provider.type
        if provider_type not in MODEL_PROVIDERS:
            supported = ", ".join(MODEL_PROVIDERS.keys())
            errors.append(
                ValidationError(
                    field="model.provider.type",
                    message=f"Unsupported provider '{provider_type}'. Supported: {supported}",
                )
            )

        return errors
