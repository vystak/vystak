# Multi-Agent Loader + CLI — Phase A Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Load multiple agents from a single Python/YAML file or multiple files, with YAML named references, base+env conventions, and platform fingerprint grouping.

**Architecture:** New `load_agents` function handles multi-agent YAML (named refs), Python (all Agent instances), and multi-file merging. New orchestrator groups agents by platform fingerprint and dispatches per-group provisioning. CLI `apply`/`destroy`/`status`/`plan` updated for multi-agent.

**Tech Stack:** Python 3.11+, Pydantic v2, PyYAML, Click, pytest

---

### Task 1: Multi-agent YAML loader with named references

**Files:**
- Create: `packages/python/agentstack/src/agentstack/schema/multi_loader.py`
- Create: `packages/python/agentstack/tests/test_multi_loader.py`

- [ ] **Step 1: Write failing tests**

```python
# packages/python/agentstack/tests/test_multi_loader.py
import pytest
import yaml

from agentstack.schema.agent import Agent
from agentstack.schema.multi_loader import load_multi_agent_yaml


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
                "claude": {
                    "provider": "anthropic",
                    "model_name": "claude-sonnet-4-20250514",
                },
            },
            "agents": [
                {
                    "name": "bot-a",
                    "model": "claude",
                    "platform": "local",
                    "channels": [{"name": "api", "type": "api"}],
                },
                {
                    "name": "bot-b",
                    "model": "claude",
                    "platform": "local",
                    "channels": [{"name": "api", "type": "api"}],
                },
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
            "models": {
                "claude": {
                    "provider": "docker",
                    "model_name": "claude-sonnet-4-20250514",
                },
            },
            "agents": [
                {"name": "a", "model": "claude", "platform": "local",
                 "channels": [{"name": "api", "type": "api"}]},
                {"name": "b", "model": "claude", "platform": "local",
                 "channels": [{"name": "api", "type": "api"}]},
            ],
        }
        agents = load_multi_agent_yaml(data)
        # Same platform name → same Python object
        assert agents[0].platform is agents[1].platform

    def test_shared_model_same_object(self):
        data = {
            "providers": {"anthropic": {"type": "anthropic"}},
            "platforms": {},
            "models": {
                "claude": {
                    "provider": "anthropic",
                    "model_name": "claude-sonnet-4-20250514",
                },
            },
            "agents": [
                {"name": "a", "model": "claude",
                 "channels": [{"name": "api", "type": "api"}]},
                {"name": "b", "model": "claude",
                 "channels": [{"name": "api", "type": "api"}]},
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
            "agents": [
                {"name": "a", "model": "nonexistent",
                 "channels": [{"name": "api", "type": "api"}]},
            ],
        }
        with pytest.raises(KeyError, match="nonexistent"):
            load_multi_agent_yaml(data)

    def test_provider_with_config(self):
        data = {
            "providers": {
                "azure": {
                    "type": "azure",
                    "config": {"location": "eastus2", "resource_group": "my-rg"},
                },
            },
            "platforms": {
                "aca": {"type": "container-apps", "provider": "azure"},
            },
            "models": {
                "claude": {
                    "provider": "azure",
                    "model_name": "claude-sonnet-4-20250514",
                },
            },
            "agents": [
                {"name": "bot", "model": "claude", "platform": "aca",
                 "channels": [{"name": "api", "type": "api"}]},
            ],
        }
        agents = load_multi_agent_yaml(data)
        assert agents[0].platform.provider.config["location"] == "eastus2"

    def test_inline_model_still_works(self):
        """Agents can still use inline model objects instead of string refs."""
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
                    "channels": [{"name": "api", "type": "api"}],
                },
            ],
        }
        agents = load_multi_agent_yaml(data)
        assert agents[0].name == "bot"
        assert agents[0].model.model_name == "claude-sonnet-4-20250514"

    def test_empty_agents_returns_empty(self):
        data = {"providers": {}, "platforms": {}, "models": {}, "agents": []}
        agents = load_multi_agent_yaml(data)
        assert agents == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/python/agentstack/tests/test_multi_loader.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement multi_loader.py**

```python
# packages/python/agentstack/src/agentstack/schema/multi_loader.py
"""Multi-agent YAML loader with named references."""

from agentstack.schema.agent import Agent
from agentstack.schema.model import Model
from agentstack.schema.platform import Platform
from agentstack.schema.provider import Provider


