# Azure Key Vault — workspace sidecar example

Agent + workspace sidecar. Demonstrates **LLM-side / tool-side secret
isolation**: the model-facing container holds only the key it needs to call
the LLM (`ANTHROPIC_API_KEY`), while tool-side secrets (`STRIPE_API_KEY`)
live exclusively in the workspace sidecar container. Each container has its
own UAMI with `lifecycle: None`, so neither process can impersonate the
other to fetch the sibling's secret.

## What this demonstrates

- Two per-container UAMIs (agent + workspace) with `lifecycle: None`
- Per-secret grant scoping: agent UAMI has read on `ANTHROPIC_API_KEY`
  only; workspace UAMI has read on `STRIPE_API_KEY` only
- `vystak.secrets.get("STRIPE_API_KEY")` inside a tool — the helper hits
  the sidecar's RPC socket, returning the environment value

## Files

- `vystak.yaml` — declarative config
- `vystak.py` — Python code-first equivalent
- `tools/charge_card.py` — example tool reading the Stripe key via the SDK
- `.env.example` — template for local apply-time values

## Run

```bash
cp .env.example .env     # then edit both keys
vystak plan              # preview the vault / identities / secrets / grants
vystak apply             # create vault + 2 UAMIs, push both secrets, deploy
vystak secrets list      # show declared secrets vs. vault state
vystak destroy           # tear down the resource group
```

## Why this layout

If you dropped `STRIPE_API_KEY` into the agent container alongside
`ANTHROPIC_API_KEY`, a prompt-injection exploit that coaxed the LLM into
reading its own env would leak the Stripe key to an attacker. By keeping
the billing credential behind an RPC boundary in a separate container, a
compromised LLM cannot see the key — only **call** `charge_card` with
arguments the tool itself validates.
