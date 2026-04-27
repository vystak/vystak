from vystak.schema.agent import Agent
from vystak.schema.compaction import Compaction
from vystak.schema.model import Model
from vystak.schema.provider import Provider
from vystak_adapter_langchain.templates import _compaction_enabled


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


def test_no_compaction_disabled():
    assert _compaction_enabled(_agent()) is False


def test_off_disabled():
    assert _compaction_enabled(_agent(Compaction(mode="off"))) is False


def test_conservative_enabled():
    assert _compaction_enabled(_agent(Compaction(mode="conservative"))) is True


def test_aggressive_enabled():
    assert _compaction_enabled(_agent(Compaction(mode="aggressive"))) is True