def load_multi_agent_yaml(data: dict) -> list[Agent]:
    """Load multi-agent YAML with named providers, platforms, and models.

    String references in agents are resolved to shared Python objects,
    so agents referencing the same platform name get the same object (id).
    """
    # 1. Providers
    providers: dict[str, Provider] = {}
    for name, cfg in data.get("providers", {}).items():
        providers[name] = Provider(name=name, **cfg)

    # 2. Platforms — resolve provider string ref
    platforms: dict[str, Platform] = {}
    for name, cfg in data.get("platforms", {}).items():
        cfg = dict(cfg)
        provider_ref = cfg.pop("provider")
        if provider_ref not in providers:
            raise KeyError(
                f"Unknown provider '{provider_ref}' in platform '{name}'. "
                f"Defined providers: {', '.join(providers.keys())}"
            )
        platforms[name] = Platform(name=name, provider=providers[provider_ref], **cfg)

    # 3. Models — resolve provider string ref
    models: dict[str, Model] = {}
    for name, cfg in data.get("models", {}).items():
        cfg = dict(cfg)
        provider_ref = cfg.pop("provider")
        if provider_ref not in providers:
            raise KeyError(
                f"Unknown provider '{provider_ref}' in model '{name}'. "
                f"Defined providers: {', '.join(providers.keys())}"
            )
        models[name] = Model(name=name, provider=providers[provider_ref], **cfg)

    # 4. Agents — resolve string refs to shared objects
    agents: list[Agent] = []
    for agent_data in data.get("agents", []):
        agent_data = dict(agent_data)

        # Resolve model reference
        model_ref = agent_data.get("model")
        if isinstance(model_ref, str):
            if model_ref not in models:
                raise KeyError(
                    f"Unknown model '{model_ref}' in agent '{agent_data.get('name')}'. "
                    f"Defined models: {', '.join(models.keys())}"
                )
            agent_data["model"] = models[model_ref]

        # Resolve platform reference
        platform_ref = agent_data.get("platform")
        if isinstance(platform_ref, str):
            if platform_ref not in platforms:
                raise KeyError(
                    f"Unknown platform '{platform_ref}' in agent '{agent_data.get('name')}'. "
                    f"Defined platforms: {', '.join(platforms.keys())}"
                )
            agent_data["platform"] = platforms[platform_ref]

        agents.append(Agent.model_validate(agent_data))

    return agents
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest packages/python/agentstack/tests/test_multi_loader.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add packages/python/agentstack/src/agentstack/schema/multi_loader.py packages/python/agentstack/tests/test_multi_loader.py
git commit -m "feat: add multi-agent YAML loader with named references"
```

---

### Task 2: Base + env file loading conventions

**Files:**
- Create: `packages/python/agentstack/src/agentstack/schema/config_loader.py`
- Create: `packages/python/agentstack/tests/test_config_loader.py`

- [ ] **Step 1: Write failing tests**

```python
# packages/python/agentstack/tests/test_config_loader.py
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
        assert result["providers"]["azure"]["type"] == "azure"
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/python/agentstack/tests/test_config_loader.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement config_loader.py**

```python
# packages/python/agentstack/src/agentstack/schema/config_loader.py
"""Base + env config loading with deep merge."""

import os
from pathlib import Path

import yaml


def merge_configs(base: dict, override: dict) -> dict:
    """Deep merge override into base. Override values win for leaf keys."""
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = merge_configs(result[key], value)
        else:
            result[key] = value
    return result


def resolve_env_file(directory: Path, env: str | None = None) -> Path | None:
    """Find the env config file by convention."""
    if env is None:
        env = os.environ.get("AGENTSTACK_ENV")

    if env:
        path = directory / f"agentstack.env.{env}.yaml"
    else:
        path = directory / "agentstack.env.yaml"

    return path if path.exists() else None


def load_base_config(directory: Path) -> dict:
    """Load agentstack.base.yaml + agentstack.env[.name].yaml, merged."""
    base_path = directory / "agentstack.base.yaml"
    if not base_path.exists():
        return {}

    base = yaml.safe_load(base_path.read_text()) or {}

    env_path = resolve_env_file(directory)
    if env_path:
        env_data = yaml.safe_load(env_path.read_text()) or {}
        base = merge_configs(base, env_data)

    return base
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest packages/python/agentstack/tests/test_config_loader.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add packages/python/agentstack/src/agentstack/schema/config_loader.py packages/python/agentstack/tests/test_config_loader.py
git commit -m "feat: add base + env config loading with deep merge"
```

---

### Task 3: Python multi-agent loader + unified load_agents

**Files:**
- Modify: `packages/python/agentstack-cli/src/agentstack_cli/loader.py`
- Modify: `packages/python/agentstack-cli/tests/test_loader.py`

- [ ] **Step 1: Write failing tests for load_agents**

Add to `packages/python/agentstack-cli/tests/test_loader.py`:

