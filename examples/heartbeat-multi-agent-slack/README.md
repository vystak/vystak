# heartbeat-multi-agent-slack

Multi-agent setup demonstrating heartbeat → Slack delivery with OTEL telemetry.

## Topology

- **weather-agent** — calls `get_weather(city)` (wttr.in)
- **time-agent** — calls `get_time()` (UTC)
- **assistant-agent** — has `subagents: [weather-agent, time-agent]`. Heartbeat fires every 10 minutes, dispatches both subagents in parallel, and posts a 2-line digest into Slack channel `C0AV6PJ4VHU` (`vystack-channel-3`).
- **slack-main** channel routes all three agents; default = assistant.
- **vystak-otel** (auto-provisioned via `platform.telemetry.enabled: true`) collects OTLP traces from every container; Grafana UI on host port `3000`.

## Setup

```bash
cd examples/heartbeat-multi-agent-slack

# Required env vars
export ANTHROPIC_API_KEY=sk-ant-api03-...
export SLACK_BOT_TOKEN=xoxb-...
export SLACK_APP_TOKEN=xapp-...

vystak init --framework langchain-python --force .
vystak apply
```

The first apply provisions:
- 3 agent containers (`vystak-weather-agent`, `vystak-time-agent`, `vystak-assistant-agent`)
- 1 channel container (`vystak-channel-slack-main`)
- 1 telemetry container (`vystak-otel`)

## Watch heartbeats fire

```bash
docker logs -f vystak-channel-slack-main | grep heartbeat
```

You should see `heartbeat.fired` every 10 minutes and a corresponding post in `#vystack-channel-3`.

For faster feedback, edit `vystak.yaml` and change `schedule: "*/10 * * * *"` to `"* * * * *"` (every minute), then `vystak apply` again. The hash will change and the slack-channel container will redeploy with the new schedule.

## Watch the OTLP traces

Open http://localhost:3000 (anonymous viewer) → Explore → Tempo → search by service name `vystak-channel-slack` or `vystak-assistant-agent`. Each heartbeat fire emits a span tree spanning channel → agent → subagents.

## Teardown

```bash
vystak destroy
```

## Why the heartbeat works on Slack

The heartbeat synthesizes an `InboundEvent` with no real Slack `say` callable. The Slack channel runtime detects `metadata["heartbeat"]=True` on the delivery event and uses `app.client.chat_postMessage(channel=event.scope_id, text=reply.text)` directly instead of the user-context-bound `say`. See `vystak-channel-slack/runtime.py::post_reply`.
