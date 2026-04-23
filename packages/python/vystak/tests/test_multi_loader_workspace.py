"""Tests for workspace loading."""

import copy

from vystak.schema.multi_loader import load_multi_yaml

BASE_CONFIG = {
    "providers": {
        "docker": {"type": "docker"},
        "anthropic": {"type": "anthropic"},
    },
    "platforms": {"local": {"type": "docker", "provider": "docker"}},
    "models": {
        "sonnet": {"provider": "anthropic", "model_name": "claude-sonnet-4-20250514"}
    },
    "agents": [
        {
            "name": "assistant",
            "model": "sonnet",
            "platform": "local",
        }
    ],
}


def test_workspace_with_vault_loads():
    data = copy.deepcopy(BASE_CONFIG)
    data["vault"] = {
        "name": "v",
        "provider": "docker",
        "type": "vault",
        "mode": "deploy",
        "config": {},
    }
    data["agents"][0]["workspace"] = {
        "name": "dev",
        "image": "python:3.12-slim",
    }
    agents, _channels, vault = load_multi_yaml(data)
    assert vault is not None
    assert agents[0].workspace is not None
    assert agents[0].workspace.image == "python:3.12-slim"


def test_no_workspace_no_vault_still_loads():
    """Agents without workspaces don't require Vault."""
    agents, _channels, vault = load_multi_yaml(copy.deepcopy(BASE_CONFIG))
    assert agents[0].workspace is None
    assert vault is None


def test_workspace_secrets_on_docker_without_vault_loads():
    """Default-path delivery handles per-container isolation via --env-file.
    Vault declaration is no longer required."""
    data = {
        "providers": {"docker": {"type": "docker"}, "anthropic": {"type": "anthropic"}},
        "platforms": {"docker": {"provider": "docker", "type": "docker"}},
        "models": {"sonnet": {"provider": "anthropic", "model_name": "claude-sonnet-4-6"}},
        "agents": [
            {
                "name": "assistant",
                "model": "sonnet",
                "platform": "docker",
                "secrets": [{"name": "ANTHROPIC_API_KEY"}],
                "workspace": {
                    "name": "ws",
                    "secrets": [{"name": "STRIPE_API_KEY"}],
                },
            }
        ],
    }
    agents, channels, vault = load_multi_yaml(data)
    assert len(agents) == 1
    assert agents[0].workspace is not None
    assert [s.name for s in agents[0].workspace.secrets] == ["STRIPE_API_KEY"]
    assert vault is None