```python
from agentstack_cli.loader import load_agents


class TestLoadAgents:
    def test_single_agent_yaml(self, tmp_path, sample_agent_yaml):
        path = tmp_path / "agent.yaml"
        path.write_text(yaml.dump(sample_agent_yaml))
        agents = load_agents([path])
        assert len(agents) == 1
        assert agents[0].name == "test-bot"

    def test_multi_agent_yaml(self, tmp_path):
        data = {
            "providers": {"anthropic": {"type": "anthropic"}},
            "platforms": {},
            "models": {
                "claude": {"provider": "anthropic", "model_name": "claude-sonnet-4-20250514"},
            },
            "agents": [
                {"name": "a", "model": "claude", "channels": [{"name": "api", "type": "api"}]},
                {"name": "b", "model": "claude", "channels": [{"name": "api", "type": "api"}]},
            ],
        }
        path = tmp_path / "agentstack.yaml"
        path.write_text(yaml.dump(data))
        agents = load_agents([path])
        assert len(agents) == 2
        assert agents[0].name == "a"
        assert agents[1].name == "b"

    def test_python_multi_agent(self, tmp_path):
        path = tmp_path / "agentstack.py"
        path.write_text("""\
from agentstack.schema.agent import Agent
from agentstack.schema.model import Model
from agentstack.schema.provider import Provider

anthropic = Provider(name="anthropic", type="anthropic")
model = Model(name="claude", provider=anthropic, model_name="claude-sonnet-4-20250514")
bot_a = Agent(name="bot-a", model=model)
bot_b = Agent(name="bot-b", model=model)
""")
        agents = load_agents([path])
        assert len(agents) == 2
        names = {a.name for a in agents}
        assert names == {"bot-a", "bot-b"}

    def test_multiple_yaml_files(self, tmp_path):
        for name in ("a", "b"):
            data = {
                "name": f"bot-{name}",
                "model": {
                    "name": "claude",
                    "provider": {"name": "anthropic", "type": "anthropic"},
                    "model_name": "claude-sonnet-4-20250514",
                },
            }
            (tmp_path / f"{name}.yaml").write_text(yaml.dump(data))

        agents = load_agents([tmp_path / "a.yaml", tmp_path / "b.yaml"])
        assert len(agents) == 2
        names = {a.name for a in agents}
        assert names == {"bot-a", "bot-b"}

    def test_directory_path_finds_yaml(self, tmp_path):
        subdir = tmp_path / "weather"
        subdir.mkdir()
        data = {
            "name": "weather-bot",
            "model": {
                "name": "claude",
                "provider": {"name": "anthropic", "type": "anthropic"},
                "model_name": "claude-sonnet-4-20250514",
            },
        }
        (subdir / "agentstack.yaml").write_text(yaml.dump(data))
        agents = load_agents([subdir])
        assert len(agents) == 1
        assert agents[0].name == "weather-bot"

    def test_base_config_merged(self, tmp_path):
        base = {
            "providers": {
                "azure": {"type": "azure", "config": {"location": "eastus2"}},
                "anthropic": {"type": "anthropic"},
            },
            "platforms": {"aca": {"type": "container-apps", "provider": "azure"}},
            "models": {"claude": {"provider": "anthropic", "model_name": "claude-sonnet-4-20250514"}},
        }
        (tmp_path / "agentstack.base.yaml").write_text(yaml.dump(base))

        agent_data = {
            "name": "bot",
            "model": "claude",
            "platform": "aca",
            "channels": [{"name": "api", "type": "api"}],
        }
        subdir = tmp_path / "bot"
        subdir.mkdir()
        (subdir / "agentstack.yaml").write_text(yaml.dump(agent_data))

        agents = load_agents([subdir], base_dir=tmp_path)
        assert len(agents) == 1
        assert agents[0].platform.provider.config["location"] == "eastus2"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/python/agentstack-cli/tests/test_loader.py::TestLoadAgents -v`
Expected: FAIL — `cannot import name 'load_agents'`

- [ ] **Step 3: Implement load_agents in loader.py**

Add to `packages/python/agentstack-cli/src/agentstack_cli/loader.py`:

