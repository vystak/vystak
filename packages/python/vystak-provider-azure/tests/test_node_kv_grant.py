from unittest.mock import MagicMock

from vystak_provider_azure.nodes.kv_grant import KvGrantNode

KV_SECRETS_USER_ROLE_ID = "4633458b-17de-408a-b874-0445c86b69e6"


def _auth_client() -> MagicMock:
    client = MagicMock()
    client.role_assignments.create.return_value = MagicMock(id="ra-id", name="ra-name")
    return client


def test_assigns_kv_secrets_user_role_on_secret():
    client = _auth_client()
    node = KvGrantNode(
        client=client,
        scope="/subscriptions/x/resourceGroups/rg/providers/Microsoft.KeyVault/vaults/v/secrets/STRIPE_API_KEY",
        principal_id="11111111-1111-1111-1111-111111111111",
        subscription_id="x",
    )
    node.provision(context={})
    args, kwargs = client.role_assignments.create.call_args
    # Scope positional arg 0, role assignment name positional arg 1, params kwarg or positional 2
    assert kwargs.get("scope") == node._scope or args[0] == node._scope
    # The role_definition_id must reference Key Vault Secrets User
    params = kwargs.get("parameters") or args[2]
    assert KV_SECRETS_USER_ROLE_ID in params.role_definition_id
    assert params.principal_id == "11111111-1111-1111-1111-111111111111"


def test_skips_when_principal_id_is_none():
    client = _auth_client()
    node = KvGrantNode(
        client=client,
        scope="/subscriptions/x/.../secrets/S",
        principal_id=None,  # from pre-existing UAMI whose principal_id wasn't fetched
        subscription_id="x",
    )
    result = node.provision(context={})
    client.role_assignments.create.assert_not_called()
    assert result.info["skipped"] is True
