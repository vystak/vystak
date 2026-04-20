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
