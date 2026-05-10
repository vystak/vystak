"""Tests for multi-model dispatch in the langchain template runtime."""

from types import SimpleNamespace

from _vystak.runtime.graph import build_models_pool, pick_model_name


def _model(name: str, provider_type: str = "anthropic", model_name: str = "x"):
    return SimpleNamespace(
        name=name,
        model_name=model_name,
        provider=SimpleNamespace(type=provider_type),
        parameters={},
    )


def _agent(default, extras):
    return SimpleNamespace(default_model=default, models=extras)


def test_pool_includes_default_and_models():
    a = _agent(_model("opus"), [_model("haiku"), _model("sonnet")])
    pool = build_models_pool(a)
    assert set(pool) == {"opus", "haiku", "sonnet"}


def test_pick_default_when_no_inputs():
    a = _agent(_model("opus"), [_model("haiku")])
    assert pick_model_name(a, session_stored=None, override=None) == "opus"


def test_pick_override_when_in_pool():
    a = _agent(_model("opus"), [_model("haiku")])
    assert pick_model_name(a, session_stored=None, override="haiku") == "haiku"


def test_pick_session_wins_over_override():
    a = _agent(_model("opus"), [_model("haiku"), _model("sonnet")])
    assert pick_model_name(a, session_stored="sonnet", override="haiku") == "sonnet"


def test_pick_falls_back_when_override_missing():
    """An override naming a model NOT in the pool falls back to default."""
    a = _agent(_model("opus"), [_model("haiku")])
    assert pick_model_name(a, session_stored=None, override="ghost") == "opus"
