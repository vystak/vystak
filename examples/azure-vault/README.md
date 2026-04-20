# Azure Key Vault — minimal example

One agent, model API key stored in Azure Key Vault.

## What this demonstrates

- `Vault` declaration at the top level (mode: `deploy` — vystak creates the vault)
- Secret materialization via ACA `secretRef` (no `.env` inside the running container)
- Secret bootstrap from local `.env` at `vystak apply` time
- Per-agent User-Assigned Managed Identity (UAMI) with `lifecycle: None` so
  the agent process cannot acquire a token for the identity

## Files

- `vystak.yaml` — declarative config (vault, platform, model, agent)
- `vystak.py` — equivalent Python-code-first config
- `.env.example` — template for the local `.env` used at apply time

## Run

```bash
cp .env.example .env     # then edit ANTHROPIC_API_KEY
vystak plan              # preview the vault/identity/secret/grant sections
vystak apply             # create vault, push secret, deploy ACA
vystak secrets list      # show declared secrets vs. vault state
vystak destroy           # tear down the resource group
```

## After apply

The container app runs with `ANTHROPIC_API_KEY` injected from Key Vault via
ACA's `secretRef` mechanism — no local `.env` file is ever baked into the
image or mounted into the container.
