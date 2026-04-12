# Docker Provider + CLI — Design Spec

## Overview

Build the Docker platform provider and CLI commands to complete the end-to-end deployment pipeline: define an agent in Python/YAML → `agentstack plan` → `agentstack apply` → Docker container running.

## Decisions

| Decision | Choice |
|----------|--------|
| Docker image building | Docker Python SDK (`docker` package) |
| CLI framework | Click |
| Agent discovery | Convention with override — `agentstack.yaml` or `agentstack.py`, `--file` flag |
| `init` output | Minimal — single `agentstack.yaml` starter file |
| Plan/Apply separation | Separate commands, `apply` plans internally (no saved plan file) |
| CLI command names | `init`, `plan`, `apply`, `destroy`, `status` |

## Docker Provider

### Package

Modify existing stub: `packages/python/agentstack-provider-docker/`

### Dependencies

Add to `pyproject.toml`:
- `docker>=7.0` (Python Docker SDK)
- `agentstack>=0.1.0` (already present)

### DockerProvider(PlatformProvider)

```python
class DockerProvider(PlatformProvider):
    def plan(self, agent: Agent, current_hash: str | None) -> DeployPlan: ...
    def apply(self, plan: DeployPlan) -> DeployResult: ...
    def destroy(self, agent_name: str) -> None: ...
    def status(self, agent_name: str) -> AgentStatus: ...
    def get_hash(self, agent_name: str) -> str | None: ...
```

Note: `apply()` takes a `DeployPlan` but also needs the generated code to build the image. The provider stores the `GeneratedCode` via a `set_generated_code()` method called by the CLI before `apply()`.

```python
class DockerProvider(PlatformProvider):
    def __init__(self):
        self._client = docker.from_env()
        self._generated_code: GeneratedCode | None = None

    def set_generated_code(self, code: GeneratedCode) -> None:
        self._generated_code = code
```

### Core Flow

**plan(agent, current_hash):**
1. Hash the agent definition using `hash_agent()`
2. Check if container `agentstack-{agent.name}` exists
3. If no container: return plan with action "Create new deployment"
4. If container exists: read `agentstack.hash` label, compare to new hash
5. If hashes match: return plan with no actions (up to date)
6. If hashes differ: return plan with action "Update deployment", include per-section changes

**apply(plan):**
1. Read `self._generated_code` (set by CLI before calling apply)
2. Write files to a temp directory
3. Generate Dockerfile in the same temp directory
4. Build Docker image tagged `agentstack-{agent_name}:latest`
5. Stop and remove existing container if present
6. Start new container with hash labels
7. Return `DeployResult` with success/failure

**destroy(agent_name):**
1. Find container `agentstack-{agent_name}`
2. Stop and remove it
3. Optionally remove the image

**status(agent_name):**
1. Find container `agentstack-{agent_name}`
2. Return running state, hash label, container info

**get_hash(agent_name):**
1. Find container `agentstack-{agent_name}`
2. Read and return `agentstack.hash` label, or None if no container

### Dockerfile Generation

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["python", "server.py"]
```

The entrypoint (`server.py`) comes from `GeneratedCode.entrypoint`. The `CMD` uses it.

### Container Configuration

- **Name:** `agentstack-{agent_name}`
- **Labels:**
  - `agentstack.hash` — root hash of agent definition
  - `agentstack.agent` — agent name
- **Port mapping:** container port 8000 → host port (auto-assigned or configurable)
- **Environment:** secrets from `Agent.secrets` passed as env vars (simple form only — name = env var name)

## CLI

### Package

Modify existing stub: `packages/python/agentstack-cli/`

### Dependencies

Add to `pyproject.toml`:
- `click>=8.0`
- `agentstack-adapter-langchain>=0.1.0`
- `agentstack-provider-docker>=0.1.0`

With workspace sources for both.

### File Structure

```
packages/python/agentstack-cli/
├── pyproject.toml
├── src/agentstack_cli/
│   ├── __init__.py
│   ├── cli.py                    # Click group + command registration
│   ├── loader.py                 # find and load agent definitions
│   └── commands/
│       ├── __init__.py
│       ├── init.py               # agentstack init
│       ├── plan.py               # agentstack plan
│       ├── apply.py              # agentstack apply
│       ├── destroy.py            # agentstack destroy
│       └── status.py             # agentstack status
└── tests/
    ├── test_version.py
    ├── test_loader.py
    ├── test_cli.py
    └── test_init.py
```

### cli.py — Entry Point

```python
@click.group()
@click.version_option(version=__version__)
def cli():
    """AgentStack — declarative AI agent orchestration."""

