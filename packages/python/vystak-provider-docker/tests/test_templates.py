"""Tests for Vault config template generators."""

from vystak_provider_docker.templates import (
    generate_agent_hcl,
    generate_entrypoint_shim,
    generate_policy_hcl,
    generate_server_hcl,
)


def test_server_hcl_uses_file_storage():
    hcl = generate_server_hcl()
    assert 'storage "file"' in hcl
    assert 'path = "/vault/file"' in hcl
    assert 'listener "tcp"' in hcl
    # HCL-style alignment produces multiple spaces around `=`
    assert '"0.0.0.0:8200"' in hcl
    assert "tls_disable = true" in hcl  # internal Docker network only


def test_server_hcl_custom_port():
    hcl = generate_server_hcl(port=8900)
    assert '"0.0.0.0:8900"' in hcl


def test_agent_hcl_contains_approle_and_template():
    hcl = generate_agent_hcl(
        vault_address="http://vystak-vault:8200",
        secret_names=["ANTHROPIC_API_KEY", "STRIPE_API_KEY"],
    )
    assert 'vault {\n  address = "http://vystak-vault:8200"' in hcl
    assert 'method "approle"' in hcl
    assert 'role_id_file_path   = "/vault/approle/role_id"' in hcl
    assert 'secret_id_file_path = "/vault/approle/secret_id"' in hcl
    assert 'destination = "/shared/secrets.env"' in hcl
    assert 'perms       = "0444"' in hcl
    assert 'with secret "secret/data/ANTHROPIC_API_KEY"' in hcl
    assert "ANTHROPIC_API_KEY={{ .Data.data.value }}" in hcl
    assert 'with secret "secret/data/STRIPE_API_KEY"' in hcl
    assert "STRIPE_API_KEY={{ .Data.data.value }}" in hcl


def test_agent_hcl_empty_secrets_still_valid():
    hcl = generate_agent_hcl(
        vault_address="http://vystak-vault:8200",
        secret_names=[],
    )
    assert "template {" in hcl
    # Empty template still renders (no `with secret` blocks), file exists but empty.


def test_policy_hcl_one_secret():
    hcl = generate_policy_hcl(secret_names=["ANTHROPIC_API_KEY"])
    assert 'path "secret/data/ANTHROPIC_API_KEY"' in hcl
    assert 'capabilities = ["read"]' in hcl


def test_policy_hcl_multiple_secrets():
    hcl = generate_policy_hcl(secret_names=["A", "B", "C"])
    assert hcl.count("path ") == 3
    for name in ("A", "B", "C"):
        assert f'path "secret/data/{name}"' in hcl


def test_policy_hcl_empty_denies_all():
    hcl = generate_policy_hcl(secret_names=[])
    assert "path" not in hcl


def test_entrypoint_shim_structure():
    shim = generate_entrypoint_shim()
    assert shim.startswith("#!/bin/sh")
    assert "SECRETS_FILE=" in shim
    assert "set -a" in shim
    assert ". \"$SECRETS_FILE\"" in shim
    assert "set +a" in shim
    assert 'exec "$@"' in shim


def test_entrypoint_shim_has_wait_loop():
    shim = generate_entrypoint_shim()
    assert "seq 1 30" in shim  # 30-second wait
    assert "sleep 1" in shim


def test_agent_hcl_includes_workspace_ssh_templates():
    from vystak_provider_docker.templates import generate_agent_hcl_with_workspace_ssh

    hcl = generate_agent_hcl_with_workspace_ssh(
        vault_address="http://vystak-vault:8200",
        secret_names=["ANTHROPIC_API_KEY"],
        agent_name="assistant",
        role="agent",  # client side — renders id_ed25519 + known_hosts
    )
    # Normal secrets.env template still present
    assert "/shared/secrets.env" in hcl
    # Agent-side SSH files. Written under /shared/ssh/* (same volume used
    # by secrets.env); the agent Dockerfile symlinks /vystak/ssh →
    # /shared/ssh so agent-side code can use the /vystak/ssh/* path.
    assert "/shared/ssh/id_ed25519" in hcl
    assert "/shared/ssh/known_hosts" in hcl
    assert '0400' in hcl  # private key perms
    # Private-key template reads client-key
    assert "_vystak/workspace-ssh/assistant/client-key" in hcl
    # known_hosts reads host-key-pub
    assert "_vystak/workspace-ssh/assistant/host-key-pub" in hcl
    # Format: "vystak-assistant-workspace ssh-ed25519 ..."
    assert "vystak-assistant-workspace" in hcl


def test_workspace_hcl_includes_workspace_ssh_templates():
    from vystak_provider_docker.templates import generate_agent_hcl_with_workspace_ssh

    hcl = generate_agent_hcl_with_workspace_ssh(
        vault_address="http://vystak-vault:8200",
        secret_names=["STRIPE_API_KEY"],
        agent_name="assistant",
        role="workspace",  # server side — renders host key + authorized_keys
    )
    assert "/shared/ssh_host_ed25519_key" in hcl
    assert "/shared/authorized_keys_vystak-agent" in hcl
    assert '0600' in hcl  # host private key perms
    assert "_vystak/workspace-ssh/assistant/host-key" in hcl
    assert "_vystak/workspace-ssh/assistant/client-key-pub" in hcl
