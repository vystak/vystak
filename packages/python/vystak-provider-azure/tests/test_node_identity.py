from unittest.mock import MagicMock

from vystak_provider_azure.nodes.identity import UserAssignedIdentityNode


def _fake_msi_client() -> MagicMock:
    client = MagicMock()
    client.user_assigned_identities.create_or_update.return_value = MagicMock(
        id="/subscriptions/x/resourceGroups/rg/providers/Microsoft.ManagedIdentity/userAssignedIdentities/my-uami",
        client_id="00000000-0000-0000-0000-000000000001",
        principal_id="11111111-1111-1111-1111-111111111111",
    )
    return client


def test_creates_uami_and_returns_ids():
    client = _fake_msi_client()
    node = UserAssignedIdentityNode(
        client=client,
        rg_name="rg",
        uami_name="my-uami",
        location="eastus2",
    )
    result = node.provision(context={})
    assert result.info["resource_id"].endswith("/my-uami")
    assert result.info["client_id"] == "00000000-0000-0000-0000-000000000001"
    assert result.info["principal_id"] == "11111111-1111-1111-1111-111111111111"


def test_passes_through_existing_resource_id_when_provided():
    node = UserAssignedIdentityNode.from_existing(
        resource_id="/subscriptions/x/resourceGroups/rg/providers/Microsoft.ManagedIdentity/userAssignedIdentities/existing",
        name="external-uami",
    )
    result = node.provision(context={})
    assert result.info["resource_id"].endswith("/existing")