```python
import yaml
from agentstack.schema.config_loader import load_base_config, merge_configs
from agentstack.schema.multi_loader import load_multi_agent_yaml


def load_agents(paths: list[Path], base_dir: Path | None = None) -> list[Agent]:
    """Load agents from one or more files/directories.

    Handles:
    - Single YAML with agents: list → multi-agent
    - Single YAML with name: field → single agent
    - Single Python file → all Agent instances
    - Multiple files/directories → agents from each, merged
    - Base + env config → merged into multi-agent YAML refs
    """
    # Load base config if available
    if base_dir is None:
        # Try to find base in the parent of the first path
        if paths and paths[0].is_dir():
            base_dir = paths[0].parent
        elif paths:
            base_dir = paths[0].parent
    base_config = load_base_config(base_dir) if base_dir else {}

    all_agents: list[Agent] = []

    for path in paths:
        path = Path(path)

        # If path is a directory, look for convention files inside it
        if path.is_dir():
            found = None
            for conv in CONVENTION_FILES:
                candidate = path / conv
                if candidate.exists():
                    found = candidate
                    break
            if found is None:
                raise FileNotFoundError(f"No agent definition found in {path}")
            path = found

        if path.suffix in (".yaml", ".yml"):
            data = yaml.safe_load(path.read_text()) or {}

            if "agents" in data:
                # Multi-agent YAML — merge with base config
                merged = merge_configs(base_config, data) if base_config else data
                all_agents.extend(load_multi_agent_yaml(merged))
            elif isinstance(data.get("model"), str) or isinstance(data.get("platform"), str):
                # Single agent YAML with string refs — needs base config
                merged = dict(base_config)
                if "agents" not in merged:
                    merged["agents"] = []
                merged["agents"].append(data)
                all_agents.extend(load_multi_agent_yaml(merged))
            else:
                # Legacy single agent YAML with inline objects
                all_agents.append(load_agent(path))

        elif path.suffix == ".py":
            agents = _load_agents_from_python(path)
            all_agents.extend(agents)

        else:
            raise ValueError(f"Unsupported file type: {path.suffix}")

    return all_agents


def _load_agents_from_python(path: Path) -> list[Agent]:
    """Load all Agent instances from a Python file."""
    spec = importlib.util.spec_from_file_location("_agentstack_def", str(path))
    module = importlib.util.module_from_spec(spec)
    sys.modules["_agentstack_def"] = module

    file_dir = str(path.parent.resolve())
    removed = file_dir in sys.path
    if removed:
        sys.path.remove(file_dir)
    try:
        spec.loader.exec_module(module)
    finally:
        if removed:
            sys.path.insert(0, file_dir)
    del sys.modules["_agentstack_def"]

    agents = []
    for name in dir(module):
        if name.startswith("_"):
            continue
        obj = getattr(module, name)
        if isinstance(obj, Agent):
            agents.append(obj)

    # Backward compat: if no agents found but `agent` var exists
    if not agents and hasattr(module, "agent") and isinstance(module.agent, Agent):
        agents.append(module.agent)

    if not agents:
        raise ValueError(f"No Agent instances found in {path}")

    return agents
```

Also add the `yaml` import at the top of the file (after the existing imports).

- [ ] **Step 4: Run tests**

Run: `uv run pytest packages/python/agentstack-cli/tests/test_loader.py -v`
Expected: All PASS (old and new tests)

- [ ] **Step 5: Commit**

```bash
git add packages/python/agentstack-cli/src/agentstack_cli/loader.py packages/python/agentstack-cli/tests/test_loader.py
git commit -m "feat: add load_agents for multi-agent Python and YAML loading"
```

---

### Task 4: Platform fingerprint grouping

**Files:**
- Create: `packages/python/agentstack/src/agentstack/provisioning/grouping.py`
- Create: `packages/python/agentstack/tests/test_grouping.py`

- [ ] **Step 1: Write failing tests**

```python
# packages/python/agentstack/tests/test_grouping.py
import pytest

from agentstack.provisioning.grouping import group_agents_by_platform, platform_fingerprint
from agentstack.schema.agent import Agent
from agentstack.schema.model import Model
from agentstack.schema.platform import Platform
from agentstack.schema.provider import Provider


@pytest.fixture()
def model():
    anthropic = Provider(name="anthropic", type="anthropic")
    return Model(name="claude", provider=anthropic, model_name="claude-sonnet-4-20250514")


class TestPlatformFingerprint:
    def test_same_platform_object_same_fingerprint(self, model):
        docker = Provider(name="docker", type="docker")
        platform = Platform(name="local", type="docker", provider=docker)
        a = Agent(name="a", model=model, platform=platform)
        b = Agent(name="b", model=model, platform=platform)
        assert platform_fingerprint(a) == platform_fingerprint(b)

    def test_same_config_same_fingerprint(self, model):
        p1 = Platform(name="aca", type="container-apps",
                       provider=Provider(name="azure", type="azure", config={"location": "eastus2"}))
        p2 = Platform(name="aca", type="container-apps",
                       provider=Provider(name="azure", type="azure", config={"location": "eastus2"}))
        a = Agent(name="a", model=model, platform=p1)
        b = Agent(name="b", model=model, platform=p2)
        assert platform_fingerprint(a) == platform_fingerprint(b)

    def test_different_config_different_fingerprint(self, model):
        p1 = Platform(name="aca", type="container-apps",
                       provider=Provider(name="azure", type="azure", config={"location": "eastus2"}))
        p2 = Platform(name="aca", type="container-apps",
                       provider=Provider(name="azure", type="azure", config={"location": "westus2"}))
        a = Agent(name="a", model=model, platform=p1)
        b = Agent(name="b", model=model, platform=p2)
        assert platform_fingerprint(a) != platform_fingerprint(b)

    def test_no_platform_default(self, model):
        a = Agent(name="a", model=model)
        assert platform_fingerprint(a) == "docker:default"

    def test_different_provider_type(self, model):
        p1 = Platform(name="a", type="docker", provider=Provider(name="docker", type="docker"))
        p2 = Platform(name="b", type="container-apps", provider=Provider(name="azure", type="azure"))
        a = Agent(name="a", model=model, platform=p1)
        b = Agent(name="b", model=model, platform=p2)
        assert platform_fingerprint(a) != platform_fingerprint(b)


class TestGroupAgentsByPlatform:
    def test_single_group(self, model):
        platform = Platform(name="local", type="docker",
                            provider=Provider(name="docker", type="docker"))
        agents = [
            Agent(name="a", model=model, platform=platform),
            Agent(name="b", model=model, platform=platform),
        ]
        groups = group_agents_by_platform(agents)
        assert len(groups) == 1
        assert len(list(groups.values())[0]) == 2

    def test_two_groups(self, model):
        docker = Platform(name="local", type="docker",
                          provider=Provider(name="docker", type="docker"))
        azure = Platform(name="aca", type="container-apps",
                         provider=Provider(name="azure", type="azure"))
        agents = [
            Agent(name="a", model=model, platform=docker),
            Agent(name="b", model=model, platform=azure),
        ]
        groups = group_agents_by_platform(agents)
        assert len(groups) == 2

    def test_empty_list(self):
        groups = group_agents_by_platform([])
        assert groups == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/python/agentstack/tests/test_grouping.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement grouping.py**

```python
# packages/python/agentstack/src/agentstack/provisioning/grouping.py
"""Group agents by platform fingerprint for shared infrastructure."""

