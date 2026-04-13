# Test Examples Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create 5 example agents that exercise postgres sessions, long-term memory, MCP servers, and Python code-first definitions.

**Architecture:** Each example is an independent directory under `examples/` with an `agentstack.yaml` (or `agentstack.py`) and optional tool/data files. No core package changes needed.

**Tech Stack:** YAML, Python, Docker, MiniMax via Anthropic-compatible API

---

### Task 1: Create minimal example

**Files:**
- Create: `examples/minimal/agentstack.yaml`

- [ ] **Step 1: Create the directory and YAML file**

```yaml
# examples/minimal/agentstack.yaml
name: minimal-agent
instructions: |
  You are a minimal agent. You have no tools and no memory.
  Just chat and be helpful.
model:
  name: minimax
  provider:
    name: anthropic
    type: anthropic
  model_name: MiniMax-M2.7
  parameters:
    temperature: 0.7
    anthropic_api_url: https://api.minimax.io/anthropic
platform:
  name: docker
  type: docker
  provider:
    name: docker
    type: docker
channels:
  - name: api
    type: api
secrets:
  - name: ANTHROPIC_API_KEY
port: 8090
```

- [ ] **Step 2: Verify YAML loads**

Run: `cd ~/Developer/work/AgentsStack && uv run python -c "from agentstack import load_agent; a = load_agent('examples/minimal/agentstack.yaml'); print(f'{a.name}: platform={a.platform.type}, sessions={a.sessions}')"`

Expected: `minimal-agent: platform=docker, sessions=None`

- [ ] **Step 3: Deploy and test**

Run:
```bash
cd ~/Developer/work/AgentsStack/examples/minimal
ANTHROPIC_API_KEY="***REMOVED***" uv run agentstack apply
```

Then:
```bash
curl -s http://localhost:8090/health
curl -s -X POST http://localhost:8090/invoke -H "Content-Type: application/json" -d '{"message": "Hello!"}'
```

Expected: Health OK, response with text.

- [ ] **Step 4: Destroy**

Run:
```bash
cd ~/Developer/work/AgentsStack/examples/minimal
ANTHROPIC_API_KEY="***REMOVED***" uv run agentstack destroy
```

- [ ] **Step 5: Commit**

```bash
cd ~/Developer/work/AgentsStack
git add examples/minimal/
git commit -m "feat: add minimal example — bare minimum agent deployment"
```

---

### Task 2: Create sessions-postgres example

**Files:**
- Create: `examples/sessions-postgres/agentstack.yaml`

- [ ] **Step 1: Create the directory and YAML file**

```yaml
# examples/sessions-postgres/agentstack.yaml
name: sessions-agent
instructions: |
  You are a helpful assistant with persistent memory of our conversation.
  If the user has told you something before, remember it.
  Refer back to earlier parts of the conversation when relevant.
model:
  name: minimax
  provider:
    name: anthropic
    type: anthropic
  model_name: MiniMax-M2.7
  parameters:
    temperature: 0.7
    anthropic_api_url: https://api.minimax.io/anthropic
platform:
  name: docker
  type: docker
  provider:
    name: docker
    type: docker
sessions:
  type: postgres
  provider:
    name: docker
    type: docker
channels:
  - name: api
    type: api
secrets:
  - name: ANTHROPIC_API_KEY
port: 8091
```

- [ ] **Step 2: Verify YAML loads**

Run: `cd ~/Developer/work/AgentsStack && uv run python -c "from agentstack import load_agent; a = load_agent('examples/sessions-postgres/agentstack.yaml'); print(f'{a.name}: sessions={a.sessions.engine}')"`

Expected: `sessions-agent: sessions=postgres`

- [ ] **Step 3: Deploy and test session persistence**

Run:
```bash
cd ~/Developer/work/AgentsStack/examples/sessions-postgres
ANTHROPIC_API_KEY="***REMOVED***" uv run agentstack apply
```

Test session persistence — send two messages in the same session:
```bash
# First message — get session_id from response
curl -s -X POST http://localhost:8091/invoke -H "Content-Type: application/json" -d '{"message": "My name is Alex."}'

# Second message — use the session_id from the first response
curl -s -X POST http://localhost:8091/invoke -H "Content-Type: application/json" -d '{"message": "What is my name?", "session_id": "<SESSION_ID_FROM_FIRST>"}'
```

Expected: Second response should mention "Alex".

- [ ] **Step 4: Verify postgres container was provisioned**

Run: `docker ps --filter "label=agentstack.resource" --format "table {{.Names}}\t{{.Status}}"`

Expected: A container named `agentstack-resource-sessions` running postgres.

- [ ] **Step 5: Destroy**

Run:
```bash
cd ~/Developer/work/AgentsStack/examples/sessions-postgres
ANTHROPIC_API_KEY="***REMOVED***" uv run agentstack destroy
```

- [ ] **Step 6: Commit**

