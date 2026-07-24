# docker-skills — folder skills + inline skills

One agent (`shop-agent`) demonstrating both skill forms:

- **Folder skill** `research` — packaged instructions in
  `skills/research/SKILL.md` (+ `sources.md` resource file). The agent's
  system prompt lists the skill's name and description; the full
  instructions load on demand via the `load_skill` tool, and resource
  files via `read_skill_file` (progressive disclosure).
- **Inline skill** `orders` — a tool bundle pointing at
  `tools/lookup_order.py`.

## Deploy

```bash
export ANTHROPIC_API_KEY=sk-ant-your-key-here
vystak apply
```

## Try it

```bash
curl -X POST http://localhost:8080/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"vystak/shop-agent","messages":[{"role":"user","content":"Research the best budget mechanical keyboard for me."}]}'
```

The agent calls `load_skill("research")`, follows the packaged workflow,
and reads `sources.md` for citation conventions. Ask "where is order 1001?"
to exercise the inline `orders` skill instead.

Edit any file under `skills/research/` and run `vystak plan` — the content
digest changes the agent hash, so the plan shows a redeploy.

## Tear down

```bash
vystak destroy
```
