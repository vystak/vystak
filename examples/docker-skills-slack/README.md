# docker-skills-slack — folder skill + inline skill + Slack channel

One agent (`shop-agent`) reachable from Slack, demonstrating both skill forms:

- **Folder skill** `research` — packaged instructions in
  `skills/research/SKILL.md` (+ `sources.md` resource file), loaded on
  demand via the `load_skill` / `read_skill_file` tools (progressive
  disclosure).
- **Inline skill** `orders` — a tool bundle pointing at
  `tools/lookup_order.py`.

The Slack channel runs as its own container (Socket Mode) and routes
messages to the agent over A2A.

## Prerequisites

A Slack app with Socket Mode enabled, a bot token (`xoxb-…`) and an app
token (`xapp-…`). See `examples/docker-slack/` for the app-manifest
walkthrough.

## Deploy

```bash
cat > .env <<'EOF'
ANTHROPIC_API_KEY=your-anthropic-api-key-here
SLACK_BOT_TOKEN=xoxb-your-bot-token-here
SLACK_APP_TOKEN=xapp-your-app-token-here
EOF
vystak apply
```

## Try it

In Slack, DM the bot (or mention it in a channel it's invited to):

- "Research the best budget mechanical keyboard for me." — the agent
  calls `load_skill("research")`, follows the packaged workflow, and
  reads `sources.md` for citation conventions.
- "Where is order 1001?" — exercises the inline `orders` skill via
  `lookup_order`.

Edit any file under `skills/research/` and run `vystak plan` — the
content digest changes the agent hash, so the plan shows a redeploy.

## Tear down

```bash
vystak destroy
```
