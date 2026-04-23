from unittest.mock import MagicMock

import pytest
from vystak_provider_docker.nodes.vault_secret_sync import VaultSecretSyncNode


def test_push_if_missing_pushes_absent():
    fake_vc = MagicMock()
    fake_vc.kv_get.return_value = None  # absent
    node = VaultSecretSyncNode(
        vault_client=fake_vc,
        declared_secrets=["ANTHROPIC_API_KEY"],
        env_values={"ANTHROPIC_API_KEY": "sk-ant-xxx"},
    )
    result = node.provision(context={})
    fake_vc.kv_put.assert_called_once_with("ANTHROPIC_API_KEY", "sk-ant-xxx")
    assert result.info["pushed"] == ["ANTHROPIC_API_KEY"]
    assert result.info["skipped"] == []
    assert result.info["missing"] == []


def test_push_if_missing_skips_present():
    fake_vc = MagicMock()
    fake_vc.kv_get.return_value = "preserved"
    node = VaultSecretSyncNode(
        vault_client=fake_vc,
        declared_secrets=["ANTHROPIC_API_KEY"],
        env_values={"ANTHROPIC_API_KEY": "different"},
    )
    result = node.provision(context={})
    fake_vc.kv_put.assert_not_called()
    assert result.info["skipped"] == ["ANTHROPIC_API_KEY"]


def test_force_overwrites():
    fake_vc = MagicMock()
    fake_vc.kv_get.return_value = "old"
    node = VaultSecretSyncNode(
        vault_client=fake_vc,
        declared_secrets=["ANTHROPIC_API_KEY"],
        env_values={"ANTHROPIC_API_KEY": "new"},
        force=True,
    )
    result = node.provision(context={})
    fake_vc.kv_put.assert_called_once_with("ANTHROPIC_API_KEY", "new")
    assert result.info["pushed"] == ["ANTHROPIC_API_KEY"]


def test_missing_aborts_by_default():
    fake_vc = MagicMock()
    fake_vc.kv_get.return_value = None
    node = VaultSecretSyncNode(
        vault_client=fake_vc,
        declared_secrets=["ABSENT"],
        env_values={},
    )
    with pytest.raises(RuntimeError, match="ABSENT"):
        node.provision(context={})


def test_missing_with_allow_missing():
    fake_vc = MagicMock()
    fake_vc.kv_get.return_value = None
    node = VaultSecretSyncNode(
        vault_client=fake_vc,
        declared_secrets=["ABSENT"],
        env_values={},
        allow_missing=True,
    )
    result = node.provision(context={})
    assert result.info["missing"] == ["ABSENT"]
