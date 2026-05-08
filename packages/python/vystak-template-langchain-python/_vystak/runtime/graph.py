"""LangGraph react agent assembly."""

from typing import Any

PROVIDER_FACTORIES = {
    "anthropic": ("langchain_anthropic", "ChatAnthropic"),
    "openai": ("langchain_openai", "ChatOpenAI"),
}


def build_model(agent: Any):
    provider_type = agent.model.provider.type
    if provider_type not in PROVIDER_FACTORIES:
        raise ValueError(f"Unsupported provider: {provider_type}")
    module_name, cls_name = PROVIDER_FACTORIES[provider_type]
    module = __import__(module_name, fromlist=[cls_name])
    cls = getattr(module, cls_name)
    kwargs: dict[str, Any] = {"model": agent.model.model_name}
    api_key = getattr(agent.model.provider, "api_key", None)
    if api_key:
        kwargs["api_key"] = api_key
    base_url = getattr(agent.model.provider, "base_url", None)
    if base_url:
        kwargs["base_url"] = base_url
    return cls(**kwargs)


def build_graph(agent: Any, *, prompt, tools: list[Any], checkpointer: Any | None):
    from langgraph.prebuilt import create_react_agent

    model = build_model(agent)
    return create_react_agent(
        model=model,
        tools=tools,
        prompt=prompt,
        checkpointer=checkpointer,
    )
