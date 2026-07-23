# docker-slack-support-mcp — Slack support agent + MCP-powered research subagent

Two agents on local Docker behind one Slack channel:

- **support-agent** — answers support questions; delegates repo-research
  questions to its subagent via A2A.
- **research-agent** — carries a **remote MCP connection** to the public
  DeepWiki server (`https://mcp.deepwiki.com/mcp`, streamable HTTP, no
  auth) and uses its tools to answer questions about public GitHub repos.

What it demonstrates:

- Multi-agent (`subagents:`) delegation over A2A
- Remote MCP config in its simplest form — just `url:`, transport inferred
- Slack self-serve routing with two agents on one channel
  (`default_agent: support-agent`)

## Run it

```bash
cp .env.example .env   # ANTHROPIC_API_KEY/_URL + SLACK_BOT_TOKEN/_APP_TOKEN
vystak apply
```

Then in Slack: invite the bot and ask something like
*"how does langgraph implement checkpointing?"* — support-agent delegates
to research-agent, which consults DeepWiki.

`vystak destroy` tears everything down.
