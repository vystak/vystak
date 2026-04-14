# Multi-Agent Deployment — Design Spec

## Overview

Support deploying multiple agents from a single command, with shared infrastructure deduplication. Works with both Python (object identity) and YAML (config equality) definitions. Agents sharing the same provider and platform get shared infrastructure (RG, ACR, ACA Environment). Agents on different platforms deploy independently.

## Core Concept

Resources are instances, not containers. When two agents reference the same provider/platform, they share infrastructure. The system figures out the graph from the references — no explicit "stack" or "fleet" wrapper needed.

### Python: Object Identity

```python
azure = ast.Provider(name="azure", type="azure", config={"location": "eastus2", "resource_group": "multi-rg"})
platform = ast.Platform(name="aca", type="container-apps", provider=azure)

# Same platform object → shared ACA Environment
weather = ast.Agent(name="weather-agent", model=model, platform=platform, ...)
time_agent = ast.Agent(name="time-agent", model=model, platform=platform, ...)
assistant = ast.Agent(name="assistant-agent", model=model, platform=platform, ...)
```

`id(weather.platform) == id(time_agent.platform)` → same infra.

### YAML: Config Equality

```bash
agentstack apply weather/agentstack.yaml time/agentstack.yaml assistant/agentstack.yaml
```

Each YAML declares its own provider/platform. The system groups agents whose provider+platform configs are structurally equal:

```yaml
# weather/agentstack.yaml
platform:
  name: aca
  type: container-apps
  provider:
    name: azure
    type: azure
    config:
      location: eastus2
      resource_group: multi-rg
```

```yaml
# time/agentstack.yaml — same provider+platform config
platform:
  name: aca
  type: container-apps
  provider:
    name: azure
    type: azure
    config:
      location: eastus2
      resource_group: multi-rg
```

These two agents share infra because their platform provider configs are equal (same type, same location, same resource_group).

### Cross-Platform Deployment

Agents in the same apply can target different platforms:

```bash
agentstack apply azure-bot/agentstack.yaml docker-bot/agentstack.yaml
```

The system creates two groups — one for Azure, one for Docker — and deploys each independently.

## Deduplication Logic

### Grouping Key

Agents are grouped by a **platform fingerprint** — a hash of the platform's provider type + provider config + platform type + platform config (excluding agent-specific overrides like cpu/memory).

```python
def platform_fingerprint(agent: Agent) -> str:
    """Compute a dedup key from provider + platform config."""
    if agent.platform is None:
        return "docker:default"
    key = {
        "provider_type": agent.platform.provider.type,
        "provider_config": agent.platform.provider.config,
        "platform_type": agent.platform.type,
    }
    return hashlib.md5(json.dumps(key, sort_keys=True).encode()).hexdigest()
```

### Python Shortcut

For Python files, before computing the fingerprint, check `id()` of the platform object. Same `id()` → same group (faster, guaranteed correct for Python).

### Per-Group Provisioning

Each group gets one provision graph:

```
Group "azure:eastus2:multi-rg":
  ResourceGroup → LogAnalytics → ACR → ACA Environment
    → ContainerApp: weather-agent
    → ContainerApp: time-agent
    → ContainerApp: assistant-agent

Group "docker:default":
  Network
    → DockerContainer: local-bot
```

## Schema Changes

### Agent — no changes

Agent stays as-is. The multi-agent capability comes from the loader and provider, not the schema.

### Service dedup

Services also deduplicate. If two agents share the same sessions Postgres (same object in Python, same config in YAML), one Postgres instance is provisioned and both agents get the same connection string.

## Loader Changes

### Python Loader

Currently finds one `agent` variable. Change to find **all** `Agent` instances:

```python
def load_agents_from_file(path: Path) -> list[Agent]:
    """Load all Agent instances from a Python file."""
    if path.suffix in (".yaml", ".yml", ".json"):
        agent = load_agent(path)
        return [agent]

    if path.suffix == ".py":
        module = _import_module(path)
        agents = []
        for name in dir(module):
            obj = getattr(module, name)
            if isinstance(obj, Agent):
                agents.append(obj)
        if not agents:
            raise ValueError(f"No Agent instances found in {path}")
        return agents
```

The old `load_agent_from_file()` stays for backward compat (returns the first agent, or the one named `agent`).

### CLI: Multiple Files

`agentstack apply` accepts multiple file arguments:

```bash
# Single file (backward compat)
agentstack apply

# Multiple files
agentstack apply weather/agentstack.yaml time/agentstack.yaml assistant/agentstack.yaml

# Multiple directories (looks for agentstack.yaml in each)
agentstack apply weather/ time/ assistant/

# Single Python file with multiple agents
agentstack apply agentstack.py
```

## Provider Changes

### Multi-Agent Apply

