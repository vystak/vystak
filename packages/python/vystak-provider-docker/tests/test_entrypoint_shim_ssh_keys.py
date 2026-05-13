from vystak_provider_docker.templates import generate_entrypoint_shim


def test_shim_writes_host_key_from_env_var():
    """When VYSTAK_SSH_HOST_KEY is set, shim writes /etc/ssh/ssh_host_ed25519_key."""
    shim = generate_entrypoint_shim()
    assert 'VYSTAK_SSH_HOST_KEY' in shim
    assert '/etc/ssh/ssh_host_ed25519_key' in shim
    assert 'chmod 600 /etc/ssh/ssh_host_ed25519_key' in shim
    assert 'unset VYSTAK_SSH_HOST_KEY' in shim


def test_shim_writes_authorized_keys_from_env_var():
    shim = generate_entrypoint_shim()
    assert 'VYSTAK_SSH_AUTHORIZED_KEYS' in shim
    assert '/etc/ssh/authorized_keys_vystak-agent' in shim
    assert 'chmod 444 /etc/ssh/authorized_keys_vystak-agent' in shim
    assert 'unset VYSTAK_SSH_AUTHORIZED_KEYS' in shim


def test_shim_writes_client_key_from_env_var():
    shim = generate_entrypoint_shim()
    assert 'VYSTAK_SSH_CLIENT_KEY' in shim
    assert '/vystak/ssh/id_ed25519' in shim
    assert 'chmod 600 /vystak/ssh/id_ed25519' in shim


def test_shim_writes_known_hosts_from_env_var():
    shim = generate_entrypoint_shim()
    assert 'VYSTAK_SSH_KNOWN_HOSTS_PUB' in shim
    assert '/vystak/ssh/known_hosts' in shim
