from vystak_provider_azure.nodes.aca_workspace_app import (
    build_workspace_revision,
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
