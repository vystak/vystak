# docker-shared-volume

Two agents — `coder` and `reviewer` — sharing one named workspace volume
(`team-code`). Demonstrates named-volume sharing across independent agent
workspaces, on top of the classic one-agent-one-workspace pattern shown in
`docker-workspace-compute`.

## What this demonstrates

- A top-level `volumes:` block (a peer of `providers`/`platforms`/`models`)
  declaring `team-code` as a named, persistent volume with
  `retention: retain`
- Two separate `workspace:` blocks — one per agent — both referencing the
  same volume via `volume: team-code` instead of the legacy per-agent
  implicit `persistence: volume` field
- Docker maps the named volume to a single Docker volume
  (`vystak-volume-team-code`) mounted at `/workspace` in *both* workspace
  containers — files the `coder` writes are immediately visible to the
  `reviewer`
- Retention semantics: `vystak destroy` leaves `team-code` in place;
  `vystak destroy --delete-workspace-data` only removes it once **neither**
  agent's workspace container references it any more — a volume still
  mounted by another agent's workspace is skipped

## Run

```bash
export ANTHROPIC_API_KEY=sk-ant-...
vystak apply
# ... both agents' endpoints are printed ...

# poke around — files written by one workspace are visible from the other
docker exec vystak-coder-workspace sh -c 'echo "hello" > /workspace/note.txt'
docker exec vystak-reviewer-workspace cat /workspace/note.txt

vystak destroy                            # preserves the shared team-code volume
vystak destroy --delete-workspace-data    # removes team-code only once both agents are destroyed
```

## Verifying the sharing

```bash
docker volume ls | grep vystak-volume-team-code
docker inspect vystak-coder-workspace --format '{{json .Mounts}}'
docker inspect vystak-reviewer-workspace --format '{{json .Mounts}}'
# both show the same Docker volume name mounted at /workspace
```
