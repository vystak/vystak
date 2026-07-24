from unittest.mock import MagicMock

from vystak_provider_azure.nodes.aca_workspace_app import (
    ACAWorkspaceAppNode,
    build_workspace_revision,
)


def _make_node(workspace_name: str = "dev", agent_name: str = "assistant"):
    """Construct a bare ACAWorkspaceAppNode with mocked Azure/Docker clients.

    Mirrors the Agent/Workspace construction pattern used in
    test_provider_workspace_graph.py, but builds the node directly rather
    than routing through AzureProvider._add_workspace_nodes — the tests
    here exercise _build_and_push_image in isolation.
    """
    from vystak.schema import Agent, Model, Platform, Provider, Workspace

    agent = Agent(
        name=agent_name,
        framework="langchain-python",
        default_model=Model(
            name="claude",
            model_name="claude-3",
            provider=Provider(name="anthropic", type="anthropic"),
        ),
        platform=Platform(
            name="aca",
            type="container-apps",
            provider=Provider(name="azure", type="azure"),
            config={
                "subscription_id": "sub-test",
                "resource_group": "rg-test",
                "location": "eastus",
            },
        ),
        workspace=Workspace(name=workspace_name, image="python:3.11-slim"),
    )
    return ACAWorkspaceAppNode(
        aca_client=MagicMock(),
        docker_client=MagicMock(),
        rg_name="rg-test",
        env_name="env-test",
        agent=agent,
        platform_config=agent.platform.config,
        location="eastus",
        ssh_keygen_node_name="keygen",
        files_share_node_name=None,
        env_storage_node_name=None,
        acr_node_name="acr-test",
        vault_node_name="vault-test",
        workspace_identity_node_name="uami-test",
    )


def test_build_workspace_revision_internal_tcp_ingress_port_22():
    """Workspace app must expose internal TCP ingress on port 22."""
    body = build_workspace_revision(
        agent_name="assistant",
        location="eastus",
        workspace_image="myacr.azurecr.io/vystak-assistant-workspace:abc",
        workspace_identity_resource_id=(
            "/subscriptions/x/resourceGroups/rg/providers/"
            "Microsoft.ManagedIdentity/userAssignedIdentities/uami-ws"
        ),
        vault_uri="https://kv.vault.azure.net/",
        ssh_kv_secrets=[
            "vystak-workspace-ssh-assistant-host-key",
            "vystak-workspace-ssh-assistant-client-key-pub",
        ],
        user_secrets=["STRIPE_API_KEY"],
        acr_login_server="myacr.azurecr.io",
        acr_password_secret_ref="acr-password",
        acr_password_value="REDACTED",
        storage_name="vystak-assistant-workspace",
        share_subpath="/workspace",
        persistence_mode="volume",
    )

    ingress = body["properties"]["configuration"]["ingress"]
    assert ingress["external"] is False
    assert ingress["transport"] == "tcp"
    assert ingress["targetPort"] == 22
    assert ingress["exposedPort"] == 22


def test_build_workspace_revision_mounts_volume_at_workspace():
    body = build_workspace_revision(
        agent_name="assistant",
        location="eastus",
        workspace_image="acr/img:tag",
        workspace_identity_resource_id="x",
        vault_uri="https://kv.vault.azure.net/",
        ssh_kv_secrets=[],
        user_secrets=[],
        acr_login_server="acr.azurecr.io",
        acr_password_secret_ref="acr-pwd",
        acr_password_value="REDACTED",
        storage_name="vystak-assistant-workspace",
        share_subpath="/workspace",
        persistence_mode="volume",
    )
    template = body["properties"]["template"]
    assert template["volumes"] == [
        {
            "name": "workspace-data",
            "storageType": "AzureFile",
            "storageName": "vystak-assistant-workspace",
        }
    ]
    assert template["containers"][0]["volumeMounts"] == [
        {"volumeName": "workspace-data", "mountPath": "/workspace"}
    ]


