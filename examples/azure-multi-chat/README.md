# azure-multi-chat example

Same as `docker-multi-chat` but on Azure Container Apps. Two agents
(weather, time) + one chat channel, all on ACA sharing one resource
group, ACR, and managed environment.

This is the cross-platform proof: identical vystak.py shape, identical
plugin, different native runtime.

## Prereqs

- Azure CLI: `az login` completed
- Active subscription with rights to create RG / ACR / ACA environments
- Docker running locally (used to build & push images)
- Environment variables set in your shell or `.env`:

```
ANTHROPIC_API_KEY=<your-api-key>
ANTHROPIC_API_URL=https://api.minimax.io/anthropic   # or your endpoint
ANTHROPIC_MODEL_NAME=MiniMax-M2.7                     # or your model
AZURE_SUBSCRIPTION_ID=<your-subscription-id>
```

## Run

```bash
cd examples/azure-multi-chat
vystak apply
```

The CLI will:

1. Create RG `vystak-multi-chat-rg`, Log Analytics, ACR, ACA env.
2. Build + push both agent images, deploy as `weather-agent` and
   `time-agent` ACA apps (internal+external ingress).
3. Bake their resolved URLs into the chat container's `routes.json`.
4. Build + push the chat image, deploy as `channel-chat` ACA app with
   external ingress.

The summary prints the chat channel's external FQDN. Then:

```bash
# Replace FQDN below with the real one from the apply output
FQDN=channel-chat.<env-id>.eastus2.azurecontainerapps.io

curl -s https://$FQDN/health
curl -s https://$FQDN/v1/models

# Weather agent
curl -s -X POST https://$FQDN/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "vystak/weather-agent",
    "messages": [{"role": "user", "content": "weather in tokyo"}]
  }'

# Time agent
curl -s -X POST https://$FQDN/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "vystak/time-agent",
    "messages": [{"role": "user", "content": "what time is it?"}]
  }'
```

## Tear down

```bash
vystak destroy --include-resources
```

`--include-resources` removes the shared ACR / ACA env / Log Analytics
along with the three apps.

## What differs from docker-multi-chat

Only the `Platform` + `Provider`. Same agents, same chat channel, same
tools, same plugin. The channel plugin's generated FastAPI server is
identical byte-for-byte.
