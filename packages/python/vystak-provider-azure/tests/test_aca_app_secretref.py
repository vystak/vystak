"""Tests for ACA app revision JSON on both the Vault and default delivery paths.

Covers ``build_revision_for_vault`` (vault-backed, UAMI + lifecycle:None)
and ``build_revision_default_path`` (inline values, no UAMI). Every
per-container scoping assertion here codifies the isolation invariant:
the agent container's env never contains workspace-scoped secrets and
vice versa.
"""

from unittest.mock import MagicMock

from vystak.schema.agent import Agent
from vystak.schema.common import WorkspaceType
from vystak.schema.model import Model
from vystak.schema.platform import Platform
from vystak.schema.provider import Provider
from vystak.schema.secret import Secret
from vystak.schema.workspace import Workspace


def _fixture_agent(with_workspace_secret: bool = False) -> Agent:
    azure = Provider(name="azure", type="azure", config={"location": "eastus2"})
    platform = Platform(name="aca", type="container-apps", provider=azure)
    anthropic = Provider(name="anthropic", type="anthropic")
    workspace = None
    if with_workspace_secret:
        workspace = Workspace(
            name="w",
            type=WorkspaceType.PERSISTENT,
            secrets=[Secret(name="STRIPE_API_KEY")],
        )
    return Agent(
        name="assistant",
        model=Model(name="m", provider=anthropic, model_name="claude-sonnet-4-6"),
        secrets=[Secret(name="ANTHROPIC_API_KEY")],
        workspace=workspace,
        platform=platform,
    )


def test_build_revision_agent_only_with_vault():
    from vystak_provider_azure.nodes.aca_app import build_revision_for_vault

    agent = _fixture_agent(with_workspace_secret=False)
    revision = build_revision_for_vault(
        agent=agent,
        vault_uri="https://my-vault.vault.azure.net/",
        agent_identity_resource_id="/subs/.../uami-agent",
        agent_identity_client_id="agent-client-id",
        workspace_identity_resource_id=None,
        workspace_identity_client_id=None,
        model_secrets=["ANTHROPIC_API_KEY"],
        workspace_secrets=[],
        acr_login_server="myacr.azurecr.io",
        acr_password_secret_ref="acr-password",
        acr_password_value="pw",
        agent_image="myacr.azurecr.io/assistant:abc",
        workspace_image=None,
    )
    # Expect: one main container (agent), one UAMI attached, both secrets wired via secretRef
    assert len(revision["properties"]["template"]["containers"]) == 1
    agent_container = revision["properties"]["template"]["containers"][0]
    assert any(
        e.get("secretRef") == "anthropic-api-key" and e["name"] == "ANTHROPIC_API_KEY"
        for e in agent_container["env"]
    )
    identities = revision["identity"]["userAssignedIdentities"]
    assert len(identities) == 1
    lifecycle = revision["properties"]["configuration"]["identitySettings"]
    assert all(
        s["lifecycle"] == "None"
        for s in lifecycle
        if s["identity"] != "ACR_IMAGEPULL_IDENTITY_RESOURCE_ID"
    )
    kv_secrets = [
        s for s in revision["properties"]["configuration"]["secrets"] if "keyVaultUrl" in s
    ]
    assert any(s["keyVaultUrl"].endswith("/secrets/anthropic-api-key") for s in kv_secrets)


def test_build_revision_agent_plus_workspace_sidecar():
    from vystak_provider_azure.nodes.aca_app import build_revision_for_vault

    agent = _fixture_agent(with_workspace_secret=True)
    revision = build_revision_for_vault(
        agent=agent,
        vault_uri="https://my-vault.vault.azure.net/",
        agent_identity_resource_id="/subs/.../uami-agent",
        agent_identity_client_id="agent-client-id",
        workspace_identity_resource_id="/subs/.../uami-workspace",
        workspace_identity_client_id="workspace-client-id",
        model_secrets=["ANTHROPIC_API_KEY"],
        workspace_secrets=["STRIPE_API_KEY"],
        acr_login_server="myacr.azurecr.io",
        acr_password_secret_ref="acr-password",
        acr_password_value="pw",
        agent_image="myacr.azurecr.io/assistant:abc",
        workspace_image="myacr.azurecr.io/assistant-workspace:abc",
    )
    containers = revision["properties"]["template"]["containers"]
    assert len(containers) == 2
    agent_c = next(c for c in containers if c["name"] == "agent")
    workspace_c = next(c for c in containers if c["name"] == "workspace")
    # Each container sees ONLY its own secret in env
    assert any(e["name"] == "ANTHROPIC_API_KEY" for e in agent_c["env"])
    assert not any(e["name"] == "STRIPE_API_KEY" for e in agent_c["env"])
    assert any(e["name"] == "STRIPE_API_KEY" for e in workspace_c["env"])
    assert not any(e["name"] == "ANTHROPIC_API_KEY" for e in workspace_c["env"])
    # Both UAMIs attached
    assert len(revision["identity"]["userAssignedIdentities"]) == 2
    # Each KV-backed secret references its owning UAMI
    kv_secrets = [
        s for s in revision["properties"]["configuration"]["secrets"] if "keyVaultUrl" in s
    ]
    anth = next(s for s in kv_secrets if s["keyVaultUrl"].endswith("/secrets/anthropic-api-key"))
    stripe = next(s for s in kv_secrets if s["keyVaultUrl"].endswith("/secrets/stripe-api-key"))
    assert anth["identity"].endswith("/uami-agent")
    assert stripe["identity"].endswith("/uami-workspace")
    # All identitySettings are lifecycle: None (except ACR-pull which may be None too)
    lifecycle = revision["properties"]["configuration"]["identitySettings"]
    non_acr = [s for s in lifecycle if "uami-" in s["identity"].lower()]
    assert all(s["lifecycle"] == "None" for s in non_acr)