import hashlib
import json

from agentstack.schema.agent import Agent


def platform_fingerprint(agent: Agent) -> str:
    """Compute a dedup key from the agent's provider + platform config."""
    if agent.platform is None:
        return "docker:default"
    key = {
        "provider_type": agent.platform.provider.type,
        "provider_config": agent.platform.provider.config,
        "platform_type": agent.platform.type,
    }
    canonical = json.dumps(key, sort_keys=True, default=str)
    return hashlib.md5(canonical.encode()).hexdigest()


def group_agents_by_platform(agents: list[Agent]) -> dict[str, list[Agent]]:
    """Group agents by platform fingerprint. Returns {fingerprint: [agents]}."""
    groups: dict[str, list[Agent]] = {}
    for agent in agents:
        fp = platform_fingerprint(agent)
        groups.setdefault(fp, []).append(agent)
    return groups
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest packages/python/agentstack/tests/test_grouping.py -v`
Expected: All PASS

- [ ] **Step 5: Update provisioning __init__.py exports**

Add to `packages/python/agentstack/src/agentstack/provisioning/__init__.py`:

```python
from agentstack.provisioning.grouping import group_agents_by_platform, platform_fingerprint
```

Add to `__all__`:
```python
"group_agents_by_platform", "platform_fingerprint",
```

- [ ] **Step 6: Commit**

```bash
git add packages/python/agentstack/src/agentstack/provisioning/grouping.py packages/python/agentstack/tests/test_grouping.py packages/python/agentstack/src/agentstack/provisioning/__init__.py
git commit -m "feat: add platform fingerprint grouping for multi-agent deploy"
```

---

### Task 5: Update CLI apply for multi-agent

**Files:**
- Modify: `packages/python/agentstack-cli/src/agentstack_cli/commands/apply.py`

- [ ] **Step 1: Rewrite apply command for multi-agent**

```python
# packages/python/agentstack-cli/src/agentstack_cli/commands/apply.py
"""agentstack apply — deploy or update agents."""

from pathlib import Path

import click

from agentstack.hash import hash_agent
from agentstack.provisioning.grouping import group_agents_by_platform
from agentstack_adapter_langchain import LangChainAdapter
from agentstack_cli.loader import find_agent_file, load_agents
from agentstack_cli.provider_factory import get_provider


@click.command()
@click.argument("files", nargs=-1, type=click.Path(exists=True))
@click.option("--file", "file_path", default=None, help="Path to agent definition file (legacy)")
def apply(files, file_path):
    """Deploy or update agents."""
    # Resolve file paths
    if files:
        paths = [Path(f) for f in files]
    elif file_path:
        paths = [Path(file_path)]
    else:
        paths = [find_agent_file()]

    # Determine base_dir for config loading
    base_dir = paths[0].parent if paths[0].is_file() else paths[0].parent if paths[0].is_dir() else Path.cwd()

    agents = load_agents(paths, base_dir=base_dir)
    click.echo(f"Loaded {len(agents)} agent(s)")

    adapter = LangChainAdapter()

    for agent in agents:
        click.echo(f"\nAgent: {agent.name}")

        click.echo("  Validating... ", nl=False)
        errors = adapter.validate(agent)
        if errors:
            click.echo("FAILED")
            for err in errors:
                click.echo(f"    {err.field}: {err.message}", err=True)
            raise SystemExit(1)
        click.echo("OK")

        click.echo("  Generating code... ", nl=False)
        # Find base_dir for this agent's tools
        agent_base = _find_agent_base_dir(agent.name, paths)
        code = adapter.generate(agent, base_dir=agent_base)
        click.echo("OK")

        provider = get_provider(agent)
        current_hash = provider.get_hash(agent.name)
        deploy_plan = provider.plan(agent, current_hash)

        if not deploy_plan.actions:
            click.echo("  No changes. Already up to date.")
            continue

        click.echo("  Deploying... ", nl=False)
        provider.set_generated_code(code)
        provider.set_agent(agent)
        result = provider.apply(deploy_plan)

        if result.success:
            click.echo("OK")
            click.echo(f"  {result.message}")
        else:
            click.echo("FAILED")
            click.echo(f"  Error: {result.message}", err=True)
            raise SystemExit(1)


