---
title: Introduction
sidebar_label: Introduction
sidebar_position: 1
slug: /getting-started/intro
---

# Introduction

**Vystak is to AI agents what Pulumi is to cloud infrastructure.** Define your agent once in YAML or Python, and Vystak generates the framework code, provisions the infrastructure, and deploys the agent — to Docker, Azure Container Apps, or any future platform.

Vystak builds nothing. It wires everything.

## What you can do with Vystak

- **Define agents declaratively** — one YAML or Python file describes the model, tools, sessions, channels, and where to run.
- **Deploy anywhere** — Docker locally, Azure Container Apps in production. Same definition, different target.
- **OpenAI-compatible API** — every agent exposes `/v1/chat/completions` and `/v1/responses` out of the box. Drop-in replacement for any OpenAI client.
- **Multi-agent collaboration** — built-in A2A protocol, gateway routing, and registry. Agents discover and call each other natively.
- **Persistence built in** — Postgres sessions, long-term memory, all auto-provisioned alongside the agent.
- **Hash-based change detection** — `vystak apply` only redeploys what changed.

## How it works

```
   ┌──────────────────────┐
   │  vystak.yaml or .py  │   ← Define once
   └──────────┬───────────┘
              │
   ┌──────────▼───────────┐
   │   Framework adapter  │   ← Generates LangGraph + FastAPI code
   │       (LangChain)    │
   └──────────┬───────────┘
              │
   ┌──────────▼───────────┐
   │  Platform provider   │   ← Provisions infra, builds image, deploys
   │  (Docker, Azure,...) │
   └──────────┬───────────┘
              │
   ┌──────────▼───────────┐
   │   Running agent      │   ← /invoke /stream /v1/chat/completions
   └──────────────────────┘
```

Three independent choices for every deployment:

- **Framework adapter** — *how* the agent thinks (LangChain/LangGraph today, others coming)
- **Platform provider** — *where* it runs (Docker, Azure Container Apps)
- **Channel adapter** — *how* users reach it (REST API, Slack, webhook)

Any combination works. The agent definition doesn't change — only the platform target does.

## Core concepts

| Concept | What it is |
|---------|------------|
| **Agent** | The deployable unit — model, tools, sessions, channels |
| **Model** | Which LLM and how to call it (Anthropic, OpenAI-compatible, MiniMax) |
| **Provider** | A cloud account or service (`docker`, `azure`, `anthropic`) |
| **Platform** | Where the agent runs (`docker`, `container-apps`) |
| **Service** | Backing infrastructure (Postgres, Redis, Qdrant) |
| **Channel** | How users reach the agent (REST, Slack, webhook) |

Each gets its own page — for now, the [Agents](/docs/concepts/agents) page covers the basics. The other concept pages have placeholders we'll expand soon.

## What's next

- [Installation](/docs/getting-started/installation) — install the CLI and Python packages
- [Quickstart](/docs/getting-started/quickstart) — deploy your first agent in five minutes
- [Agents](/docs/concepts/agents) — the agent schema in depth
