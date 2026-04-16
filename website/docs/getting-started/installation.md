---
title: Installation
sidebar_label: Installation
sidebar_position: 2
---

# Installation

Vystak is a set of Python packages plus a CLI. You'll install the core SDK, the CLI, the LangChain adapter, and at least one platform provider.

## Prerequisites

- **Python 3.11 or later**
- **Docker** — required for the [Quickstart](/docs/getting-started/quickstart) and any Docker deploy
- **An LLM API key** — Anthropic, OpenAI, or any compatible endpoint (we use [MiniMax](https://www.minimax.io) in our examples)

Optional, depending on your target:
- **Azure CLI** (`az login`) — if you plan to deploy to Azure Container Apps

## Install the core packages

```bash
pip install vystak vystak-cli vystak-adapter-langchain vystak-provider-docker
```

That's the minimum to deploy a Docker agent. For Azure, also install:

```bash
pip install vystak-provider-azure
```

For the interactive chat client:

```bash
pip install vystak-chat
```

:::tip Use `uv` if you can
[uv](https://github.com/astral-sh/uv) is significantly faster than pip:

```bash
uv pip install vystak vystak-cli vystak-adapter-langchain vystak-provider-docker
```
:::

## Verify the install

```bash
vystak --version
vystak --help
```

You should see the version string and a list of subcommands (`init`, `plan`, `apply`, `destroy`, `status`, `logs`).

## Set your API key

The agent runtime reads its model API key from an environment variable. The variable name is whatever you declare in your agent's `secrets` field — by convention `ANTHROPIC_API_KEY` for Anthropic-compatible models:

```bash
export ANTHROPIC_API_KEY=your-key-here
```

Add it to your shell profile (`~/.zshrc`, `~/.bashrc`) so it persists across sessions.

## What's next

- [Quickstart](/docs/getting-started/quickstart) — deploy your first agent
