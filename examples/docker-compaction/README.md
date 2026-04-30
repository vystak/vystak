# docker-compaction — local session-compaction smoke

Single agent with **session compaction enabled at a 5K context window** so
compaction fires after a handful of turns. Routes to both a chat channel
(port 8080, OpenAI-compatible) and Slack.

## What this exercises

- Layer 1 prune (always-on for tool outputs)
- Layer 2 autonomous summarization tool (LangChain middleware)
- Layer 3 threshold pre-call summarize — fires when prefill ≥ 0.7 × 5_000 = 3_500 tokens
- Manual `/v1/sessions/{thread_id}/compact` endpoint
- The chat REPL slash commands `/compact` and `/compactions`

## Prereqs

Copy the secrets template and fill it in:

```bash
cd examples/docker-compaction
cp .env.example .env
# edit .env with your real keys
```

`vystak apply` reads `.env` from the project directory and injects the
values into the agent + channel containers. The file is `.gitignore`d.

Required:
- `ANTHROPIC_API_KEY` — for both the agent and the summarizer
- `ANTHROPIC_API_URL` — `https://api.anthropic.com` or a proxy

Optional (only for the Slack channel):
- `SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN` — Socket Mode tokens

If you don't want Slack, delete the `slack-main` channel block from
`vystak.yaml` before applying.

Docker daemon must be running.

## Deploy

```bash
cd examples/docker-compaction
uv run vystak apply
```

This brings up:
- `vystak-chatty` (the agent container, port 8000 inside, exposed on a docker port)
- `vystak-resource-sessions-db` (Postgres container for session state + compactions table)
- `vystak-channel-chat` (port 8080 — OpenAI-compatible)
- `vystak-channel-slack-main` (Slack Socket Mode runner, only if SLACK_*_TOKEN set)

## Drive a conversation

### Via REPL (recommended)

```bash
uv run vystak-chat
> /connect http://localhost:8080
> Write me a 3-paragraph essay about the history of clocks.
> Now do the same for telescopes.
> What about microscopes?
> ...keep going for ~5-7 turns; each turn's instructions add ~200-400 tokens
> /compactions     # see what compactions have fired
> /compact focus on the topics covered    # force a manual summary with guidance
```

### Via curl

```bash
THREAD_ID=$(curl -s http://localhost:8080/v1/responses \
  -H 'content-type: application/json' \
  -d '{"model":"vystak/chatty","input":"hi","store":true}' | jq -r .id)
# subsequent turns: pass previous_response_id

# Inspect compactions:
curl http://localhost:8080/v1/sessions/$THREAD_ID/compactions | jq .

# Force compact:
curl -X POST http://localhost:8080/v1/sessions/$THREAD_ID/compact \
  -H 'content-type: application/json' \
  -d '{"instructions": "summarize the topics discussed"}'
```

### Via Slack

DM the bot or `@mention` it in any channel it's in. Each message is one
turn. After ~5-7 long messages, watch the agent's logs to see
`vystak.compaction.threshold` events fire.

## Verify compaction happened

```bash
docker exec -it vystak-resource-sessions-db psql -U postgres -c \
  "SELECT thread_id, generation, trigger, summarizer_model, input_tokens, output_tokens \
   FROM vystak_compactions ORDER BY thread_id, generation;"
```

You should see rows with `trigger='threshold'` after long conversations,
and `trigger='manual'` when you invoke `/compact`.

## Tuning

This example is calibrated for **fast dev iteration**, not realistic
production use:

- `context_window: 5000` — pretend the model has a 5K window so
  compaction fires after 5–10 turns instead of hundreds.
- `trigger_pct: 0.3` — fire at 30% of the (fake) window, i.e. 1500
  tokens. Tight enough that you'll see compaction within a single
  test session; the conservative-mode default is 0.75.
- `summarizer: claude-haiku-4-5-20251001` — Haiku is roughly 1/15 the
  cost of Sonnet, so summaries are cheap during dev.

For production use, drop `context_window` (so the real model context
applies — 200K for Claude Sonnet 4.x) and pick a preset:

```yaml
compaction:
  mode: conservative   # trigger_pct=0.75, keep_recent_pct=0.10
# or
compaction:
  mode: aggressive     # trigger_pct=0.60, keep_recent_pct=0.20
```

`trigger_pct` and `keep_recent_pct` behave the same way at any window
size — they're fractions of the resolved context window.

## Teardown

```bash
uv run vystak destroy
```
