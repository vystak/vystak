# azure-test-multi-channel

Azure-hosted equivalent of `examples/test-multi-channel`:
3 agents (assistant + weather + time) reachable via 3 channels
(Chat HTTP API, Slack, Discord) on Azure Container Apps with Key Vault.

## Setup

```bash
# Symlink to repo root .env (ANTHROPIC_API_KEY, SLACK_*, DISCORD_BOT_TOKEN).
ln -s ../../.env .env

# Login + set the subscription (one-time).
az login
export AZURE_SUBSCRIPTION_ID=...
```

## Deploy

```bash
uv run vystak apply
```

Provisions: resource group `vystak-test-multi-channel-rg`,
Log Analytics workspace, ACA Environment, ACR, Key Vault
(`vystak-test-mc-vault`), 3 agent Container Apps, 3 channel
Container Apps. ~5–10 minutes cold.

## Test the Chat HTTP API

After deploy, find the chat-api FQDN:

```bash
uv run vystak status
```

Then:

```bash
CHAT_URL=$(uv run vystak status --json | jq -r '.channels[] | select(.name=="chat-api") | .url')
curl -X POST "$CHAT_URL/v1/chat/completions" \
  -H 'Content-Type: application/json' \
  -d '{"model":"vystak/time-agent","messages":[{"role":"user","content":"what time is it?"}]}'
```

Slack and Discord bots come online automatically — @-mention them in
your workspace/server.

## Tear down

```bash
uv run vystak destroy
```

Removes all Azure resources (resource group + everything in it).
