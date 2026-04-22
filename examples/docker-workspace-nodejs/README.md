# docker-workspace-nodejs

JavaScript/TypeScript coding assistant running against a Node 20 workspace.

## What this demonstrates

- Workspace compute unit with a non-Python base image (`node:20-slim`)
- Multi-step `provision:` that mixes apt packages and npm globals
- fs/exec/git built-in services — no custom tool needed for a pure JS flow
- Persistent volume: `/workspace/` survives agent restart and rebuilds

## Run

```bash
cp .env.example .env   # then edit to add your real ANTHROPIC_API_KEY
vystak plan            # preview what will be created
vystak apply           # build + start: vault, workspace, agent
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
