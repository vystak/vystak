from vystak.schema.agent import Agent
from vystak.schema.compaction import Compaction
from vystak.schema.model import Model
from vystak.schema.provider import Provider
from vystak.schema.service import Postgres
from vystak_adapter_langchain.templates import generate_agent_py


def _agent_with_postgres_and_compaction():
    return Agent(
        name="x",
        model=Model(
            name="m",
            provider=Provider(name="anthropic", type="anthropic"),
            model_name="claude-sonnet-4-6",
        ),
        sessions=Postgres(
            provider=Provider(name="docker", type="docker"),
        ),
        compaction=Compaction(mode="conservative"),
    )


def test_prompt_callable_calls_prune_and_maybe_compact():
    code = generate_agent_py(_agent_with_postgres_and_compaction())
    assert "prune_messages(" in code
    assert "maybe_compact(" in code


def test_prompt_callable_assigns_vystak_msg_id():
    code = generate_agent_py(_agent_with_postgres_and_compaction())
    assert "assign_vystak_msg_id(" in code


def test_no_compaction_no_prune_call():
    a = _agent_with_postgres_and_compaction()
    a = a.model_copy(update={"compaction": None})
    code = generate_agent_py(a)
    assert "prune_messages(" not in code
    assert "maybe_compact(" not in code