cli.add_command(init)
cli.add_command(plan)
cli.add_command(apply)
cli.add_command(destroy)
cli.add_command(status)
```

Entry point in `pyproject.toml`: `agentstack = "agentstack_cli.cli:cli"`

### loader.py — Agent Discovery

```python
def find_agent_file(file: str | None = None) -> Path:
    """Find the agent definition file."""
    # If --file specified, use it
    # Otherwise look for agentstack.yaml, agentstack.yml, agentstack.py
    # Raise click.UsageError if not found

def load_agent_from_file(path: Path) -> Agent:
    """Load an Agent from a YAML/JSON or Python file."""
    # YAML/JSON: use agentstack.load_agent()
    # Python: import module, look for 'agent' variable
```

### Commands

**init:**
```
$ agentstack init
Created agentstack.yaml
```
Creates `agentstack.yaml` in current directory with starter content:
```yaml
name: my-agent
model:
  name: claude
  provider:
    name: anthropic
    type: anthropic
  model_name: claude-sonnet-4-20250514
skills:
  - name: assistant
    tools: []
    prompt: You are a helpful assistant.
channels:
  - name: api
    type: api
```

**plan:**
```
$ agentstack plan [--file PATH]

Agent: my-agent
Provider: anthropic (claude-sonnet-4-20250514)
Framework: langchain

Changes:
  + New deployment (no existing container)

Run 'agentstack apply' to deploy.
```

**apply:**
```
$ agentstack apply [--file PATH]

Agent: my-agent
Validating... ✓
Generating code... ✓
Building Docker image... ✓
Starting container... ✓

Deployed: my-agent
  Container: agentstack-my-agent
  URL: http://localhost:8000
  Health: http://localhost:8000/health
```

**destroy:**
```
$ agentstack destroy [--file PATH | --name AGENT_NAME]

Stopping container agentstack-my-agent... ✓
Removing container... ✓
Destroyed: my-agent
```

**status:**
```
$ agentstack status [--file PATH | --name AGENT_NAME]

Agent: my-agent
Status: running
Container: agentstack-my-agent
Hash: a1b2c3d4...
URL: http://localhost:8000
```

### Orchestration Flow (apply command)

1. Load agent definition (loader)
2. Validate via adapter (`LangChainAdapter.validate()`)
3. Generate code via adapter (`LangChainAdapter.generate()`)
4. Hash the agent (`hash_agent()`)
5. Create Docker provider, set generated code
6. Plan (`provider.plan()`)
7. If no changes, print "Up to date" and exit
8. Apply (`provider.apply()`)
9. Print result

## Testing Strategy

### Docker Provider Tests (test_provider.py)

All tests mock the `docker` Python SDK — no real Docker daemon required.

- `test_plan_new_deployment` — no existing container, returns plan with "Create" action
- `test_plan_update` — existing container with different hash, returns plan with "Update" action
- `test_plan_no_change` — existing container with same hash, returns plan with no actions
- `test_apply_builds_and_runs` — verify Docker SDK calls: build image, run container with labels
- `test_apply_replaces_existing` — verify old container stopped/removed before new one starts
- `test_destroy_removes_container` — verify stop and remove calls
- `test_status_running` — container running, returns correct status
- `test_status_not_found` — no container, returns not running
- `test_get_hash_from_label` — reads agentstack.hash label
- `test_get_hash_no_container` — returns None when no container
- `test_container_naming` — verify `agentstack-{name}` convention

### CLI Tests

**test_loader.py:**
- `test_find_yaml` — finds `agentstack.yaml` in current dir
- `test_find_yml` — finds `agentstack.yml`
- `test_find_py` — finds `agentstack.py`
- `test_file_override` — `--file` flag takes precedence
- `test_not_found` — raises error when no file found
- `test_load_yaml` — loads Agent from YAML file
- `test_load_py` — loads Agent from Python file with `agent` variable

**test_init.py:**
- `test_creates_yaml` — file created in current directory
- `test_yaml_content_valid` — created file parses as valid Agent
- `test_no_overwrite` — refuses to overwrite existing file

**test_cli.py** (Click CliRunner, mocked provider/adapter):
- `test_plan_new` — shows "New deployment" message
- `test_plan_up_to_date` — shows "Up to date" message
- `test_apply_success` — shows deployment success
- `test_apply_validation_error` — shows validation errors and exits
- `test_destroy_success` — shows destroy success
- `test_status_running` — shows running status
- `test_status_not_found` — shows not found message

## What This Spec Does NOT Cover

- Cloud providers (AWS, GCP, Azure, DigitalOcean)
- Multi-agent compose
- Fleet management
- Custom framework adapter selection (hardcoded to LangChain for MVP)
- Authentication on deployed agents
- Custom Dockerfile templates
- Docker Compose integration
