# docker-workspace-nodejs

JavaScript/TypeScript coding assistant running against a Node 20 workspace.

## What this demonstrates

- Workspace compute unit with a non-Python base image (`node:20-slim`)
- Multi-step `provision:` that mixes apt packages and npm globals
- fs/exec/git built-in services — no custom tool needed for a pure JS flow
- Persistent volume: `/workspace/` survives agent restart and rebuilds
- **Default secret delivery path** — secrets flow from `.env` into each
  container's environment via `--env-file` at `vystak apply` time. No Vault
  server, no sidecars, no unseal keys.

## Run

```bash
cp .env.example .env   # then edit to add your real ANTHROPIC_API_KEY
vystak plan            # preview what will be created
vystak apply           # build + start: 2 containers, ~3s cold start
# ... the agent's endpoint is printed ...
vystak destroy                           # preserves /workspace/ data
vystak destroy --delete-workspace-data   # full teardown
```

## Poke around

```bash
# shell into the running workspace
docker exec -it vystak-node-coder-workspace bash
# inside:
node --version       # v20.x
npm --version
tsc --version        # typescript global
git --version
rg --version
```

## Opting into Vault

If you want secret rotation, an audit log of reads, or shared secret
storage across multiple deploys, add a `vault:` block to `vystak.yaml`:

```yaml
vault:
  name: vystak-vault
  provider: docker
  type: vault
  mode: deploy
  config: {}
```

Next `vystak apply` will stand up a HashiCorp Vault container + per-principal
Vault Agent sidecars. The per-container isolation guarantee is unchanged —
Vault adds operational features, not isolation. The same `secrets:` block on
agent and workspace keeps working unchanged.
