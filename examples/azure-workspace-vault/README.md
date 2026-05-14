# Azure Key Vault — standalone workspace example

Agent + standalone workspace app. Demonstrates **LLM-side / tool-side secret
isolation**: the model-facing container holds only the key it needs to call
the LLM (`ANTHROPIC_API_KEY`), while tool-side secrets (`STRIPE_API_KEY`)
live exclusively in the workspace app. Each container has its own UAMI with
`lifecycle: None`, so neither process can impersonate the other to fetch the
sibling's secret.

## What this demonstrates

- Two separate Azure Container Apps in the same ACA Environment — one for the
  agent, one for the workspace
- Two per-container UAMIs (agent + workspace) with `lifecycle: None`
- Per-secret grant scoping: agent UAMI has read on `ANTHROPIC_API_KEY`
  only; workspace UAMI has read on `STRIPE_API_KEY` only
- Agent reaches the workspace via internal DNS at
  `<workspace-app>.internal.<env>:22` over SSH-RPC (same transport as the
  Docker provider)
- `workspace.persistence: volume` backed by an Azure Files share mounted at
  `/workspace` — data survives container restarts
- `vystak.secrets.get("STRIPE_API_KEY")` inside a tool — the helper connects
  to the workspace app via SSH-RPC, returning the environment value

## Topology

The deployment produces two ACA apps inside a shared ACA Environment:

```
ACA Environment
├── assistant          (agent app)   — holds ANTHROPIC_API_KEY via UAMI
└── assistant-workspace (workspace app) — holds STRIPE_API_KEY via UAMI
                                          /workspace → Azure Files share
```

The agent app connects to the workspace app over internal ACA networking
on port 22 using SSH-RPC — no public endpoint is exposed for the workspace.

## Prerequisites

- An Azure subscription with `az login` completed (or `AZURE_SUBSCRIPTION_ID`
  set as an environment variable)
- An **existing** Azure Storage Account in the same region as the ACA
  environment (`eastus2` by default). Pass its name via the
  `AZURE_STORAGE_ACCOUNT` environment variable. The storage account is used to
  create an Azure Files share that backs the workspace volume.
- The storage account must be in the same region as the ACA environment.

## Files

- `vystak.yaml` — declarative config
- `vystak.py` — Python code-first equivalent
- `tools/charge_card.py` — example tool reading the Stripe key via the SDK
- `.env.example` — template for local apply-time values

## Run

```bash
cp .env.example .env     # then edit both keys and set AZURE_STORAGE_ACCOUNT
vystak plan              # preview the vault / identities / secrets / grants / workspace app
vystak apply             # create vault + 2 UAMIs + Files share + 2 ACA apps, push both secrets, deploy
vystak secrets list      # show declared secrets vs. vault state
vystak destroy           # tear down the resource group
```

## Why this layout

If you dropped `STRIPE_API_KEY` into the agent container alongside
`ANTHROPIC_API_KEY`, a prompt-injection exploit that coaxed the LLM into
reading its own env would leak the Stripe key to an attacker. By keeping
the billing credential in a **separate ACA app** behind an SSH-RPC boundary,
a compromised LLM cannot see the key — only **call** `charge_card` with
arguments the tool itself validates.

The Azure Files share (`persistence: volume`) ensures that any tool-side
state written to `/workspace` — cached data, compiled artifacts, intermediate
files — survives workspace container restarts without requiring the agent to
rebuild its tooling environment on every deploy.
