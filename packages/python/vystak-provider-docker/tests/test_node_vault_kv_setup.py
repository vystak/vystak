from unittest.mock import MagicMock

from vystak_provider_docker.nodes.vault_kv_setup import VaultKvSetupNode


def test_enables_kv_v2_and_approle_auth():
    fake_vc = MagicMock()
    node = VaultKvSetupNode(vault_client=fake_vc)
    result = node.provision(context={})
    fake_vc.enable_kv_v2.assert_called_once_with("secret")
    fake_vc.enable_approle_auth.assert_called_once()
    assert result.success is True


def test_sets_token_before_calls():
    """If a token is passed, the underlying client's token should be set
    before calling enable_*."""
    fake_vc = MagicMock()
    node = VaultKvSetupNode(vault_client=fake_vc, root_token="hvs.xxx")
    node.provision(context={})
    fake_vc.set_token.assert_called_once_with("hvs.xxx")