def _find_agent_base_dir(agent_name: str, paths: list[Path]) -> Path:
    """Find the base directory for an agent's tools.

    Looks for a directory matching the agent name among the provided paths,
    or falls back to the first path's parent.
    """
    for p in paths:
        if p.is_dir() and p.name == agent_name:
            return p
        if p.is_dir():
            subdir = p / agent_name
            if subdir.exists():
                return subdir
    # Fallback: first path's parent or the path itself
    first = paths[0] if paths else Path.cwd()
    return first if first.is_dir() else first.parent
```

- [ ] **Step 2: Run CLI tests**

Run: `uv run pytest packages/python/agentstack-cli/tests/ -v`
Expected: All PASS

- [ ] **Step 3: Run full test suite**

Run: `uv run pytest packages/python/ -v`
Expected: All PASS

- [ ] **Step 4: Commit**

```bash
git add packages/python/agentstack-cli/src/agentstack_cli/commands/apply.py
git commit -m "feat: update apply command for multi-agent deployment"
```

---

### Task 6: Update CLI destroy and status for multi-agent

**Files:**
- Modify: `packages/python/agentstack-cli/src/agentstack_cli/commands/destroy.py`
- Modify: `packages/python/agentstack-cli/src/agentstack_cli/commands/status.py`
- Modify: `packages/python/agentstack-cli/src/agentstack_cli/commands/plan.py`

- [ ] **Step 1: Update destroy for multi-agent**

```python
# packages/python/agentstack-cli/src/agentstack_cli/commands/destroy.py
"""agentstack destroy — stop and remove agents."""

from pathlib import Path

import click

from agentstack_cli.loader import find_agent_file, load_agents
from agentstack_cli.provider_factory import get_provider


@click.command()
@click.argument("files", nargs=-1, type=click.Path(exists=True))
@click.option("--file", "file_path", default=None, help="Path to agent definition file (legacy)")
@click.option("--name", "agent_name", default=None, help="Destroy a specific agent by name")
@click.option("--include-resources", is_flag=True, default=False,
              help="Also remove backing infrastructure")
def destroy(files, file_path, agent_name, include_resources):
    """Stop and remove deployed agents."""
    if agent_name and not files and not file_path:
        # Destroy by name without loading a file — default to Docker
        from agentstack_provider_docker import DockerProvider
        provider = DockerProvider()
        click.echo(f"Destroying: {agent_name}")
        provider.destroy(agent_name, include_resources=include_resources)
        click.echo(f"Destroyed: {agent_name}")
        return

    # Load agents
    if files:
        paths = [Path(f) for f in files]
    elif file_path:
        paths = [Path(file_path)]
    else:
        paths = [find_agent_file()]

    base_dir = paths[0].parent if paths[0].is_file() else paths[0].parent
    agents = load_agents(paths, base_dir=base_dir)

    # Filter to specific agent if --name given
    if agent_name:
        agents = [a for a in agents if a.name == agent_name]
        if not agents:
            click.echo(f"Agent '{agent_name}' not found in definition.", err=True)
            raise SystemExit(1)

    for agent in agents:
        click.echo(f"Destroying: {agent.name}")
        provider = get_provider(agent)
        provider.set_agent(agent)

        if include_resources and hasattr(provider, "list_resources"):
            resources = provider.list_resources(agent.name)
            if resources:
                click.echo("  Resources to delete:")
                for r in resources:
                    click.echo(f"    - {r['type']}: {r['name']}")

        try:
            provider.destroy(agent.name, include_resources=include_resources)
            click.echo(f"  OK")
        except Exception as e:
            click.echo(f"  FAILED: {e}", err=True)

    click.echo(f"Destroyed {len(agents)} agent(s)")
```

- [ ] **Step 2: Update status for multi-agent**

```python
# packages/python/agentstack-cli/src/agentstack_cli/commands/status.py
"""agentstack status — show agent status."""

from pathlib import Path

import click

from agentstack_cli.loader import find_agent_file, load_agents
from agentstack_cli.provider_factory import get_provider


