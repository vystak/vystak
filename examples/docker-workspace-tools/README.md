# docker-workspace-tools

One agent (`analyst`) with a workspace seeded from `workspaces/dev/`,
driven entirely through the nine built-in workspace tools — no custom
tool code, no MCP server, just `fs`/`exec`/`git` over the SSH+JSON-RPC
channel described in
`docs/superpowers/specs/2026-07-24-workspace-tools-and-seed-design.md`.

## What this demonstrates

- **Seed folder convention** — `workspaces/<workspace-name>/` in the
  project dir (here `workspaces/dev/`, matching `workspace.name: dev` in
  `vystak.yaml`) is staged into the workspace image at `/vystak/seed/`
  and copied into `/workspace` by the container entrypoint on first
  boot. No schema field turns this on — the folder just has to exist.
- **Copy-if-absent semantics** — the entrypoint copy (`cp -rn`) only
  writes a seed file if the destination doesn't already exist. Files
  you edit inside the running workspace are never clobbered by a later
  apply; only seed files that are genuinely new to that workspace land.
- **Hash-triggered re-provision** — the seed folder's file paths and
  content join the workspace's deploy hash, so changing anything under
  `workspaces/dev/` and running `vystak apply` again is enough to
  trigger a rebuild — you don't have to touch `vystak.yaml`.
- **The nine built-in workspace tools** — exposed to the LLM
  automatically because the agent declares a `workspace:` block, no
  `tools:` entry or custom code required:
  - Filesystem: `read_file`, `write_file`, `edit_file`, `list_dir`
  - Execution: `run`, `shell`
  - Git: `git_status`, `git_diff`, `git_commit`

The agent's instructions point it at the seeded `analyze.sh` and
`data.csv`; a prompt like "analyze the data and write a report" exercises
`list_dir` → `read_file` → `run` → `write_file` end to end.

## Run

```bash
cd examples/docker-workspace-tools
echo "ANTHROPIC_API_KEY=sk-ant-your-key-here" > .env

vystak init --framework langchain-python --force .   # scaffolds the runtime template
vystak plan     # shows the agent + workspace container that will be created
vystak apply
# ... the agent's endpoint is printed ...

# Chat via the REPL (A2A under the hood)
vystak-chat
> analyze the data in /workspace and write your findings to report.md

# ...or hit the agent's A2A endpoint / agent card directly
curl -s http://localhost:<agent-port>/.well-known/agent.json | jq .

# Confirm the workspace was seeded and the report landed
docker exec vystak-analyst-workspace cat /workspace/data.csv
docker exec vystak-analyst-workspace cat /workspace/report.md

vystak destroy                            # preserves the workspace volume
vystak destroy --delete-workspace-data    # full teardown
```

## Try copy-if-absent yourself

```bash
# Hand-edit a file already inside the running workspace
docker exec vystak-analyst-workspace sh -c 'echo "hand-edited" >> /workspace/data.csv'

# Add a brand-new file to the seed folder and re-apply — new seed content
# changes the workspace hash, so this triggers a rebuild
echo "# scratch notes" > workspaces/dev/notes.txt
vystak apply

# The new seed file arrives; your hand edit to data.csv survives untouched
docker exec vystak-analyst-workspace cat /workspace/notes.txt
docker exec vystak-analyst-workspace cat /workspace/data.csv
```