```bash
cd ~/Developer/work/AgentsStack
git add examples/sessions-postgres/
git commit -m "feat: add sessions-postgres example — postgres-backed session persistence"
```

---

### Task 3: Create memory-agent example

**Files:**
- Create: `examples/memory-agent/agentstack.yaml`

- [ ] **Step 1: Create the directory and YAML file**

```yaml
# examples/memory-agent/agentstack.yaml
name: memory-agent
instructions: |
  You are a personal assistant with long-term memory.
  Remember important facts the user tells you (name, preferences, projects).
  When starting a new conversation, recall what you know about the user.
  Use save_memory when the user shares important facts.
  Use forget_memory when asked to forget something.
model:
  name: minimax
  provider:
    name: anthropic
    type: anthropic
  model_name: MiniMax-M2.7
  parameters:
    temperature: 0.7
    anthropic_api_url: https://api.minimax.io/anthropic
platform:
  name: docker
  type: docker
  provider:
    name: docker
    type: docker
sessions:
  type: postgres
  provider:
    name: docker
    type: docker
memory:
  type: postgres
  provider:
    name: docker
    type: docker
skills:
  - name: assistant
    tools: []
channels:
  - name: api
    type: api
secrets:
  - name: ANTHROPIC_API_KEY
port: 8092
```

- [ ] **Step 2: Verify YAML loads**

Run: `cd ~/Developer/work/AgentsStack && uv run python -c "from agentstack import load_agent; a = load_agent('examples/memory-agent/agentstack.yaml'); print(f'{a.name}: sessions={a.sessions.engine}, memory={a.memory.engine}')"`

Expected: `memory-agent: sessions=postgres, memory=postgres`

- [ ] **Step 3: Deploy and test long-term memory**

Run:
```bash
cd ~/Developer/work/AgentsStack/examples/memory-agent
ANTHROPIC_API_KEY="***REMOVED***" uv run agentstack apply
```

Test memory — tell it a fact, then start a NEW session and see if it recalls:
```bash
# Session 1: teach it a fact
curl -s -X POST http://localhost:8092/invoke -H "Content-Type: application/json" -d '{"message": "My favorite color is blue. Please remember that."}'

# Session 2: new session (no session_id), ask if it remembers
curl -s -X POST http://localhost:8092/invoke -H "Content-Type: application/json" -d '{"message": "What is my favorite color?"}'
```

Expected: The second response (new session) should mention "blue" — proving long-term memory works across sessions.

- [ ] **Step 4: Verify two postgres containers provisioned**

Run: `docker ps --filter "label=agentstack.resource" --format "table {{.Names}}\t{{.Status}}"`

Expected: Two postgres containers — `agentstack-resource-sessions` and `agentstack-resource-memory`.

- [ ] **Step 5: Destroy**

Run:
```bash
cd ~/Developer/work/AgentsStack/examples/memory-agent
ANTHROPIC_API_KEY="***REMOVED***" uv run agentstack destroy
```

- [ ] **Step 6: Commit**

```bash
cd ~/Developer/work/AgentsStack
git add examples/memory-agent/
git commit -m "feat: add memory-agent example — long-term memory across sessions"
```

---

### Task 4: Create mcp-files example

**Files:**
- Create: `examples/mcp-files/agentstack.yaml`
- Create: `examples/mcp-files/sample-docs/readme.txt`
- Create: `examples/mcp-files/sample-docs/notes.txt`

- [ ] **Step 1: Create sample documents**

```
# examples/mcp-files/sample-docs/readme.txt
AgentStack Project Overview

AgentStack is a declarative, platform-agnostic orchestration layer for AI agents.
It defines, provisions, deploys, updates, and manages agents across any framework,
any platform, and any cloud — from a single command.

Key principles:
1. Agents are infrastructure
2. Define once, deploy everywhere
3. Build nothing, integrate everything
4. Code over config
5. Progressive complexity
```

```
# examples/mcp-files/sample-docs/notes.txt
Meeting Notes - April 2026

Attendees: Alice, Bob, Charlie

Action Items:
- Alice: Review the API design doc by Friday
- Bob: Set up staging environment for load testing
- Charlie: Update the onboarding guide with new MCP examples

Decisions:
- Agreed to use Azure Container Apps for production deployment
- Will migrate from SQLite to Postgres for session storage
- MCP filesystem server approved for document analysis use case
```

- [ ] **Step 2: Create the YAML file**

```yaml
# examples/mcp-files/agentstack.yaml
name: mcp-files-agent
instructions: |
  You are a file analysis agent. You can read files from the /docs directory
  using your MCP tools. When asked about files, use your tools to read and
  analyze them. List files before reading to know what's available.
model:
  name: minimax
  provider:
    name: anthropic
    type: anthropic
  model_name: MiniMax-M2.7
  parameters:
    temperature: 0.3
    anthropic_api_url: https://api.minimax.io/anthropic
platform:
  name: docker
  type: docker
  provider:
    name: docker
    type: docker
mcp_servers:
  - name: filesystem
    transport: stdio
    command: npx -y @modelcontextprotocol/server-filesystem /docs
    install: npm install -g @modelcontextprotocol/server-filesystem
channels:
  - name: api
    type: api
secrets:
  - name: ANTHROPIC_API_KEY
port: 8093
```