def test_build_workspace_revision_ephemeral_no_volume_mount():
    body = build_workspace_revision(
        agent_name="assistant",
        location="eastus",
        workspace_image="acr/img:tag",
        workspace_identity_resource_id="x",
        vault_uri="https://kv.vault.azure.net/",
        ssh_kv_secrets=[],
        user_secrets=[],
        acr_login_server="acr.azurecr.io",
        acr_password_secret_ref="acr-pwd",
        acr_password_value="REDACTED",
        storage_name=None,
        share_subpath=None,
        persistence_mode="ephemeral",
    )
    template = body["properties"]["template"]
    assert "volumes" not in template or template["volumes"] == []
    assert template["containers"][0].get("volumeMounts", []) == []


def test_build_workspace_revision_ssh_keys_via_secretref():
    body = build_workspace_revision(
        agent_name="assistant",
        location="eastus",
        workspace_image="acr/img:tag",
        workspace_identity_resource_id="x",
        vault_uri="https://kv.vault.azure.net/",
        ssh_kv_secrets=[
            "vystak-workspace-ssh-assistant-host-key",
            "vystak-workspace-ssh-assistant-client-key-pub",
        ],
        user_secrets=[],
        acr_login_server="acr.azurecr.io",
        acr_password_secret_ref="acr-pwd",
        acr_password_value="REDACTED",
        storage_name="ws",
        share_subpath="/workspace",
        persistence_mode="volume",
    )
    secrets = body["properties"]["configuration"]["secrets"]
    secret_names = {s["name"] for s in secrets}
    assert "vystak-workspace-ssh-assistant-host-key" in secret_names
    assert "vystak-workspace-ssh-assistant-client-key-pub" in secret_names

    container = body["properties"]["template"]["containers"][0]
    env_names = {e["name"] for e in container["env"]}
    assert "VYSTAK_SSH_HOST_KEY" in env_names
    assert "VYSTAK_SSH_AUTHORIZED_KEYS" in env_names


def test_build_workspace_revision_scale_locked_to_one():
    body = build_workspace_revision(
        agent_name="assistant",
        location="eastus",
        workspace_image="acr/img:tag",
        workspace_identity_resource_id="x",
        vault_uri="https://kv.vault.azure.net/",
        ssh_kv_secrets=[],
        user_secrets=[],
        acr_login_server="acr.azurecr.io",
        acr_password_secret_ref="acr-pwd",
        acr_password_value="REDACTED",
        storage_name="ws",
        share_subpath="/workspace",
        persistence_mode="volume",
    )
    scale = body["properties"]["template"]["scale"]
    assert scale["minReplicas"] == 1
    assert scale["maxReplicas"] == 1


def test_nfs_volume_uses_nfs_storage_type():
    body = build_workspace_revision(
        agent_name="assistant",
        location="eastus",
        workspace_image="acr/img:tag",
        workspace_identity_resource_id="x",
        vault_uri="https://kv.vault.azure.net/",
        ssh_kv_secrets=[],
        user_secrets=[],
        acr_login_server="acr.azurecr.io",
        acr_password_secret_ref="acr-pwd",
        acr_password_value="REDACTED",
        storage_name="vystak-volume-team-code",
        share_subpath="/workspace",
        persistence_mode="volume",
        nfs=True,
    )
    vol = body["properties"]["template"]["volumes"][0]
    assert vol["storageType"] == "NfsAzureFile"
    assert vol["storageName"] == "vystak-volume-team-code"


def test_build_context_stages_tools_seed_and_entrypoint(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools" / "t.py").write_text("def t(): pass\n")
    seed = tmp_path / "workspaces" / "dev"
    seed.mkdir(parents=True)
    (seed / "hello.txt").write_text("seeded\n")

    node = _make_node()  # workspace name "dev", agent name "assistant"
    node._docker.images.push.return_value = [{}]
    node._build_and_push_image(
        acr_login_server="acr.azurecr.io",
        acr_username="acr",
        acr_password="pw",
    )
    build_dir = tmp_path / ".vystak" / "assistant-workspace-azure"
    assert (build_dir / "tools" / "t.py").exists()
    assert (build_dir / "seed" / "hello.txt").read_text() == "seeded\n"
    assert (build_dir / "workspace-entrypoint.sh").exists()
