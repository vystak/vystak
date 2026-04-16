# vystak

Declarative, platform-agnostic orchestration for AI agents. Define once, deploy everywhere.

Vystak builds nothing. It wires everything. Define your agent in YAML or code, and Vystak generates native framework code, provisions infrastructure, and deploys — from a single command.

## Install

```bash
npm install -g vystak
```

## Quick Start

```bash
# Create an agent definition
vystak init

# Preview what will be generated
vystak plan

# Deploy
vystak apply

# Tear down
vystak destroy
```

## Define an Agent

```yaml
name: support-bot
instructions: |
  You are a helpful support agent. Be concise and friendly.
model:
  name: claude
  provider:
    name: anthropic
    type: anthropic
  model_name: claude-sonnet-4-20250514
platform:
  name: docker
  type: docker
  provider:
    name: docker
    type: docker
skills:
  - name: support
    tools: [lookup_order, process_refund]
channels:
  - name: api
    type: api
```

## What Vystak Does

```
vystak.yaml
    |
    v
+-------------------+
|   Parse & Hash    |  Schema validation, change detection
+-------------------+
    |
    v
+-------------------+
|  Code Generation  |  LangChain, Mastra, or your framework
+-------------------+
    |
    v
+-------------------+
|    Provision      |  Docker, Azure, or your cloud
+-------------------+
    |
    v
  Running Agent
  (OpenAI-compatible API)
```

## Features

- **Declarative** — YAML or Python definitions, no boilerplate
- **Framework-agnostic** — generates native code for LangChain, Mastra, and more
- **Platform-agnostic** — deploys to Docker, Azure Container Apps, with more coming
- **Multi-agent** — agent-to-agent communication via A2A protocol
- **OpenAI-compatible** — every agent exposes `/v1/chat/completions` and `/v1/responses`
- **Change detection** — content-addressable hashing skips unchanged deploys
- **Sessions & memory** — built-in persistence with Postgres, SQLite, or Redis

## Status

Early release. The TypeScript CLI is under active development. For full functionality today, use the Python packages:

```bash
pip install vystak vystak-cli vystak-adapter-langchain vystak-provider-docker
```

## Links

- [Documentation](https://vystak.dev)
- [GitHub](https://github.com/vystak/vystak)
- [PyPI](https://pypi.org/project/vystak/)

## License

Apache-2.0
