# Docker + HashiCorp Vault — agent + workspace sidecar

Demonstrates the Hashi Vault backend on Docker: the Vault server runs as
its own container, per-principal AppRoles + Vault Agent sidecars render
scoped secrets into per-container volumes, and the main containers use
an entrypoint shim to source secrets into env before execution.

## What this demonstrates

- `Vault(type="vault", provider=docker, mode="deploy")` — vystak boots a
  production-mode Vault container
- Per-principal AppRole + policy — agent's AppRole can read only
  `ANTHROPIC_API_KEY`, workspace's can read only `STRIPE_API_KEY`
- Per-container shared volumes — the agent container cannot read the
  workspace's secrets even on the same Docker host
- `.env` bootstrap via `vystak secrets push`

## Run

```bash
cp .env.example .env   # then edit
vystak apply
vystak secrets list
vystak secrets push     # if you change values later
vystak destroy          # preserves Vault container + data
vystak destroy --delete-vault  # full teardown, unrecoverable
```

## Security note

`.vystak/vault/init.json` is created at first apply with the unseal
keys and root token — it is as sensitive as your `.env`. Keep it out
of backups you don't trust; it inherits the `.vystak/` gitignore.
