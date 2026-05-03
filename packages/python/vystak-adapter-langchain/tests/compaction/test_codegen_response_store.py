from vystak.schema.agent import Agent
from vystak.schema.compaction import Compaction
from vystak.schema.model import Model
from vystak.schema.provider import Provider
from vystak_adapter_langchain.responses import generate_responses_handler_code


def _agent_compaction():
    return Agent(
        name="x",
        model=Model(
            name="m",
            provider=Provider(name="anthropic", type="anthropic"),
            model_name="claude-sonnet-4-6",
        ),
        compaction=Compaction(mode="conservative"),
    )


def test_responses_emits_last_input_tokens_threading():
    code = generate_responses_handler_code(_agent_compaction())
    assert "last_input_tokens" in code


def test_get_response_includes_thread_id():
    code = generate_responses_handler_code(_agent_compaction())
    assert "stored.get('thread_id')" in code or "'thread_id': stored.get" in code
