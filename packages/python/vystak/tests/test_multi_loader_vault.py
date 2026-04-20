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


def test_workspace_with_secrets_on_non_azure_platform_raises():
    data = copy.deepcopy(AZURE_ONE_AGENT_WITH_VAULT)
    data["providers"]["docker"] = {"type": "docker"}
    data["platforms"]["docker"] = {"type": "docker", "provider": "docker"}
    data["agents"][0]["platform"] = "docker"
    data["agents"][0]["workspace"] = {
        "name": "ws",
        "type": "persistent",
        "secrets": [{"name": "STRIPE_API_KEY"}],
    }
    with pytest.raises(
        ValueError, match="only supports workspace-scoped secrets on Azure"
    ):
        load_multi_yaml(data)
