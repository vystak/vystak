import pytest
from vystak.schema.multi_loader import load_multi_agent_yaml


class TestLoadMultiAgentYaml:
    def test_basic_multi_agent(self):
        data = {
            "providers": {
                "anthropic": {"type": "anthropic"},
                "docker": {"type": "docker"},
            },
            "platforms": {
                "local": {"type": "docker", "provider": "docker"},
            },
            "models": {
                "claude": {"provider": "anthropic", "model_name": "claude-sonnet-4-20250514"},
            },
            "agents": [
                {"name": "bot-a", "model": "claude", "platform": "local", "channels": [{"name": "api", "type": "api"}]},
                {"name": "bot-b", "model": "claude", "platform": "local", "channels": [{"name": "api", "type": "api"}]},
            ],
        }
        agents = load_multi_agent_yaml(data)
        assert len(agents) == 2
        assert agents[0].name == "bot-a"
        assert agents[1].name == "bot-b"

    def test_shared_platform_same_object(self):
        data = {
            "providers": {"docker": {"type": "docker"}},
            "platforms": {"local": {"type": "docker", "provider": "docker"}},
            "models": {"claude": {"provider": "docker", "model_name": "claude-sonnet-4-20250514"}},
            "agents": [
                {"name": "a", "model": "claude", "platform": "local", "channels": [{"name": "api", "type": "api"}]},
                {"name": "b", "model": "claude", "platform": "local", "channels": [{"name": "api", "type": "api"}]},
            ],
        }
        agents = load_multi_agent_yaml(data)
        assert agents[0].platform is agents[1].platform

    def test_shared_model_same_object(self):
        data = {
            "providers": {"anthropic": {"type": "anthropic"}},
            "platforms": {},
            "models": {"claude": {"provider": "anthropic", "model_name": "claude-sonnet-4-20250514"}},
            "agents": [
                {"name": "a", "model": "claude", "channels": [{"name": "api", "type": "api"}]},
                {"name": "b", "model": "claude", "channels": [{"name": "api", "type": "api"}]},
            ],
        }
        agents = load_multi_agent_yaml(data)
        assert agents[0].model is agents[1].model

    def test_unknown_provider_raises(self):
        data = {
            "providers": {},
            "platforms": {"local": {"type": "docker", "provider": "nonexistent"}},
            "models": {},
            "agents": [],
        }
        with pytest.raises(KeyError, match="nonexistent"):
            load_multi_agent_yaml(data)

    def test_unknown_model_raises(self):
        data = {
            "providers": {"anthropic": {"type": "anthropic"}},
            "platforms": {},
            "models": {},
            "agents": [{"name": "a", "model": "nonexistent", "channels": [{"name": "api", "type": "api"}]}],
        }
        with pytest.raises(KeyError, match="nonexistent"):
            load_multi_agent_yaml(data)

    def test_provider_with_config(self):
        data = {
            "providers": {"azure": {"type": "azure", "config": {"location": "eastus2", "resource_group": "my-rg"}}},
            "platforms": {"aca": {"type": "container-apps", "provider": "azure"}},
            "models": {"claude": {"provider": "azure", "model_name": "claude-sonnet-4-20250514"}},
            "agents": [{"name": "bot", "model": "claude", "platform": "aca", "channels": [{"name": "api", "type": "api"}]}],
        }
        agents = load_multi_agent_yaml(data)
        assert agents[0].platform.provider.config["location"] == "eastus2"

    def test_inline_model_still_works(self):
        data = {
            "providers": {}, "platforms": {}, "models": {},
            "agents": [{
                "name": "bot",
                "model": {"name": "claude", "provider": {"name": "anthropic", "type": "anthropic"}, "model_name": "claude-sonnet-4-20250514"},
                "channels": [{"name": "api", "type": "api"}],
            }],
        }
        agents = load_multi_agent_yaml(data)
        assert agents[0].model.model_name == "claude-sonnet-4-20250514"

    def test_empty_agents_returns_empty(self):
        data = {"providers": {}, "platforms": {}, "models": {}, "agents": []}
        assert load_multi_agent_yaml(data) == []
