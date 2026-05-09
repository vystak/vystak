# heartbeat-agent

A minimal example showing periodic agent self-invocation. The `ops-bot`
agent runs every 30 minutes (Mon-Fri 9am-6pm Eastern), reads
`HEARTBEAT.md`, and posts an alert into the `standup-room` chat scope
unless the reply is `HEARTBEAT_OK`.

## Run

```bash
cd examples/heartbeat-agent
export ANTHROPIC_API_KEY=...
vystak apply

# Watch the chat-main container's logs to see heartbeats fire
docker logs -f chat-main
```

## Tweak

- Change `schedule` to `"* * * * *"` (every minute) for faster local feedback.
- Edit `HEARTBEAT.md` to refine the agent's check-in checklist.
- Set `isolated_session: false` to have the heartbeat appear in the
  `standup-room` history (vs. running silently in a synthetic session).

## Ack contract

The runtime drops replies that contain `HEARTBEAT_OK` and are at most 300
characters (configurable via `ack_max_chars`). Longer replies, or replies
without the sentinel, are delivered to `target_thread`.
