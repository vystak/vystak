from vystak.schema.agent import Agent
from vystak.schema.compaction import Compaction
from vystak.schema.model import Model
from vystak.schema.provider import Provider
from vystak_adapter_langchain.templates import generate_server_py


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


def test_compact_endpoint_emitted():
    code = generate_server_py(_agent_compaction())
    assert '@app.post("/v1/sessions/{thread_id}/compact")' in code
    assert "class CompactRequest" in code


def test_inspection_endpoints_emitted():
    code = generate_server_py(_agent_compaction())
    assert '@app.get("/v1/sessions/{thread_id}/compactions")' in code
    assert '@app.get("/v1/sessions/{thread_id}/compactions/{generation}")' in code


def test_no_compaction_no_endpoints():
    a = _agent_compaction().model_copy(update={"compaction": None})
    code = generate_server_py(a)
    assert "/v1/sessions/" not in code
