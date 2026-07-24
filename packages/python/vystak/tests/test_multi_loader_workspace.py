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
            "framework": "langchain-python",
            "default_model": "sonnet",
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
                "framework": "langchain-python",
                "default_model": "sonnet",
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


ACA_WORKSPACE_CONFIG = {
    "providers": {
        "azure": {"type": "azure", "config": {"location": "eastus2"}},
        "anthropic": {"type": "anthropic"},
    },
    "platforms": {"aca": {"type": "container-apps", "provider": "azure"}},
    "vault": {
        "name": "v",
        "provider": "azure",
        "type": "key-vault",
        "mode": "deploy",
        "config": {"vault_name": "vk"},
    },
    "models": {
        "sonnet": {"provider": "anthropic", "model_name": "claude-sonnet-4-20250514"}
    },
    "agents": [
        {
            "name": "assistant",
            "framework": "langchain-python",
            "default_model": "sonnet",
            "platform": "aca",
            "secrets": [{"name": "ANTHROPIC_API_KEY"}],
            "workspace": {
                "name": "dev",
                "image": "python:3.12-slim",
                "persistence": "volume",
            },
        }
    ],
}


def test_aca_workspace_persistence_volume_loads():
    """persistence=volume is supported on ACA (Azure Files mount)."""
    data = copy.deepcopy(ACA_WORKSPACE_CONFIG)
    agents, _channels, vault = load_multi_yaml(data)
    assert vault is not None
    assert agents[0].workspace.persistence == "volume"


def test_aca_workspace_persistence_ephemeral_loads():
    """persistence=ephemeral is supported on ACA (replica ephemeral disk)."""
    data = copy.deepcopy(ACA_WORKSPACE_CONFIG)
    data["agents"][0]["workspace"]["persistence"] = "ephemeral"
    agents, _channels, _vault = load_multi_yaml(data)
    assert agents[0].workspace.persistence == "ephemeral"


def test_aca_workspace_persistence_bind_rejected():
    """persistence=bind has no meaning on ACA (no host filesystem)."""
    import pytest
    data = copy.deepcopy(ACA_WORKSPACE_CONFIG)
    data["agents"][0]["workspace"]["persistence"] = "bind"
    data["agents"][0]["workspace"]["path"] = "/tmp/x"
    with pytest.raises(ValueError, match="mode='bind'.*Container Apps"):
        load_multi_yaml(data)


def test_docker_workspace_persistence_bind_still_supported():
    """The ACA-specific rule must not regress the Docker path."""
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
        "persistence": "bind",
        "path": "/tmp/ws",
    }
    agents, _channels, _vault = load_multi_yaml(data)
    assert agents[0].workspace.persistence == "bind"
    assert agents[0].workspace.path == "/tmp/ws"


# --- volumes: section (Phase 1) -------------------------------------------

def test_named_volume_resolves_onto_workspace():
    data = copy.deepcopy(BASE_CONFIG)
    data["volumes"] = {"team-code": {"mode": "persistent"}}
    data["agents"][0]["workspace"] = {
        "name": "dev",
        "image": "python:3.12-slim",
        "volume": "team-code",
    }
    agents, _channels, _vault = load_multi_yaml(data)
    ws = agents[0].workspace
    assert ws is not None
    from vystak.schema.volume import Volume

    assert isinstance(ws.volume, Volume)
    assert ws.effective_volume.name == "team-code"


def test_unknown_volume_reference_raises():
    import pytest

    data = copy.deepcopy(BASE_CONFIG)
    data["volumes"] = {"team-code": {}}
    data["agents"][0]["workspace"] = {
        "name": "dev",
        "image": "python:3.12-slim",
        "volume": "does-not-exist",
    }
    with pytest.raises(KeyError, match="Unknown volume 'does-not-exist'"):
        load_multi_yaml(data)


def test_two_agents_share_one_volume():
    data = copy.deepcopy(BASE_CONFIG)
    data["volumes"] = {"team-code": {}}
    second = copy.deepcopy(data["agents"][0])
    second["name"] = "reviewer"
    data["agents"].append(second)
    for agent_data in data["agents"]:
        agent_data["workspace"] = {
            "name": "dev",
            "image": "python:3.12-slim",
            "volume": "team-code",
        }
    agents, _channels, _vault = load_multi_yaml(data)
    assert agents[0].workspace.effective_volume.name == "team-code"
    assert agents[1].workspace.effective_volume.name == "team-code"
    assert (
        agents[0].workspace.effective_volume
        is agents[1].workspace.effective_volume
    )


def test_bind_volume_rejected_on_container_apps():
    import pytest

    data = copy.deepcopy(BASE_CONFIG)
    data["providers"]["azure"] = {"type": "azure"}
    data["platforms"]["aca"] = {"type": "container-apps", "provider": "azure"}
    data["volumes"] = {"local-src": {"mode": "bind", "path": "~/code"}}
    data["agents"][0]["platform"] = "aca"
    data["agents"][0]["workspace"] = {
        "name": "dev",
        "image": "python:3.12-slim",
        "volume": "local-src",
    }
    with pytest.raises(ValueError, match="mode='bind'.*Container Apps"):
        load_multi_yaml(data)


def test_legacy_bind_persistence_still_rejected_on_container_apps():
    import pytest

    data = copy.deepcopy(BASE_CONFIG)
    data["providers"]["azure"] = {"type": "azure"}
    data["platforms"]["aca"] = {"type": "container-apps", "provider": "azure"}
    data["agents"][0]["platform"] = "aca"
    data["agents"][0]["workspace"] = {
        "name": "dev",
        "image": "python:3.12-slim",
        "persistence": "bind",
        "path": "/tmp/src",
    }
    with pytest.raises(ValueError, match="mode='bind'.*Container Apps"):
        load_multi_yaml(data)


def test_agent_with_volume_round_trips_through_model_dump():
    from vystak.schema import Agent

    data = copy.deepcopy(BASE_CONFIG)
    data["volumes"] = {"team-code": {}}
    data["agents"][0]["workspace"] = {
        "name": "dev",
        "image": "python:3.12-slim",
        "volume": "team-code",
    }
    agents, _channels, _vault = load_multi_yaml(data)
    revalidated = Agent.model_validate(agents[0].model_dump())
    assert revalidated.workspace.effective_volume.name == "team-code"