- [ ] **Step 3: Copy sample-docs into the build context**

The Docker provider builds from `.agentstack/<agent-name>/`. After `agentstack apply` generates the code, the sample-docs need to be in the build context. Add a step to copy them:

Run after deploy to check if docs were included:
```bash
cd ~/Developer/work/AgentsStack/examples/mcp-files
ANTHROPIC_API_KEY="***REMOVED***" uv run agentstack apply
```

If the MCP server can't find `/docs`, we may need to manually copy sample-docs into the build context and add a `COPY sample-docs /docs` to the Dockerfile. Check the generated Dockerfile:
```bash
cat .agentstack/mcp-files-agent/Dockerfile
```

If `/docs` is missing, copy the files and rebuild:
```bash
cp -r sample-docs .agentstack/mcp-files-agent/sample-docs
# Add "COPY sample-docs /docs" to the Dockerfile before the CMD line
# Rebuild with: docker build -t agentstack-mcp-files-agent .agentstack/mcp-files-agent/
```

- [ ] **Step 4: Test MCP file reading**

```bash
curl -s http://localhost:8093/health
curl -s -X POST http://localhost:8093/invoke -H "Content-Type: application/json" -d '{"message": "List the files in /docs and tell me what they contain."}'
```

Expected: Response should mention both `readme.txt` and `notes.txt` with summaries of their content.

- [ ] **Step 5: Destroy**

Run:
```bash
cd ~/Developer/work/AgentsStack/examples/mcp-files
ANTHROPIC_API_KEY="***REMOVED***" uv run agentstack destroy
```

- [ ] **Step 6: Commit**

```bash
cd ~/Developer/work/AgentsStack
git add examples/mcp-files/
git commit -m "feat: add mcp-files example — filesystem MCP server integration"
```

---

### Task 5: Create code-first example

**Files:**
- Create: `examples/code-first/agentstack.py`

- [ ] **Step 1: Create the Python definition file**

```python
# examples/code-first/agentstack.py
"""Code-first agent definition — Python instead of YAML."""

import agentstack as ast

anthropic = ast.Provider(name="anthropic", type="anthropic")
docker = ast.Provider(name="docker", type="docker")

model = ast.Model(
    name="minimax",
    provider=anthropic,
    model_name="MiniMax-M2.7",
    parameters={
        "temperature": 0.7,
        "anthropic_api_url": "https://api.minimax.io/anthropic",
    },
)

agent = ast.Agent(
    name="code-first-agent",
    instructions=(
        "You are a personal assistant defined in Python code.\n"
        "Remember important facts the user tells you.\n"
        "Use save_memory and forget_memory tools as needed."
    ),
    model=model,
    platform=ast.Platform(name="docker", type="docker", provider=docker),
    sessions=ast.Postgres(provider=docker),
    memory=ast.Postgres(provider=docker),
    skills=[ast.Skill(name="assistant", tools=[])],
    channels=[ast.Channel(name="api", type=ast.ChannelType.API)],
    secrets=[ast.Secret(name="ANTHROPIC_API_KEY")],
    port=8094,
)
```

- [ ] **Step 2: Verify Python file loads**

Run: `cd ~/Developer/work/AgentsStack/examples/code-first && uv run python -c "from agentstack_cli.loader import find_agent_file, load_agent_from_file; p = find_agent_file(); a = load_agent_from_file(p); print(f'{a.name}: sessions={a.sessions.engine}, memory={a.memory.engine}, port={a.port}')"`

Expected: `code-first-agent: sessions=postgres, memory=postgres, port=8094`

- [ ] **Step 3: Deploy and test**

Run:
```bash
cd ~/Developer/work/AgentsStack/examples/code-first
ANTHROPIC_API_KEY="***REMOVED***" uv run agentstack apply
```

Test:
```bash
curl -s http://localhost:8094/health
curl -s -X POST http://localhost:8094/invoke -H "Content-Type: application/json" -d '{"message": "Hello! I am testing the code-first agent."}'
```

Expected: Health OK, response with text, memory tools available.

- [ ] **Step 4: Destroy**

Run:
```bash
cd ~/Developer/work/AgentsStack/examples/code-first
ANTHROPIC_API_KEY="***REMOVED***" uv run agentstack destroy
```

- [ ] **Step 5: Commit**

```bash
cd ~/Developer/work/AgentsStack
git add examples/code-first/
git commit -m "feat: add code-first example — Python-defined agent with memory"
```
