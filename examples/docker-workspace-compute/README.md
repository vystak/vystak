# docker-workspace-compute

Coding assistant with a real workspace — persistent filesystem, shell
access, git, and an example custom tool (ripgrep-backed project search).

## What this demonstrates

- Workspace deployed as a separate Docker container
- fs/exec/git built-in services via the SSH+JSON-RPC channel
- User tool (`search_project`) running in the workspace container
- Workspace secrets + SSH keys delivered via Vault (v1 Hashi)

## Run

```bash
cp .env.example .env   # then edit
vystak apply
# ... the agent's endpoint is printed ...
vystak destroy          # preserves workspace data volume
vystak destroy --delete-workspace-data  # full teardown
```
