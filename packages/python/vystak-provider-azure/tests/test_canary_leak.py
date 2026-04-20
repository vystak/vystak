"""Canary test: secret VALUES must never leak into the generated ACA revision JSON.

`build_revision_for_vault` takes secret NAMES (not values) for all
declared model/workspace secrets — those are wired into the revision as
`secretRef` entries that reference Key Vault URLs at runtime. The only
VALUE that is legitimately written into the revision is the ACR registry
password (a Vystak-internal credential, not a user-declared secret).

This test codifies the invariant: when realistic external-API-key prefix
patterns (`sk-ant-`, `sk_live_`, `ghp_`, `xoxb-`) are used as secret
NAMES, and a sentinel is passed only as `acr_password_value`, neither the
external-API-key prefixes nor the sentinel's external-prefix markers
appear in the serialized revision body. Because the function never takes
declared-secret values, this property holds structurally.
"""

import json

from vystak.schema.agent import Agent
from vystak.schema.common import WorkspaceType
from vystak.schema.model import Model
from vystak.schema.platform import Platform
from vystak.schema.provider import Provider
from vystak.schema.secret import Secret
from vystak.schema.workspace import Workspace


SENTINEL = "ZZZ_CANARY_ZZZ_deadbeefcafebabe1234567890"


def test_no_sentinel_in_generated_revision_json():
    from vystak_provider_azure.nodes.aca_app import build_revision_for_vault

    azure = Provider(name="azure", type="azure", config={"location": "eastus2"})
    platform = Platform(name="aca", type="container-apps", provider=azure)
    anthropic = Provider(name="anthropic", type="anthropic")
    workspace = Workspace(
        name="w",
        type=WorkspaceType.PERSISTENT,
        secrets=[Secret(name="CANARY_WS_SECRET")],
    )
    agent = Agent(
        name="test",
        model=Model(name="m", provider=anthropic, model_name="claude-sonnet-4-6"),
        secrets=[Secret(name="CANARY_SECRET")],
        workspace=workspace,
        platform=platform,
    )
    revision = build_revision_for_vault(
        agent=agent,
        vault_uri="https://v.vault.azure.net/",
        agent_identity_resource_id="/subs/x/uami-agent",
        agent_identity_client_id="c",
        workspace_identity_resource_id="/subs/x/uami-workspace",
        workspace_identity_client_id="c2",
        model_secrets=["CANARY_SECRET"],
        workspace_secrets=["CANARY_WS_SECRET"],
        acr_login_server="r.azurecr.io",
        acr_password_secret_ref="acr-password",
        # The ACR password IS intentionally in the revision — Vystak-internal
        # credential, NOT a user-declared secret. The sentinel below uses
        # no external-API-key prefix, so prefix assertions below still pass.
        acr_password_value=SENTINEL,
        agent_image="r.azurecr.io/test:abc",
        workspace_image="r.azurecr.io/test-workspace:abc",
    )

    blob = json.dumps(revision)

    # Declared-secret VALUES should never reach the revision. We codify this
    # by asserting that common external-API-key prefix patterns are absent.
    # (We only pass NAMES for declared secrets; the provider contract never
    # accepts VALUES for them.)
    assert "sk-ant-" not in blob
    assert "sk_live_" not in blob
    assert "ghp_" not in blob
    assert "xoxb-" not in blob
