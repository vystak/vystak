from unittest.mock import MagicMock

import pytest
from azure.core.exceptions import ResourceNotFoundError
from vystak_provider_azure.nodes.secret_sync import SecretSyncNode


def _secret_client(existing: dict[str, str] | None = None) -> MagicMock:
    existing = existing or {}
    client = MagicMock()

    def _get(name):
        if name in existing:
            mock = MagicMock()
            mock.value = existing[name]
            return mock
        raise ResourceNotFoundError("not found")

    client.get_secret.side_effect = _get
    client.set_secret.return_value = MagicMock()
    return client


def test_push_if_missing_pushes_absent_secrets():
    client = _secret_client(existing={})
    node = SecretSyncNode(
        client=client,
        declared_secrets=["ANTHROPIC_API_KEY"],
        env_values={"ANTHROPIC_API_KEY": "sk-ant-value"},
    )
    result = node.provision(context={})
    # KV name uses hyphens (Azure Key Vault rejects underscores).
    client.set_secret.assert_called_once_with("anthropic-api-key", "sk-ant-value")
    assert result.info["pushed"] == ["ANTHROPIC_API_KEY"]
    assert result.info["skipped"] == []
    assert result.info["missing"] == []


def test_push_if_missing_skips_present_secrets():
    # Existing KV state uses the hyphen-translated name.
    client = _secret_client(existing={"anthropic-api-key": "preserved"})
    node = SecretSyncNode(
        client=client,
        declared_secrets=["ANTHROPIC_API_KEY"],
        env_values={"ANTHROPIC_API_KEY": "different"},
    )
    result = node.provision(context={})
    client.set_secret.assert_not_called()
    assert result.info["skipped"] == ["ANTHROPIC_API_KEY"]


def test_force_overwrites_present_secrets():
    client = _secret_client(existing={"anthropic-api-key": "old"})
    node = SecretSyncNode(
        client=client,
        declared_secrets=["ANTHROPIC_API_KEY"],
        env_values={"ANTHROPIC_API_KEY": "new"},
        force=True,
    )
    result = node.provision(context={})
    client.set_secret.assert_called_once_with("anthropic-api-key", "new")
    assert result.info["pushed"] == ["ANTHROPIC_API_KEY"]


def test_missing_secret_aborts_with_actionable_error():
    client = _secret_client(existing={})
    node = SecretSyncNode(
        client=client,
        declared_secrets=["ABSENT_KEY"],
        env_values={},
    )
    with pytest.raises(RuntimeError, match="ABSENT_KEY"):
        node.provision(context={})


def test_missing_with_allow_missing_does_not_abort():
    client = _secret_client(existing={})
    node = SecretSyncNode(
        client=client,
        declared_secrets=["ABSENT_KEY"],
        env_values={},
        allow_missing=True,
    )
    result = node.provision(context={})
    assert result.info["missing"] == ["ABSENT_KEY"]