def test_container_app_node_uses_vault_path_when_vault_result_in_context():
    """When context contains a KeyVaultNode result, ContainerAppNode uses
    build_revision_for_vault for revision creation."""
    from vystak.providers.base import DeployPlan, GeneratedCode
    from vystak_provider_azure.nodes.aca_app import ContainerAppNode

    # Fixture: vault result in context
    context = {
        "keyvault:my-vault": MagicMock(
            info={"vault_uri": "https://my-vault.vault.azure.net/"}
        ),
        "uami:assistant-agent": MagicMock(
            info={
                "resource_id": "/subs/.../uami-agent",
                "client_id": "agent-c",
                "principal_id": "p1",
            }
        ),
        "uami:assistant-workspace": MagicMock(
            info={
                "resource_id": "/subs/.../uami-workspace",
                "client_id": "ws-c",
                "principal_id": "p2",
            }
        ),
    }

    agent = _fixture_agent(with_workspace_secret=True)
    aca_client = MagicMock()
    docker_client = MagicMock()
    plan = DeployPlan(
        agent_name=agent.name,
        actions=[],
        current_hash=None,
        target_hash="t-hash",
        changes={},
    )
    code = GeneratedCode(files={"main.py": "pass", "requirements.txt": ""}, entrypoint="main.py")
    node = ContainerAppNode(
        aca_client=aca_client,
        docker_client=docker_client,
        rg_name="rg",
        agent=agent,
        generated_code=code,
        plan=plan,
        platform_config={"location": "eastus2"},
    )
    node.set_vault_context(
        vault_key="keyvault:my-vault",
        agent_identity_key="uami:assistant-agent",
        workspace_identity_key="uami:assistant-workspace",
        model_secrets=["ANTHROPIC_API_KEY"],
        workspace_secrets=["STRIPE_API_KEY"],
    )
    # The node's _build_body should return a dict that's topologically equivalent
    # to build_revision_for_vault output — verify a few anchor assertions.
    body = node._build_body(
        context=context,
        acr_info={"login_server": "myacr.azurecr.io", "password": "pw"},
    )
    container_names = [c["name"] for c in body["properties"]["template"]["containers"]]
    assert "agent" in container_names
    assert "workspace" in container_names


def test_channel_app_with_vault_uses_per_container_secretref():
    from vystak.providers.base import DeployPlan, GeneratedCode
    from vystak.schema.channel import Channel
    from vystak.schema.common import ChannelType
    from vystak_provider_azure.nodes.aca_channel_app import AzureChannelAppNode

    channel = Channel(
        name="slack",
        type=ChannelType.SLACK,
        platform=_fixture_agent().platform,
        secrets=[Secret(name="SLACK_BOT_TOKEN")],
    )
    aca_client = MagicMock()
    docker_client = MagicMock()
    plan = DeployPlan(
        agent_name=channel.name,
        actions=[],
        current_hash=None,
        target_hash="t-hash",
        changes={},
    )
    code = GeneratedCode(
        files={"Dockerfile": "FROM python:3.11-slim\n", "requirements.txt": ""},
        entrypoint="server.py",
    )
    node = AzureChannelAppNode(
        aca_client=aca_client,
        docker_client=docker_client,
        rg_name="rg",
        channel=channel,
        generated_code=code,
        plan=plan,
        platform_config={"location": "eastus2"},
    )
    node.set_vault_context(
        vault_key="keyvault:my-vault",
        identity_key="uami:slack-channel",
        secrets=["SLACK_BOT_TOKEN"],
    )
    context = {
        "keyvault:my-vault": MagicMock(info={"vault_uri": "https://v.vault.azure.net/"}),
        "uami:slack-channel": MagicMock(
            info={
                "resource_id": "/subs/.../uami-slack",
                "client_id": "c",
                "principal_id": "p",
            }
        ),
    }
    body = node._build_body(
        context=context,
        acr_info={"login_server": "r.azurecr.io", "password": "p"},
    )
    kv = [s for s in body["properties"]["configuration"]["secrets"] if "keyVaultUrl" in s]
    assert any(s["keyVaultUrl"].endswith("/secrets/slack-bot-token") for s in kv)
    assert all(
        s["lifecycle"] == "None" for s in body["properties"]["configuration"]["identitySettings"]
    )


