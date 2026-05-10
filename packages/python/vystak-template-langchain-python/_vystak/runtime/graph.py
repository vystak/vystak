"""LangGraph react agent assembly with multi-model dispatch."""

from typing import Any

PROVIDER_FACTORIES = {
    "anthropic": ("langchain_anthropic", "ChatAnthropic"),
    "openai": ("langchain_openai", "ChatOpenAI"),
}


def build_models_pool(agent: Any) -> dict[str, Any]:
    """Return name → Model schema dict for default_model + every entry in models."""
    pool = {agent.default_model.name: agent.default_model}
    for m in agent.models:
        if m.name in pool:
            raise ValueError(f"duplicate model name {m.name!r} in agent pool")
        pool[m.name] = m
    return pool


def pick_model_name(agent: Any, *, session_stored: str | None, override: str | None) -> str:
    """Pick the model name to use for this turn.

    Precedence: session_stored > override > default. An override that
    names a model not in the pool falls back to default.
    """
    pool = build_models_pool(agent)
    if session_stored and session_stored in pool:
        return session_stored
    if override and override in pool:
        return override
    return agent.default_model.name


def build_model(model_schema: Any, *, callbacks: list[Any] | None = None):
    """Construct one LangChain chat model from a single Model schema entry."""
    import importlib

    provider_type = model_schema.provider.type
    if provider_type not in PROVIDER_FACTORIES:
        raise ValueError(f"Unsupported provider: {provider_type}")
    module_name, cls_name = PROVIDER_FACTORIES[provider_type]
    module = importlib.import_module(module_name)
    cls = getattr(module, cls_name)
    kwargs: dict[str, Any] = {"model": model_schema.model_name}
    kwargs.update(model_schema.parameters or {})
    if callbacks:
        kwargs["callbacks"] = callbacks
    return cls(**kwargs)


def build_models_bindings(agent: Any, *, callbacks: list[Any] | None = None) -> dict[str, Any]:
    """Construct LangChain bindings for every model in the agent's pool.

    Returns name → bound model. Used by app_factory to dispatch turns.
    """
    return {
        name: build_model(schema, callbacks=callbacks)
        for name, schema in build_models_pool(agent).items()
    }


def build_graph(agent: Any, *, prompt, tools: list[Any], checkpointer: Any | None,
                model_name: str | None = None):
    """Build a react agent graph bound to a single chosen model.

    `model_name` selects from the agent's pool. None falls back to default.
    """
    from langgraph.prebuilt import create_react_agent

    from _vystak.runtime.token_usage import build_token_usage_callback

    callbacks = [build_token_usage_callback()]
    bindings = build_models_bindings(agent, callbacks=callbacks)
    chosen = model_name if model_name in bindings else agent.default_model.name
    return create_react_agent(
        model=bindings[chosen],
        tools=tools,
        prompt=prompt,
        checkpointer=checkpointer,
    )
