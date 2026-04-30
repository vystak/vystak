from vystak.schema.agent import Agent
from vystak.schema.compaction import Compaction
from vystak.schema.model import Model
from vystak.schema.provider import Provider
from vystak_adapter_langchain.templates import generate_agent_py


def _agent(comp=None):
    return Agent(
        name="x",
        model=Model(
            name="m",
            provider=Provider(name="anthropic", type="anthropic"),
            model_name="claude-sonnet-4-6",
        ),
        compaction=comp,
    )


def test_off_emits_no_compaction_imports():
    code = generate_agent_py(_agent(Compaction(mode="off")))
    assert "vystak_adapter_langchain.compaction" not in code
    assert "create_summarization_tool_middleware" not in code


def test_no_compaction_emits_no_compaction_imports():
    code = generate_agent_py(_agent())
    assert "vystak_adapter_langchain.compaction" not in code


def test_conservative_emits_compaction_imports():
    """Compaction-enabled agent imports our runtime module.

    Layer 2 (autonomous middleware) emission is disabled in the current
    codegen path — langchain 1.1.x renamed the API and removed the
    autonomous-tool variant. Layers 1+3 still wire in via the prompt
    callable.
    """
    code = generate_agent_py(_agent(Compaction(mode="conservative")))
    assert "from vystak_adapter_langchain.compaction import" in code
    # Sanity: the disabled middleware doesn't sneak back in.
    assert "create_summarization_tool_middleware" not in code


def test_aggressive_emits_compaction_imports():
    code = generate_agent_py(_agent(Compaction(mode="aggressive")))
    assert "from vystak_adapter_langchain.compaction import" in code
    assert "create_summarization_tool_middleware" not in code


def test_use_langchain_middleware_off_no_emission():
    """With use_langchain_middleware=False (the default), the codegen
    should NOT import or wire the langchain SummarizationMiddleware."""
    code = generate_agent_py(_agent(Compaction(mode="conservative")))
    assert "SummarizationMiddleware" not in code
    assert "from langchain.agents.middleware" not in code


def test_use_langchain_middleware_on_emits_wiring():
    """With use_langchain_middleware=True, codegen emits the import and
    threads `middleware=[SummarizationMiddleware(...)]` into create_react_agent."""
    code = generate_agent_py(
        _agent(Compaction(mode="conservative", use_langchain_middleware=True))
    )
    assert "from langchain.agents.middleware import SummarizationMiddleware" in code
    assert "SummarizationMiddleware(" in code
    assert "middleware=[SummarizationMiddleware(" in code
    assert "trigger=('fraction', _compaction_policy.trigger_pct)" in code
    assert "keep=('fraction', _compaction_policy.keep_recent_pct)" in code


def test_explicit_summarizer_model_emitted():
    custom = Model(
        name="haiku",
        provider=Provider(name="anthropic", type="anthropic"),
        model_name="claude-haiku-4-5-20251001",
    )
    code = generate_agent_py(_agent(Compaction(mode="conservative", summarizer=custom)))
    assert "claude-haiku-4-5-20251001" in code