def test_build_revision_default_path_agent_only():
    """No workspace, no Vault: single container, agent's secrets inline with
    per-container secretRef scoping. No UAMI, no lifecycle:None."""
    from vystak_provider_azure.nodes.aca_app import build_revision_default_path

    agent = _fixture_agent(with_workspace_secret=False)
    revision = build_revision_default_path(
        agent=agent,
        model_secrets={"ANTHROPIC_API_KEY": "sk-test"},
        workspace_secrets={},
        acr_login_server="myacr.azurecr.io",
        acr_password_secret_ref="acr-password",
        acr_password_value="pw",
        agent_image="myacr.azurecr.io/assistant:abc",
        workspace_image=None,
    )

    # Single container
    containers = revision["properties"]["template"]["containers"]
    assert len(containers) == 1
    assert containers[0]["name"] == "agent"

    # Agent env wires ANTHROPIC_API_KEY via secretRef
    agent_env = containers[0]["env"]
    assert any(
        e.get("secretRef") == "anthropic-api-key" and e["name"] == "ANTHROPIC_API_KEY"
        for e in agent_env
    )

    # No UAMI / no identity block / no identitySettings
    assert "identity" not in revision
    assert "identitySettings" not in revision["properties"]["configuration"]

    # Inline secrets pool has the value, no keyVaultUrl refs
    secrets = revision["properties"]["configuration"]["secrets"]
    anthropic_entry = next(s for s in secrets if s["name"] == "anthropic-api-key")
    assert anthropic_entry["value"] == "sk-test"
    assert "keyVaultUrl" not in anthropic_entry


def test_build_revision_default_path_isolates_workspace_from_agent():
    """Workspace declared, no Vault: two containers. Agent container's env
    contains ONLY the agent's secrets; workspace container's env contains
    ONLY the workspace's secrets. The per-container isolation invariant
    holds without Vault."""
    from vystak_provider_azure.nodes.aca_app import build_revision_default_path

    agent = _fixture_agent(with_workspace_secret=True)
    revision = build_revision_default_path(
        agent=agent,
        model_secrets={"ANTHROPIC_API_KEY": "sk-agent"},
        workspace_secrets={"STRIPE_API_KEY": "sk-workspace"},
        acr_login_server="myacr.azurecr.io",
        acr_password_secret_ref="acr-password",
        acr_password_value="pw",
        agent_image="myacr.azurecr.io/assistant:abc",
        workspace_image="myacr.azurecr.io/assistant-workspace:abc",
    )

    containers = revision["properties"]["template"]["containers"]
    assert len(containers) == 2

    agent_container = next(c for c in containers if c["name"] == "agent")
    workspace_container = next(c for c in containers if c["name"] == "workspace")

    agent_env_names = {e["name"] for e in agent_container["env"]}
    ws_env_names = {e["name"] for e in workspace_container["env"]}

    # Per-container scoping invariant
    assert "ANTHROPIC_API_KEY" in agent_env_names
    assert "STRIPE_API_KEY" not in agent_env_names, (
        "agent container leaked STRIPE_API_KEY into its env"
    )
    assert "STRIPE_API_KEY" in ws_env_names
    assert "ANTHROPIC_API_KEY" not in ws_env_names, (
        "workspace container leaked ANTHROPIC_API_KEY into its env"
    )

    # Both values present in the revision-level inline secrets pool
    secret_pool = {s["name"]: s for s in revision["properties"]["configuration"]["secrets"]}
    assert secret_pool["anthropic-api-key"]["value"] == "sk-agent"
    assert secret_pool["stripe-api-key"]["value"] == "sk-workspace"

    # No UAMI on default path
    assert "identity" not in revision
    assert "identitySettings" not in revision["properties"]["configuration"]


