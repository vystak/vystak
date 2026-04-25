import pytest
from vystak.schema.common import ChannelType
from vystak.schema.multi_loader import load_multi_yaml


class TestLoadMultiYaml:
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
                {"name": "bot-a", "model": "claude", "platform": "local"},
                {"name": "bot-b", "model": "claude", "platform": "local"},
            ],
        }
        agents, channels, _ = load_multi_yaml(data)
        assert len(agents) == 2
        assert agents[0].name == "bot-a"
        assert agents[1].name == "bot-b"
        assert channels == []

    def test_shared_platform_same_object(self):
        data = {
            "providers": {"docker": {"type": "docker"}},
            "platforms": {"local": {"type": "docker", "provider": "docker"}},
            "models": {"claude": {"provider": "docker", "model_name": "claude-sonnet-4-20250514"}},
            "agents": [
                {"name": "a", "model": "claude", "platform": "local"},
                {"name": "b", "model": "claude", "platform": "local"},
            ],
        }
        agents, _channels, _vault = load_multi_yaml(data)
        assert agents[0].platform is agents[1].platform

    def test_shared_model_same_object(self):
        data = {
            "providers": {"anthropic": {"type": "anthropic"}},
            "platforms": {},
            "models": {
                "claude": {"provider": "anthropic", "model_name": "claude-sonnet-4-20250514"}
            },
            "agents": [
                {"name": "a", "model": "claude"},
                {"name": "b", "model": "claude"},
            ],
        }
        agents, _channels, _vault = load_multi_yaml(data)
        assert agents[0].model is agents[1].model

    def test_unknown_provider_raises(self):
        data = {
            "providers": {},
            "platforms": {"local": {"type": "docker", "provider": "nonexistent"}},
            "models": {},
            "agents": [],
        }
        with pytest.raises(KeyError, match="nonexistent"):
            load_multi_yaml(data)

    def test_unknown_model_raises(self):
        data = {
            "providers": {"anthropic": {"type": "anthropic"}},
            "platforms": {},
            "models": {},
            "agents": [{"name": "a", "model": "nonexistent"}],
        }
        with pytest.raises(KeyError, match="nonexistent"):
            load_multi_yaml(data)

    def test_provider_with_config(self):
        data = {
            "providers": {
                "azure": {
                    "type": "azure",
                    "config": {"location": "eastus2", "resource_group": "my-rg"},
                }
            },
            "platforms": {"aca": {"type": "container-apps", "provider": "azure"}},
            "models": {"claude": {"provider": "azure", "model_name": "claude-sonnet-4-20250514"}},
            "agents": [{"name": "bot", "model": "claude", "platform": "aca"}],
        }
        agents, _channels, _vault = load_multi_yaml(data)
        assert agents[0].platform.provider.config["location"] == "eastus2"

    def test_inline_model_still_works(self):
        data = {
            "providers": {},
            "platforms": {},
            "models": {},
            "agents": [
                {
                    "name": "bot",
                    "model": {
                        "name": "claude",
                        "provider": {"name": "anthropic", "type": "anthropic"},
                        "model_name": "claude-sonnet-4-20250514",
                    },
                }
            ],
        }
        agents, _channels, _vault = load_multi_yaml(data)
        assert agents[0].model.model_name == "claude-sonnet-4-20250514"

    def test_empty_returns_empty(self):
        data = {"providers": {}, "platforms": {}, "models": {}, "agents": []}
        agents, channels, vault = load_multi_yaml(data)
        assert agents == []
        assert channels == []
        assert vault is None


class TestLoadMultiYamlChannels:
    def test_basic_channel(self):
        data = {
            "providers": {"docker": {"type": "docker"}},
            "platforms": {
                "local": {"type": "docker", "provider": "docker", "namespace": "prod"},
            },
            "models": {},
            "agents": [],
            "channels": [
                {
                    "name": "slack-main",
                    "type": "slack",
                    "platform": "local",
                    "config": {"bot_token_secret": "SLACK_TOKEN"},
                },
            ],
        }
        _agents, channels, _vault = load_multi_yaml(data)
        assert len(channels) == 1
        ch = channels[0]
        assert ch.name == "slack-main"
        assert ch.type == ChannelType.SLACK
        assert ch.platform.namespace == "prod"
        assert ch.canonical_name == "slack-main.channels.prod"

    def test_unknown_platform_raises(self):
        data = {
            "providers": {},
            "platforms": {},
            "models": {},
            "agents": [],
            "channels": [
                {"name": "x", "type": "api", "platform": "nonexistent"},
            ],
        }
        with pytest.raises(KeyError, match="nonexistent"):
            load_multi_yaml(data)

    def test_channel_and_agents_share_platform(self):
        data = {
            "providers": {"docker": {"type": "docker"}, "anthropic": {"type": "anthropic"}},
            "platforms": {"local": {"type": "docker", "provider": "docker"}},
            "models": {
                "claude": {"provider": "anthropic", "model_name": "claude-sonnet-4-20250514"}
            },
            "agents": [{"name": "bot", "model": "claude", "platform": "local"}],
            "channels": [
                {"name": "api", "type": "api", "platform": "local"},
            ],
        }
        agents, channels, _vault = load_multi_yaml(data)
        assert agents[0].platform is channels[0].platform
