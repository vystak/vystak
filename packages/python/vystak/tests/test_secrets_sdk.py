import pytest


def test_get_returns_env_value(monkeypatch):
    monkeypatch.setenv("FOO_KEY", "bar")
    from vystak import secrets
    assert secrets.get("FOO_KEY") == "bar"


def test_get_missing_raises_secret_not_available(monkeypatch):
    monkeypatch.delenv("NOPE_KEY", raising=False)
    from vystak import secrets
    from vystak.secrets import SecretNotAvailableError
    with pytest.raises(SecretNotAvailableError, match="NOPE_KEY"):
        secrets.get("NOPE_KEY")


def test_secret_not_available_message_is_actionable(monkeypatch):
    monkeypatch.delenv("ABSENT_KEY", raising=False)
    from vystak import secrets
    from vystak.secrets import SecretNotAvailableError
    try:
        secrets.get("ABSENT_KEY")
    except SecretNotAvailableError as e:
        assert "ABSENT_KEY" in str(e)
        assert "Declare it on the Agent / Workspace / Channel" in str(e)
