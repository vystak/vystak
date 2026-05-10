"""build_graph — assembles create_react_agent from agent + tools + prompt."""

from _vystak.runtime.graph import build_graph, build_model


def _agent(model_provider="anthropic"):
    from vystak.schema.agent import Agent
    from vystak.schema.model import Model
    from vystak.schema.provider import Provider
    return Agent(
        name="test",
        framework="langchain-python",
        default_model=Model(
            name="m",
            provider=Provider(name=model_provider, type=model_provider, api_key="test-key"),
            model_name="claude-sonnet-4-6",
        ),
    )


def test_build_model_returns_chat_anthropic_for_anthropic_provider():
    model = build_model(_agent("anthropic").default_model)
    assert model.__class__.__name__ == "ChatAnthropic"


def test_build_model_returns_chat_openai_for_openai_provider(monkeypatch):
    # ChatOpenAI's underlying client validates credentials at construction.
    # The Provider schema silently drops the test fixture's api_key= kwarg
    # (pydantic ignores extras), so we set OPENAI_API_KEY in the env instead.
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    model = build_model(_agent("openai").default_model)
    assert model.__class__.__name__ == "ChatOpenAI"


def test_build_graph_returns_compiled_graph():
    async def fake_prompt(state, config):
        return state["messages"]

    g = build_graph(_agent(), prompt=fake_prompt, tools=[], checkpointer=None)
    assert hasattr(g, "ainvoke") or hasattr(g, "invoke")