def test_build_revision_default_path_no_workspace_image_no_sidecar():
    """Even with workspace_secrets provided, if workspace_image is None
    no sidecar container is emitted — matches build_revision_for_vault's
    contract."""
    from vystak_provider_azure.nodes.aca_app import build_revision_default_path

    agent = _fixture_agent(with_workspace_secret=True)
    revision = build_revision_default_path(
        agent=agent,
        model_secrets={"ANTHROPIC_API_KEY": "sk-a"},
        workspace_secrets={"STRIPE_API_KEY": "sk-s"},
        acr_login_server="myacr.azurecr.io",
        acr_password_secret_ref="acr-password",
        acr_password_value="pw",
        agent_image="myacr.azurecr.io/assistant:abc",
        workspace_image=None,
    )

    containers = revision["properties"]["template"]["containers"]
    assert len(containers) == 1
    assert containers[0]["name"] == "agent"

    # Workspace secret value must NOT appear in the inline pool — no consumer.
    pool_names = {s["name"] for s in revision["properties"]["configuration"]["secrets"]}
    assert "stripe-api-key" not in pool_names, (
        "workspace secret value transmitted to Azure with no container to consume it"
    )


def test_build_revision_default_path_rejects_same_name_collision():
    """Agent and workspace declaring the same secret name is rejected —
    otherwise the workspace container would silently resolve its secretRef
    to the agent's value via the shared inline pool."""
    import pytest
    from vystak_provider_azure.nodes.aca_app import build_revision_default_path

    agent = _fixture_agent(with_workspace_secret=True)
    with pytest.raises(ValueError) as exc:
        build_revision_default_path(
            agent=agent,
            model_secrets={"DATABASE_URL": "sk-agent-db"},
            workspace_secrets={"DATABASE_URL": "sk-workspace-db"},
            acr_login_server="myacr.azurecr.io",
            acr_password_secret_ref="acr-password",
            acr_password_value="pw",
            agent_image="myacr.azurecr.io/assistant:abc",
            workspace_image="myacr.azurecr.io/assistant-workspace:abc",
        )
    assert "collision" in str(exc.value).lower()
    assert "database-url" in str(exc.value)


def test_build_revision_for_vault_no_rpc_url_when_no_sidecar():
    """VYSTAK_WORKSPACE_RPC_URL must not be injected into the agent env
    when no workspace sidecar will actually exist — pointing the agent
    at localhost:50051 with no listener produces a runtime connection
    error. Edge case: workspace UAMI declared but no image/secrets, so
    emit_workspace_sidecar is False."""
    from vystak_provider_azure.nodes.aca_app import build_revision_for_vault

    agent = _fixture_agent(with_workspace_secret=True)
    revision = build_revision_for_vault(
        agent=agent,
        vault_uri="https://my-vault.vault.azure.net/",
        agent_identity_resource_id="/subs/.../uami-agent",
        agent_identity_client_id="agent-client-id",
        workspace_identity_resource_id="/subs/.../uami-workspace",
        workspace_identity_client_id="workspace-client-id",
        model_secrets=["ANTHROPIC_API_KEY"],
        workspace_secrets=[],  # no workspace secrets → emit_workspace_sidecar is False
        acr_login_server="myacr.azurecr.io",
        acr_password_secret_ref="acr-password",
        acr_password_value="pw",
        agent_image="myacr.azurecr.io/assistant:abc",
        workspace_image="myacr.azurecr.io/assistant-workspace:abc",
    )
    agent_container = revision["properties"]["template"]["containers"][0]
    agent_env_names = {e["name"] for e in agent_container["env"]}
    assert "VYSTAK_WORKSPACE_RPC_URL" not in agent_env_names, (
        "agent env points at a non-existent RPC URL because the sidecar "
        "is not emitted when workspace_secrets is empty"
    )


def test_build_revision_for_vault_drops_dead_workspace_refs():
    """When workspace_image is None, workspace KV refs must not appear in
    the revision's secrets block — no sidecar will consume them."""
    from vystak_provider_azure.nodes.aca_app import build_revision_for_vault

    agent = _fixture_agent(with_workspace_secret=True)
    revision = build_revision_for_vault(
        agent=agent,
        vault_uri="https://my-vault.vault.azure.net/",
        agent_identity_resource_id="/subs/.../uami-agent",
        agent_identity_client_id="agent-client-id",
        workspace_identity_resource_id="/subs/.../uami-workspace",
        workspace_identity_client_id="workspace-client-id",
        model_secrets=["ANTHROPIC_API_KEY"],
        workspace_secrets=["STRIPE_API_KEY"],
        acr_login_server="myacr.azurecr.io",
        acr_password_secret_ref="acr-password",
        acr_password_value="pw",
        agent_image="myacr.azurecr.io/assistant:abc",
        workspace_image=None,
    )

    containers = revision["properties"]["template"]["containers"]
    assert len(containers) == 1

    kv_names = {
        s["name"]
        for s in revision["properties"]["configuration"]["secrets"]
        if "keyVaultUrl" in s
    }
    assert "anthropic-api-key" in kv_names
    assert "stripe-api-key" not in kv_names, (
        "workspace KV ref transmitted to Azure with no container to consume it"
    )
