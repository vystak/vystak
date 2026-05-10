"""LangGraph react agent assembly."""

from typing import Any

PROVIDER_FACTORIES = {
    "anthropic": ("langchain_anthropic", "ChatAnthropic"),
    "openai": ("langchain_openai", "ChatOpenAI"),
}


def build_model(agent: Any):
    """Construct a LangChain chat model from the agent's Model schema.

    Credentials are read from environment variables (ANTHROPIC_API_KEY,
    OPENAI_API_KEY, etc.) by the LangChain provider classes. Provider config
    overrides (base_url, api_key) will land via agent.default_model.parameters in a
    future phase; the schema doesn't carry them today.
    """
    import importlib

    provider_type = agent.default_model.provider.type
    if provider_type not in PROVIDER_FACTORIES:
        raise ValueError(f"Unsupported provider: {provider_type}")
    module_name, cls_name = PROVIDER_FACTORIES[provider_type]
    module = importlib.import_module(module_name)
    cls = getattr(module, cls_name)
    return cls(model=agent.default_model.model_name)


def build_graph(agent: Any, *, prompt, tools: list[Any], checkpointer: Any | None):
    from langgraph.prebuilt import create_react_agent

    model = build_model(agent)
    return create_react_agent(
        model=model,
        tools=tools,
        prompt=prompt,
        checkpointer=checkpointer,
    )