@click.command()
@click.argument("files", nargs=-1, type=click.Path(exists=True))
@click.option("--file", "file_path", default=None, help="Path to agent definition file (legacy)")
@click.option("--name", "agent_name", default=None, help="Show status for a specific agent")
def status(files, file_path, agent_name):
    """Show the status of deployed agents."""
    if agent_name and not files and not file_path:
        from agentstack_provider_docker import DockerProvider
        provider = DockerProvider()
        _show_status(provider, agent_name)
        return

    if files:
        paths = [Path(f) for f in files]
    elif file_path:
        paths = [Path(file_path)]
    else:
        paths = [find_agent_file()]

    base_dir = paths[0].parent if paths[0].is_file() else paths[0].parent
    agents = load_agents(paths, base_dir=base_dir)

    if agent_name:
        agents = [a for a in agents if a.name == agent_name]

    for agent in agents:
        provider = get_provider(agent)
        provider.set_agent(agent)
        _show_status(provider, agent.name)


def _show_status(provider, agent_name: str):
    agent_status = provider.status(agent_name)
    click.echo(f"Agent: {agent_name}")
    if agent_status.running:
        click.echo(f"  Status: running")
        if agent_status.hash:
            click.echo(f"  Hash: {agent_status.hash[:16]}...")
        info = agent_status.info
        if "url" in info and info["url"]:
            click.echo(f"  URL: {info['url']}")
        elif "ports" in info and "8000/tcp" in info["ports"] and info["ports"]["8000/tcp"]:
            host_port = info["ports"]["8000/tcp"][0].get("HostPort", "?")
            click.echo(f"  URL: http://localhost:{host_port}")
    else:
        click.echo(f"  Status: not deployed")
```

- [ ] **Step 3: Update plan for multi-agent**

```python
# packages/python/agentstack-cli/src/agentstack_cli/commands/plan.py
"""agentstack plan — show what would change."""

from pathlib import Path

import click

from agentstack.hash import hash_agent
from agentstack_adapter_langchain import LangChainAdapter
from agentstack_cli.loader import find_agent_file, load_agents
from agentstack_cli.provider_factory import get_provider


@click.command()
@click.argument("files", nargs=-1, type=click.Path(exists=True))
@click.option("--file", "file_path", default=None, help="Path to agent definition file (legacy)")
def plan(files, file_path):
    """Show what would change if you applied."""
    if files:
        paths = [Path(f) for f in files]
    elif file_path:
        paths = [Path(file_path)]
    else:
        paths = [find_agent_file()]

    base_dir = paths[0].parent if paths[0].is_file() else paths[0].parent
    agents = load_agents(paths, base_dir=base_dir)

    adapter = LangChainAdapter()

    for agent in agents:
        click.echo(f"Agent: {agent.name}")
        click.echo(f"  Provider: {agent.model.provider.type} ({agent.model.model_name})")
        if agent.platform:
            click.echo(f"  Platform: {agent.platform.type} ({agent.platform.provider.type})")

        errors = adapter.validate(agent)
        if errors:
            for err in errors:
                click.echo(f"  Validation error: {err.field} — {err.message}", err=True)
            continue

        try:
            provider = get_provider(agent)
            provider.set_agent(agent)
            current_hash = provider.get_hash(agent.name)
            deploy_plan = provider.plan(agent, current_hash)

            if not deploy_plan.actions:
                click.echo("  No changes. Already up to date.")
            else:
                click.echo("  Changes:")
                for action in deploy_plan.actions:
                    click.echo(f"    + {action}")
        except Exception as e:
            tree = hash_agent(agent)
            click.echo(f"  Could not connect to provider: {e}", err=True)
            click.echo(f"  Target hash: {tree.root[:16]}...")

        click.echo()
```

- [ ] **Step 4: Run full test suite**

Run: `uv run pytest packages/python/ -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add packages/python/agentstack-cli/src/agentstack_cli/commands/
git commit -m "feat: update destroy, status, plan commands for multi-agent"
```

---

### Task 7: Create multi-agent examples and test end-to-end

**Files:**
- Create: `examples/azure-multi-agent/agentstack.py`
- Create: `examples/azure-multi-agent/agentstack.yaml`
- Create: `examples/azure-multi-agent/weather/tools/get_weather.py`
- Create: `examples/azure-multi-agent/time/tools/get_time.py`
- Create: `examples/azure-multi-agent/assistant/tools/ask_weather_agent.py`
- Create: `examples/azure-multi-agent/assistant/tools/ask_time_agent.py`

- [ ] **Step 1: Create Python multi-agent example**

```python
# examples/azure-multi-agent/agentstack.py
"""Multi-agent Azure deployment — Python code-first."""

import agentstack as ast

