---
title: Deploying to Azure Container Apps
sidebar_label: Azure Container Apps
---

# Deploying to Azure Container Apps

`vystak` ships first-class support for Azure Container Apps (ACA). One `vystak apply` provisions every layer the deployment needs — Resource Group → Log Analytics → ACR → ACA Managed Environment → Container Apps for each agent + each channel. Optionally Azure Key Vault and Postgres Flexible Server for secrets and durable sessions.

## Prerequisites

- An Azure subscription you can deploy into (`az login`).
- Docker Desktop running locally (used to build images that get pushed to ACR).
- `vystak` and `vystak-provider-azure` installed (`uv add vystak vystak-cli vystak-provider-azure vystak-adapter-langchain`).

## Minimal config

```yaml
providers:
  azure:
    type: azure
    config:
      location: eastus2
      resource_group: my-app-rg

platforms:
  aca:
    type: container-apps
    provider: azure

agents:
  - name: my-agent
    instructions: You are a helpful assistant.
    model: claude
    platform: aca
    secrets:
      - {name: ANTHROPIC_API_KEY}
```

`vystak apply` will:

1. Create / find the resource group (`my-app-rg`) in `eastus2`.
2. Create / reuse a per-RG Log Analytics workspace, ACR, and ACA Managed Environment.
3. Build the agent's image with `docker buildx --platform linux/amd64`, push to ACR, and deploy as a Container App with the secret wired in.

Subsequent applies are content-addressable: agent definition unchanged ⇒ "Already up to date" with no rebuild. Codegen-only changes (e.g. a new framework-adapter feature) also bump the deploy hash now, so the agent rebuilds when the adapter does.

## Build cache

Each agent / channel build passes `--cache-from type=registry,ref=<acr>/<name>:buildcache` and `--cache-to ...,mode=max` to `docker buildx`. The first build seeds the cache (~2–3 min/component); subsequent builds with unchanged dependencies restore the slow `pip install` and source-bundling layers from ACR (~30s/component). Per-component cache image keeps caches isolated — touching one agent doesn't invalidate another's.

## Secrets — Azure Key Vault (recommended)

Declare a vault to push every declared `Secret` to a Key Vault and wire each agent + channel + workspace to a per-principal User Assigned Managed Identity (UAMI) with read access only on its own secrets:

```yaml
vault:
  name: my-app-vault
  provider: azure
  mode: deploy
  config:
    vault_name: my-app-vault
```

On apply:

1. Key Vault is created in the same RG with `enable_rbac_authorization=true`.
2. The deployer (the user running `vystak apply`) is granted **Secrets Officer** so they can push secret values from `.env` into KV. This is auto-resolved from `az ad signed-in-user show` (override via `AZURE_DEPLOYER_OBJECT_ID`).
3. One UAMI is created per principal (`<agent>-agent`, `<agent>-workspace`, `<channel>-channel`) and granted **Secrets User** on exactly the secrets it declared.
4. The Container App template references each secret as `{ keyVaultUrl, identity: <uami>, lifecycle: None }` — values are mounted at container start without ever touching `vystak`'s state.

Tenant ID is auto-resolved from `az account show` (override via `AZURE_TENANT_ID` or `provider.config.tenant_id`).

## Sessions and memory — Azure Postgres Flexible Server

Add `sessions:` to an agent for durable conversation memory:

```yaml
agents:
  - name: assistant
    # ...
    sessions:
      type: postgres
      name: assistant-sessions
      provider: {name: azure, type: azure}
```

`vystak apply` creates a Flexible Server in the same RG (sized for dev tier by default), bootstraps a `vystak` database, and emits the connection string into the agent's container env. The same shape works for `memory:` (long-term key-value store) on a separate or shared server.

## Slack channel

`vystak-channel-slack` deploys as its own Container App alongside the agents:

```yaml
channels:
  - name: slack-main
    type: slack
    platform: aca
    config:
      stream_tool_calls: true     # live tool-call progress in Slack
    secrets:
      - {name: SLACK_BOT_TOKEN}
      - {name: SLACK_APP_TOKEN}
    agents: [assistant]
    default_agent: assistant
```

The channel container runs Slack Socket Mode and dispatches to peer agents via the A2A protocol over the agents' ACA ingress URLs. See [`channels/slack`](../channels/slack.md) for the full Slack surface, including `stream_tool_calls`.

A complete worked example lives at `examples/azure-slack-multi-agent/`.

## Destroying

```bash
vystak destroy                       # tears down the agent + channel container apps
vystak destroy --include-resources   # also deletes per-principal UAMIs and tagged shared infra
az group delete --name <rg> --yes    # nuke the entire RG (ACR, KV, Postgres, Log Analytics, etc.)
```

The CLI's `--include-resources` removes per-agent tagged resources but leaves shared infrastructure (ACR, Log Analytics, ACA env) intact in case multiple agents share an RG. To fully tear down a single-app RG, drop straight to `az group delete`.

## Limitations

- Single region per RG — multi-region failover isn't modeled in v1.
- ACA min replicas is `1` for now (no scale-to-zero) so the bot stays warm.
- Workspace persistence (`workspace.persistence: durable`) requires Azure Files and isn't yet wired through the Azure provider — Docker workspaces work today.
