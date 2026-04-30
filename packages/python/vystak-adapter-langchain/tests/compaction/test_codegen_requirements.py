from vystak.schema.agent import Agent
from vystak.schema.compaction import Compaction
from vystak.schema.model import Model
from vystak.schema.provider import Provider
from vystak_adapter_langchain.templates import generate_requirements_txt


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


def test_no_compaction_no_langchain_pin():
    reqs = generate_requirements_txt(_agent())
    assert "langchain>=" not in reqs


def test_compaction_does_not_add_langchain_pin():
    """Compaction runtime uses only langchain-core; no extra langchain pin needed
    in the current codegen path (Layer 2 middleware emission is disabled until
    langchain's middleware API restabilizes).
    """
    reqs = generate_requirements_txt(_agent(Compaction(mode="conservative")))
    assert "langchain>=1.0,<1.2" not in reqs
    # langchain-core (transitively pulled by langchain-anthropic) is still present.
    assert "langchain-core>=" in reqs


def test_off_no_pin():
    reqs = generate_requirements_txt(_agent(Compaction(mode="off")))
    assert "langchain>=" not in reqs


def test_use_langchain_middleware_pins_langchain_and_prebuilt():
    """Opt-in middleware needs langchain 1.1+ and a working
    langgraph-prebuilt pair."""
    reqs = generate_requirements_txt(
        _agent(Compaction(mode="conservative", use_langchain_middleware=True))
    )
    assert "langchain>=1.1,<1.2" in reqs
    assert "langgraph-prebuilt<=1.0.5" in reqs
    assert "langchain-core>=1.0,<2.0" in reqs


def test_default_compaction_no_middleware_pins():
    """Without the opt-in, no langchain middleware pins in requirements."""
    reqs = generate_requirements_txt(_agent(Compaction(mode="conservative")))
    assert "langchain>=1.1" not in reqs
    assert "langgraph-prebuilt" not in reqs