The provider's `apply()` currently takes one `DeployPlan`. For multi-agent, the CLI orchestrates:

1. Load all agents from all files
2. Group by platform fingerprint
3. For each group:
   a. Create one provision graph with shared infra
   b. Add one ContainerApp/DockerAgent node per agent
   c. Execute the graph
4. Report results

This orchestration lives in the CLI (or a new `orchestrator` module), not in the provider. The provider still handles one graph execution at a time.

### Azure Provider: Shared Environment

When the graph has multiple ContainerApp nodes, they all depend on the same ACA Environment node. The environment is created once, then each app is deployed into it.

The ACA Environment enables internal DNS — apps in the same environment can reach each other at `<app-name>.internal.<domain>`.

### Docker Provider: Shared Network

Already works — all agents share `agentstack-net`. Container names serve as DNS.

## CLI Changes

### `agentstack apply`

```
Usage: agentstack apply [OPTIONS] [FILES]...

  Deploy or update agents.

Arguments:
  [FILES]...  Agent definition files or directories. Defaults to current directory.

Options:
  --file TEXT  Path to agent definition file (legacy, single file)
```

### `agentstack destroy`

```
Usage: agentstack destroy [OPTIONS] [FILES]...

  Stop and remove deployed agents.

Arguments:
  [FILES]...  Agent definition files or directories. Defaults to current directory.

Options:
  --name TEXT              Destroy a specific agent by name
  --include-resources      Also remove backing infrastructure
  --file TEXT              Path to agent definition file (legacy)
```

- No args: destroy all agents in the current definition file
- `--name weather-agent`: destroy one specific agent
- `--include-resources`: also remove shared infra (only if no other agents are using it)

### `agentstack status`

Shows all agents from the definition:

```
$ agentstack status
Agents:
  weather-agent   running   https://weather-agent.xxx.eastus2.azurecontainerapps.io
  time-agent      running   https://time-agent.xxx.eastus2.azurecontainerapps.io
  assistant-agent running   https://assistant-agent.xxx.eastus2.azurecontainerapps.io
```

### `agentstack plan`

Shows changes for all agents:

```
$ agentstack plan
Shared infrastructure:
  + Resource Group: multi-rg
  + ACA Environment: multi-rg-env

Agents:
  + weather-agent (new)
  + time-agent (new)
  + assistant-agent (new)
```

## Example: Azure Multi-Agent (Python)

```python
# examples/azure-multi-agent/agentstack.py
import agentstack as ast

# Shared infrastructure
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

# Agents — all share the same platform
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

```bash
cd examples/azure-multi-agent
agentstack apply
# → Creates 1 RG, 1 ACR, 1 Log Analytics, 1 ACA Environment, 3 Container Apps
```

## Example: Azure Multi-Agent (YAML)

```
examples/azure-multi-agent-yaml/
  weather/agentstack.yaml
  weather/tools/get_weather.py
  time/agentstack.yaml
  time/tools/get_time.py
  assistant/agentstack.yaml
  assistant/tools/ask_weather_agent.py
  assistant/tools/ask_time_agent.py
```

```bash
cd examples/azure-multi-agent-yaml
agentstack apply weather/ time/ assistant/
# → Detects matching provider+platform config, shares infra
```

## A2A Agent Discovery

When agents are in the same ACA Environment, they can discover each other via A2A protocol. The assistant's tools need to know the other agents' URLs.

For agents in the same ACA Environment, the URL pattern is predictable:
`https://<agent-name>.<environment-default-domain>`

The provider should inject environment variables for peer agents:
- `WEATHER_AGENT_URL=https://weather-agent.<domain>`
- `TIME_AGENT_URL=https://time-agent.<domain>`

Or more generically, inject all peer agent URLs:
- `AGENTSTACK_PEER_<NAME>=https://<name>.<domain>`

The tools can read these env vars instead of hardcoding URLs.

## Phased Implementation

### Phase A: Multi-agent loader + CLI
- Python loader finds all Agent instances in a file
- CLI accepts multiple files/directories
- Platform fingerprint grouping
- Backward compatible — single agent still works

### Phase B: Multi-agent provisioning
- Shared provision graph for grouped agents
- Azure: shared RG/ACR/ACA Environment, multiple Container Apps
- Docker: shared network, multiple containers
- Peer agent URL injection

### Phase C: Multi-agent lifecycle
- `destroy` with `--name` for individual agents
- `status` shows all agents
- `plan` shows grouped changes
- Shared infra cleanup when last agent is removed

## Out of Scope

- Agent-to-agent dependency declarations (deploy order between agents)
- Cross-region multi-agent (all agents in a group share one region)
- Gateway as an agent type (gateway is still channel-specific)
- Automatic A2A tool generation from peer discovery
