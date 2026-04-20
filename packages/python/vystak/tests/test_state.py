from pathlib import Path

from vystak.state import (
    load_identities_state,
    load_secrets_state,
    record_identity_created,
    record_secret_pushed,
    save_secrets_state,
)


def test_secrets_state_round_trip(tmp_path: Path):
    p = tmp_path / ".vystak" / "secrets-state.json"
    save_secrets_state(
        p,
        {"STRIPE_API_KEY": {"pushed_at": "2026-04-19T10:00:00Z", "hash_prefix": "abcd"}},
    )
    state = load_secrets_state(p)
    assert state == {
        "STRIPE_API_KEY": {"pushed_at": "2026-04-19T10:00:00Z", "hash_prefix": "abcd"}
    }


def test_load_secrets_state_missing_returns_empty(tmp_path: Path):
    assert load_secrets_state(tmp_path / "nothing.json") == {}


def test_record_secret_pushed(tmp_path: Path):
    p = tmp_path / ".vystak" / "secrets-state.json"
    record_secret_pushed(p, "STRIPE_API_KEY", hash_prefix="abcd")
    state = load_secrets_state(p)
    assert "STRIPE_API_KEY" in state
    assert state["STRIPE_API_KEY"]["hash_prefix"] == "abcd"
    assert "pushed_at" in state["STRIPE_API_KEY"]


def test_record_identity_created(tmp_path: Path):
    p = tmp_path / ".vystak" / "identities-state.json"
    record_identity_created(
        p, name="agent-uami", resource_id="/subscriptions/.../uami-foo"
    )
    state = load_identities_state(p)
    assert state["agent-uami"]["resource_id"] == "/subscriptions/.../uami-foo"
