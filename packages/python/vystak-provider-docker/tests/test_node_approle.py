from unittest.mock import MagicMock

from vystak_provider_docker.nodes.approle import AppRoleNode


def test_creates_policy_and_approle():
    fake_vc = MagicMock()
    fake_vc.upsert_approle.return_value = ("role-id-1", "secret-id-1")
    node = AppRoleNode(
        vault_client=fake_vc,
        principal_name="assistant-agent",
        secret_names=["ANTHROPIC_API_KEY"],
    )
    result = node.provision(context={})
    # Policy written with correct HCL
    fake_vc.write_policy.assert_called_once()
    args, kwargs = fake_vc.write_policy.call_args
    assert kwargs.get("name") == "assistant-agent-policy" or args[0] == "assistant-agent-policy"
    policy_hcl = kwargs.get("hcl") or args[1]
    assert 'path "secret/data/ANTHROPIC_API_KEY"' in policy_hcl
    # AppRole created
    fake_vc.upsert_approle.assert_called_once()
    ur_kwargs = fake_vc.upsert_approle.call_args.kwargs
    assert ur_kwargs["role_name"] == "assistant-agent"
    assert ur_kwargs["policies"] == ["assistant-agent-policy"]
    # Result carries creds
    assert result.info["role_id"] == "role-id-1"
    assert result.info["secret_id"] == "secret-id-1"
    assert result.info["policy_name"] == "assistant-agent-policy"


def test_empty_secret_list_still_creates_role():
    fake_vc = MagicMock()
    fake_vc.upsert_approle.return_value = ("r", "s")
    node = AppRoleNode(
        vault_client=fake_vc,
        principal_name="no-secrets-principal",
        secret_names=[],
    )
    result = node.provision(context={})
    fake_vc.write_policy.assert_called_once()
    # Role still created so the principal has an auth identity, just no paths
    assert result.success is True


def test_destroy_removes_approle_and_policy():
    fake_vc = MagicMock()
    node = AppRoleNode(
        vault_client=fake_vc,
        principal_name="assistant-agent",
        secret_names=["ANTHROPIC_API_KEY"],
    )
    node.destroy()
    fake_vc.delete_approle.assert_called_once_with("assistant-agent")
    fake_vc.delete_policy.assert_called_once_with("assistant-agent-policy")
