import copy

import pytest
from vystak.schema.multi_loader import load_multi_yaml

AZURE_ONE_AGENT_WITH_VAULT = {
    "providers": {
        "azure": {"type": "azure", "config": {"resource_group": "rg"}},
        "anthropic": {"type": "anthropic"},
    },
    "platforms": {
        "aca": {"type": "container-apps", "provider": "azure"},
    },
    "vault": {
        "name": "vystak-vault",
        "provider": "azure",
        "mode": "deploy",
        "config": {"vault_name": "vystak-vault"},
    },
    "models": {
        "sonnet": {"provider": "anthropic", "model_name": "claude-sonnet-4-6"},
    },
    "agents": [
        {
            "name": "assistant",
            "model": "sonnet",
            "secrets": [{"name": "ANTHROPIC_API_KEY"}],
            "platform": "aca",
        },
    ],
}


def test_vault_loaded_from_yaml():
    agents, channels, vault = load_multi_yaml(copy.deepcopy(AZURE_ONE_AGENT_WITH_VAULT))
    assert vault is not None
    assert vault.name == "vystak-vault"
    assert vault.config["vault_name"] == "vystak-vault"
    assert vault.provider.name == "azure"


def test_no_vault_key_yields_none():
    data = copy.deepcopy(AZURE_ONE_AGENT_WITH_VAULT)
    data.pop("vault")
    agents, channels, vault = load_multi_yaml(data)
    assert vault is None


def test_vault_references_unknown_provider_raises():
    data = copy.deepcopy(AZURE_ONE_AGENT_WITH_VAULT)
    data["vault"] = {"name": "v", "provider": "nope", "mode": "deploy"}
    with pytest.raises(KeyError, match="Unknown provider 'nope' in vault"):
        load_multi_yaml(data)


def test_workspace_with_secrets_on_docker_with_hashi_vault_loads():
    """Docker platform + workspace secrets + HashiCorp Vault = valid."""
    data = copy.deepcopy(AZURE_ONE_AGENT_WITH_VAULT)
    data["providers"]["docker"] = {"type": "docker"}
    data["platforms"]["docker"] = {"type": "docker", "provider": "docker"}
    data["vault"] = {
        "name": "vystak-vault",
        "provider": "docker",
        "type": "vault",
        "mode": "deploy",
        "config": {},
    }
    data["agents"][0]["platform"] = "docker"
    data["agents"][0]["workspace"] = {
        "name": "ws",
        "type": "persistent",
        "secrets": [{"name": "STRIPE_API_KEY"}],
    }
    agents, _channels, vault = load_multi_yaml(data)
    assert vault is not None and vault.type.value == "vault"
    assert agents[0].workspace.secrets[0].name == "STRIPE_API_KEY"


def test_vault_type_vault_requires_docker_provider():
    data = copy.deepcopy(AZURE_ONE_AGENT_WITH_VAULT)
    data["vault"] = {
        "name": "v",
        "provider": "azure",
        "mode": "deploy",
        "type": "vault",   # hashi type with azure provider = error
        "config": {"image": "hashicorp/vault:1.17"},
    }
    with pytest.raises(ValueError, match="type='vault' requires provider.type='docker'"):
        load_multi_yaml(data)


def test_vault_type_key_vault_requires_azure_provider():
    data = copy.deepcopy(AZURE_ONE_AGENT_WITH_VAULT)
    data["providers"]["docker"] = {"type": "docker"}
    data["vault"] = {
        "name": "v",
        "provider": "docker",
        "mode": "deploy",
        "type": "key-vault",  # azure type with docker provider = error
        "config": {"vault_name": "v"},
    }
    with pytest.raises(ValueError, match="type='key-vault' requires provider.type='azure'"):
        load_multi_yaml(data)


def test_hashi_vault_valid_pairing_loads():
    data = {
        "providers": {"docker": {"type": "docker"}, "anthropic": {"type": "anthropic"}},
        "platforms": {"local": {"type": "docker", "provider": "docker"}},
        "vault": {
            "name": "v",
            "provider": "docker",
            "mode": "deploy",
            "type": "vault",
            "config": {},
        },
        "models": {"sonnet": {"provider": "anthropic", "model_name": "claude-sonnet-4-20250514"}},
        "agents": [
            {"name": "a", "model": "sonnet", "platform": "local",
             "secrets": [{"name": "ANTHROPIC_API_KEY"}]},
        ],
    }
    agents, channels, vault = load_multi_yaml(data)
    assert vault is not None
    assert vault.type.value == "vault"
    assert vault.provider.type == "docker"
