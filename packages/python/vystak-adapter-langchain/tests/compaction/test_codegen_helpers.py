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


def test_context_window_default():
    from vystak_adapter_langchain.templates import _context_window_for
    assert _context_window_for(_agent()) == 200_000


def test_context_window_override_from_compaction():
    from vystak_adapter_langchain.templates import _context_window_for
    a = _agent(Compaction(mode="aggressive", context_window=5000))
    assert _context_window_for(a) == 5000


def test_context_window_unknown_model_defaults_to_200k():
    from vystak_adapter_langchain.templates import _context_window_for
    a = Agent(
        name="x",
        model=Model(
            name="m",
            provider=Provider(name="anthropic", type="anthropic"),
            model_name="some-future-model",
        ),
    )
    assert _context_window_for(a) == 200_000
