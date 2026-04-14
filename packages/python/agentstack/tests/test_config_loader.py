import pytest
import yaml
from pathlib import Path

from agentstack.schema.config_loader import load_base_config, merge_configs, resolve_env_file


class TestMergeConfigs:
    def test_simple_merge(self):
        base = {"providers": {"azure": {"type": "azure"}}}
        override = {"providers": {"azure": {"config": {"location": "eastus2"}}}}
        result = merge_configs(base, override)
        assert result["providers"]["azure"]["type"] == "azure"
        assert result["providers"]["azure"]["config"]["location"] == "eastus2"

    def test_deep_merge(self):
        base = {"providers": {"azure": {"type": "azure", "config": {"location": "eastus2"}}}}
        override = {"providers": {"azure": {"config": {"resource_group": "my-rg"}}}}
        result = merge_configs(base, override)
        assert result["providers"]["azure"]["config"]["location"] == "eastus2"
        assert result["providers"]["azure"]["config"]["resource_group"] == "my-rg"

    def test_override_wins(self):
        base = {"providers": {"azure": {"config": {"location": "eastus2"}}}}
        override = {"providers": {"azure": {"config": {"location": "westus2"}}}}
        result = merge_configs(base, override)
        assert result["providers"]["azure"]["config"]["location"] == "westus2"

    def test_add_new_keys(self):
        base = {"providers": {"azure": {"type": "azure"}}}
        override = {"providers": {"docker": {"type": "docker"}}}
        result = merge_configs(base, override)
        assert "azure" in result["providers"]
        assert "docker" in result["providers"]

    def test_empty_override(self):
        base = {"providers": {"azure": {"type": "azure"}}}
        result = merge_configs(base, {})
        assert result == base

    def test_empty_base(self):
        override = {"providers": {"azure": {"type": "azure"}}}
        result = merge_configs({}, override)
        assert result == override


class TestResolveEnvFile:
    def test_default_env(self, tmp_path):
        (tmp_path / "agentstack.env.yaml").write_text("providers: {}")
        result = resolve_env_file(tmp_path, env=None)
        assert result == tmp_path / "agentstack.env.yaml"

    def test_named_env(self, tmp_path):
        (tmp_path / "agentstack.env.prod.yaml").write_text("providers: {}")
        result = resolve_env_file(tmp_path, env="prod")
        assert result == tmp_path / "agentstack.env.prod.yaml"

    def test_no_env_file_returns_none(self, tmp_path):
        result = resolve_env_file(tmp_path, env=None)
        assert result is None

    def test_missing_named_env_returns_none(self, tmp_path):
        result = resolve_env_file(tmp_path, env="staging")
        assert result is None


class TestLoadBaseConfig:
    def test_loads_base_and_env(self, tmp_path):
        base = {"providers": {"azure": {"type": "azure"}}}
        env = {"providers": {"azure": {"config": {"location": "eastus2"}}}}
        (tmp_path / "agentstack.base.yaml").write_text(yaml.dump(base))
        (tmp_path / "agentstack.env.yaml").write_text(yaml.dump(env))
        result = load_base_config(tmp_path)
        assert result["providers"]["azure"]["type"] == "azure"
        assert result["providers"]["azure"]["config"]["location"] == "eastus2"

    def test_base_only(self, tmp_path):
        base = {"providers": {"azure": {"type": "azure"}}}
        (tmp_path / "agentstack.base.yaml").write_text(yaml.dump(base))
        result = load_base_config(tmp_path)
        assert result["providers"]["azure"]["type"] == "azure"

    def test_no_base_returns_empty(self, tmp_path):
        result = load_base_config(tmp_path)
        assert result == {}

    def test_env_override(self, tmp_path, monkeypatch):
        base = {"providers": {"azure": {"type": "azure", "config": {"location": "eastus2"}}}}
        prod = {"providers": {"azure": {"config": {"location": "westus2"}}}}
        (tmp_path / "agentstack.base.yaml").write_text(yaml.dump(base))
        (tmp_path / "agentstack.env.prod.yaml").write_text(yaml.dump(prod))
        monkeypatch.setenv("AGENTSTACK_ENV", "prod")
        result = load_base_config(tmp_path)
        assert result["providers"]["azure"]["config"]["location"] == "westus2"
