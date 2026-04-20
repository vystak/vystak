"""Tests for the Vault HTTP client wrapper."""

from unittest.mock import MagicMock, patch

from vystak_provider_docker.vault_client import (
    VaultClient,
    VaultInitResult,
)


def test_is_initialized_true():
    mock_client = MagicMock()
    mock_client.sys.is_initialized.return_value = True
    with patch("vystak_provider_docker.vault_client.hvac.Client", return_value=mock_client):
        client = VaultClient("http://vystak-vault:8200")
        assert client.is_initialized() is True


def test_is_initialized_false():
    mock_client = MagicMock()
    mock_client.sys.is_initialized.return_value = False
    with patch("vystak_provider_docker.vault_client.hvac.Client", return_value=mock_client):
        client = VaultClient("http://vystak-vault:8200")
        assert client.is_initialized() is False


def test_initialize_returns_keys_and_token():
    mock_client = MagicMock()
    mock_client.sys.initialize.return_value = {
        "keys_base64": ["k1", "k2", "k3", "k4", "k5"],
        "root_token": "hvs.deadbeef",
    }
    with patch("vystak_provider_docker.vault_client.hvac.Client", return_value=mock_client):
        client = VaultClient("http://vystak-vault:8200")
        result = client.initialize(key_shares=5, key_threshold=3)
        assert isinstance(result, VaultInitResult)
        assert result.unseal_keys == ["k1", "k2", "k3", "k4", "k5"]
        assert result.root_token == "hvs.deadbeef"
        mock_client.sys.initialize.assert_called_once_with(secret_shares=5, secret_threshold=3)


def test_unseal_with_keys_calls_per_key():
    mock_client = MagicMock()
    # is_sealed() is checked *before* each submission; must be True for all
    # three keys to be submitted (three probe calls, then the loop exits).
    mock_client.sys.is_sealed.side_effect = [True, True, True, False]
    mock_client.sys.submit_unseal_key.return_value = {"sealed": False}
    with patch("vystak_provider_docker.vault_client.hvac.Client", return_value=mock_client):
        client = VaultClient("http://vystak-vault:8200")
        client.unseal(["k1", "k2", "k3"])
        assert mock_client.sys.submit_unseal_key.call_count == 3
        mock_client.sys.submit_unseal_key.assert_any_call("k1")
        mock_client.sys.submit_unseal_key.assert_any_call("k2")
        mock_client.sys.submit_unseal_key.assert_any_call("k3")


def test_enable_kv_v2_idempotent():
    mock_client = MagicMock()
    # sys.list_mounted_secrets_engines returns existing mounts
    mock_client.sys.list_mounted_secrets_engines.return_value = {
        "secret/": {"type": "kv", "options": {"version": "2"}}
    }
    with patch("vystak_provider_docker.vault_client.hvac.Client", return_value=mock_client):
        client = VaultClient("http://vystak-vault:8200", token="root-token")
        client.enable_kv_v2("secret")
        mock_client.sys.enable_secrets_engine.assert_not_called()


def test_enable_kv_v2_creates_when_absent():
    mock_client = MagicMock()
    mock_client.sys.list_mounted_secrets_engines.return_value = {"other/": {"type": "kv"}}
    with patch("vystak_provider_docker.vault_client.hvac.Client", return_value=mock_client):
        client = VaultClient("http://vystak-vault:8200", token="root-token")
        client.enable_kv_v2("secret")
        mock_client.sys.enable_secrets_engine.assert_called_once_with(
            backend_type="kv", path="secret", options={"version": "2"}
        )


def test_enable_approle_auth_idempotent():
    mock_client = MagicMock()
    mock_client.sys.list_auth_methods.return_value = {"approle/": {"type": "approle"}}
    with patch("vystak_provider_docker.vault_client.hvac.Client", return_value=mock_client):
        client = VaultClient("http://vystak-vault:8200", token="root-token")
        client.enable_approle_auth()
        mock_client.sys.enable_auth_method.assert_not_called()


def test_write_policy():
    mock_client = MagicMock()
    with patch("vystak_provider_docker.vault_client.hvac.Client", return_value=mock_client):
        client = VaultClient("http://vystak-vault:8200", token="root-token")
        client.write_policy("my-policy", 'path "secret/data/FOO" { capabilities = ["read"] }')
        mock_client.sys.create_or_update_policy.assert_called_once()


def test_upsert_approle_creates_role():
    mock_client = MagicMock()
    mock_client.auth.approle.read_role.side_effect = Exception("not found")
    mock_client.auth.approle.read_role_id.return_value = {
        "data": {"role_id": "role-id-1"}
    }
    mock_client.auth.approle.generate_secret_id.return_value = {
        "data": {"secret_id": "secret-id-1"}
    }
    with patch("vystak_provider_docker.vault_client.hvac.Client", return_value=mock_client):
        client = VaultClient("http://vystak-vault:8200", token="root-token")
        role_id, secret_id = client.upsert_approle(
            role_name="my-role",
            policies=["my-policy"],
            token_ttl="1h",
            token_max_ttl="24h",
        )
        assert role_id == "role-id-1"
        assert secret_id == "secret-id-1"
        mock_client.auth.approle.create_or_update_approle.assert_called_once()


def test_kv_get_returns_none_on_missing():
    mock_client = MagicMock()
    import hvac.exceptions

    mock_client.secrets.kv.v2.read_secret_version.side_effect = hvac.exceptions.InvalidPath
    with patch("vystak_provider_docker.vault_client.hvac.Client", return_value=mock_client):
        client = VaultClient("http://vystak-vault:8200", token="root-token")
        assert client.kv_get("MISSING") is None


def test_kv_get_returns_value():
    mock_client = MagicMock()
    mock_client.secrets.kv.v2.read_secret_version.return_value = {
        "data": {"data": {"value": "the-secret"}}
    }
    with patch("vystak_provider_docker.vault_client.hvac.Client", return_value=mock_client):
        client = VaultClient("http://vystak-vault:8200", token="root-token")
        assert client.kv_get("MY_KEY") == "the-secret"


def test_kv_put_writes_value_under_value_field():
    mock_client = MagicMock()
    with patch("vystak_provider_docker.vault_client.hvac.Client", return_value=mock_client):
        client = VaultClient("http://vystak-vault:8200", token="root-token")
        client.kv_put("MY_KEY", "secret-value")
        mock_client.secrets.kv.v2.create_or_update_secret.assert_called_once_with(
            path="MY_KEY", secret={"value": "secret-value"}
        )
