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


def test_conservative_emits_middleware_with_preset_kwargs():
    code = generate_agent_py(_agent(Compaction(mode="conservative")))
    assert "from vystak_adapter_langchain.compaction import" in code
    assert "create_summarization_tool_middleware" in code
    assert "keep_last_n_messages" in code


def test_aggressive_emits_middleware():
    code = generate_agent_py(_agent(Compaction(mode="aggressive")))
    assert "create_summarization_tool_middleware" in code


def test_explicit_summarizer_model_emitted():
    custom = Model(
        name="haiku",
        provider=Provider(name="anthropic", type="anthropic"),
        model_name="claude-haiku-4-5-20251001",
    )
    code = generate_agent_py(_agent(Compaction(mode="conservative", summarizer=custom)))
    assert "claude-haiku-4-5-20251001" in code
