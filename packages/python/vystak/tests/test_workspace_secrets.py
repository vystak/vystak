from vystak.schema.common import WorkspaceType
from vystak.schema.secret import Secret
from vystak.schema.workspace import Workspace


def test_workspace_default_has_no_secrets():
    ws = Workspace(name="w", type=WorkspaceType.PERSISTENT)
    assert ws.secrets == []
    assert ws.identity is None


def test_workspace_with_secrets():
    ws = Workspace(
        name="w",
        type=WorkspaceType.PERSISTENT,
        secrets=[Secret(name="STRIPE_API_KEY")],
    )
    assert len(ws.secrets) == 1
    assert ws.secrets[0].name == "STRIPE_API_KEY"


def test_workspace_with_explicit_identity_resource_id():
    uami_id = (
        "/subscriptions/xxx/resourceGroups/rg/providers/"
        "Microsoft.ManagedIdentity/userAssignedIdentities/my-uami"
    )
    ws = Workspace(
        name="w",
        type=WorkspaceType.PERSISTENT,
        identity=uami_id,
    )
    assert ws.identity == uami_id