# Shared infrastructure — declared once, referenced by all agents
azure = ast.Provider(name="azure", type="azure", config={
    "location": "eastus2",
    "resource_group": "agentstack-multi-rg",
})
anthropic = ast.Provider(name="anthropic", type="anthropic")
model = ast.Model(
    name="minimax", provider=anthropic, model_name="MiniMax-M2.7",
    parameters={"temperature": 0.7, "anthropic_api_url": "https://api.minimax.io/anthropic"},
)
platform = ast.Platform(name="aca", type="container-apps", provider=azure)

weather = ast.Agent(
    name="weather-agent",
    instructions="You are a weather specialist. Use get_weather for real data.",
    model=model,
    platform=platform,
    skills=[ast.Skill(name="weather", tools=["get_weather"])],
    channels=[ast.Channel(name="api", type=ast.ChannelType.API)],
    secrets=[ast.Secret(name="ANTHROPIC_API_KEY")],
)

time_agent = ast.Agent(
    name="time-agent",
    instructions="You are a time specialist. Use get_time for current time.",
    model=model,
    platform=platform,
    skills=[ast.Skill(name="time", tools=["get_time"])],
    channels=[ast.Channel(name="api", type=ast.ChannelType.API)],
    secrets=[ast.Secret(name="ANTHROPIC_API_KEY")],
)

assistant = ast.Agent(
    name="assistant-agent",
    instructions="You are a helpful assistant. Use ask_weather_agent and ask_time_agent.",
    model=model,
    platform=platform,
    skills=[ast.Skill(name="assistant", tools=["ask_weather_agent", "ask_time_agent"])],
    channels=[ast.Channel(name="api", type=ast.ChannelType.API)],
    secrets=[ast.Secret(name="ANTHROPIC_API_KEY")],
)
```

- [ ] **Step 2: Create YAML multi-agent example**

```yaml
# examples/azure-multi-agent/agentstack.yaml
providers:
  azure:
    type: azure
    config:
      location: eastus2
      resource_group: agentstack-multi-rg
  anthropic:
    type: anthropic

platforms:
  aca:
    type: container-apps
    provider: azure

models:
  minimax:
    provider: anthropic
    model_name: MiniMax-M2.7
    parameters:
      temperature: 0.7
      anthropic_api_url: https://api.minimax.io/anthropic

agents:
  - name: weather-agent
    instructions: You are a weather specialist. Use get_weather for real data.
    model: minimax
    platform: aca
    skills:
      - name: weather
        tools: [get_weather]
    channels:
      - name: api
        type: api
    secrets:
      - name: ANTHROPIC_API_KEY

  - name: time-agent
    instructions: You are a time specialist. Use get_time for current time.
    model: minimax
    platform: aca
    skills:
      - name: time
        tools: [get_time]
    channels:
      - name: api
        type: api
    secrets:
      - name: ANTHROPIC_API_KEY

  - name: assistant-agent
    instructions: You are a helpful assistant. Use ask_weather_agent and ask_time_agent.
    model: minimax
    platform: aca
    skills:
      - name: assistant
        tools: [ask_weather_agent, ask_time_agent]
    channels:
      - name: api
        type: api
    secrets:
      - name: ANTHROPIC_API_KEY
```

- [ ] **Step 3: Copy tool files from existing multi-agent example**

```bash
cp examples/multi-agent/weather/tools/get_weather.py examples/azure-multi-agent/weather/tools/
cp examples/multi-agent/time/tools/get_time.py examples/azure-multi-agent/time/tools/
cp examples/multi-agent/assistant/tools/ask_weather_agent.py examples/azure-multi-agent/assistant/tools/
cp examples/multi-agent/assistant/tools/ask_time_agent.py examples/azure-multi-agent/assistant/tools/
```

- [ ] **Step 4: Verify YAML multi-agent loads**

```bash
uv run python -c "
from agentstack_cli.loader import load_agents
from pathlib import Path
agents = load_agents([Path('examples/azure-multi-agent/agentstack.yaml')])
for a in agents:
    print(f'{a.name}: platform={a.platform.type if a.platform else None}')
print(f'Shared platform: {agents[0].platform is agents[1].platform}')
"
```

Expected:
```
weather-agent: platform=container-apps
time-agent: platform=container-apps
assistant-agent: platform=container-apps
Shared platform: True
```

- [ ] **Step 5: Verify Python multi-agent loads**

```bash
uv run python -c "
from agentstack_cli.loader import load_agents
from pathlib import Path
agents = load_agents([Path('examples/azure-multi-agent/agentstack.py')])
for a in agents:
    print(f'{a.name}: platform={a.platform.type if a.platform else None}')
print(f'Shared platform: {agents[0].platform is agents[1].platform}')
"
```

Expected: Same output, `Shared platform: True`

- [ ] **Step 6: Run full test suite**

Run: `uv run pytest packages/python/ -v`
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
git add examples/azure-multi-agent/
git commit -m "feat: add azure-multi-agent examples (Python + YAML)"
```
