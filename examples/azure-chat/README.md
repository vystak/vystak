# azure-chat example

Deploys a chat channel on Azure Container Apps alongside an agent. Same
`vystak-channel-chat` plugin emits the same FastAPI server — the Azure
provider wraps it in an ACA container app.

This is the cross-platform proof: the chat plugin never knew Azure
existed, and the Azure provider never knew a chat channel could emit a
FastAPI server. They meet via `ChannelPlugin.generate_code(...)` +
`AzureChannelAppNode`.

## Prereqs

- Azure CLI installed and logged in: `az login`
- Active subscription with permission to create resource groups / ACR /
  ACA environments
- Docker running locally (used to build and push the image to ACR)
- `ANTHROPIC_API_KEY` exported

## Configure

Edit `vystak.py`:

- Replace `YOUR_SUBSCRIPTION_ID` with your real subscription ID.
- Optionally change `location` and `resource_group`.

## Run

```bash
export ANTHROPIC_API_KEY=sk-ant-...
cd examples/azure-chat
vystak apply
```

The CLI will:

1. Create the resource group, Log Analytics workspace, ACR, ACA
   environment (shared with the agent).
2. Build & push the agent image to ACR; deploy as ACA `weather-agent`.
3. Build & push the chat channel image to ACR; deploy as ACA
   `channel-chat` with an external FQDN.
4. Bake the agent's external URL into the chat container's `routes.json`
   so chat completions route to it.

Once deployed:

```bash
# The FQDN is shown in the summary, e.g. https://channel-chat.<env-id>.eastus2.azurecontainerapps.io
curl -s https://<fqdn>/health
curl -s https://<fqdn>/v1/models
curl -s -X POST https://<fqdn>/v1/chat/completions \
    -H "Content-Type: application/json" \
    -d '{
        "model": "vystak/weather-agent",
        "messages": [{"role": "user", "content": "hi"}]
    }'
```

## Tear down

```bash
vystak destroy --include-resources
```

`--include-resources` also removes the ACA environment, ACR, and Log
Analytics workspace when no other agents/channels share them.
