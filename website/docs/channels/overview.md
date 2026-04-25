---
title: Channels
sidebar_label: Overview
sidebar_position: 1
---

# Channels

A **channel** is how the outside world reaches your agents. Channels are sibling deployables to agents — they own their own platform, runtime, and routing policy. Agents stay pure computational units; channels declare which agents they dispatch to.

## Available channel types

| Type | Status | Use case |
|---|---|---|
| [`slack`](./slack) | Stable | Slack Socket Mode bot with self-serve runtime routing |
| `api` | Stable | OpenAI-compatible HTTP endpoint (`/v1/chat/completions`, `/v1/responses`) |
| `chat` | Stable | Browser-friendly chat UI |

## Common shape

Every channel block has the same skeleton:

```yaml
channels:
  - name: <unique-name>
    type: slack | api | chat
    platform: <platform-ref>
    secrets:
      - {name: <ENV_VAR_NAME>}
    # type-specific fields below
```

- **`name`** — unique identifier; appears in `vystak status`, `vystak destroy --name`, container labels.
- **`type`** — picks the channel plugin. New types are pluggable via `vystak.channels.register(...)`.
- **`platform`** — same `Platform` object used by agents; controls *where* the channel container runs (Docker, Azure Container Apps).
- **`secrets`** — environment variables the channel container needs (bot tokens, signing secrets). Resolved from `.env` or vault depending on the platform.

Type-specific fields are documented per channel:

- [Slack channel →](./slack)

## How channels and agents connect

The channel container is a separate process from your agent containers. They talk over the **A2A transport** — HTTP by default, NATS optionally — using the canonical name on the agent side and an entry in the channel's runtime route table.

```
┌─────────────────┐   A2A (HTTP/NATS)   ┌─────────────────┐
│  channel        │ ─────────────────►  │  agent          │
│  (slack/api/…)  │                     │  (langchain +   │
│                 │                     │   FastAPI)      │
└─────────────────┘                     └─────────────────┘
        ▲
        │ events from Slack / HTTP / etc.
```

The channel's `agents:` field declares which agents it can dispatch to. The exact dispatch logic depends on the channel:

- **Slack** routes per (team, channel, user) using a runtime SQLite store, populated via slash commands and a bot-invite welcome flow.
- **API** dispatches to the agent named in the request body's `model` field (`vystak/<agent-name>`).
- **Chat** mirrors the API channel with a UI.

## Lifecycle

```bash
vystak apply           # build + run the channel container alongside agents
vystak status          # health + binding info
vystak destroy         # stop and remove the channel container
                       # state volumes (e.g. Slack /data) preserved by default
```

For Slack, `vystak destroy --delete-channel-data` also removes the runtime bindings/preferences SQLite volume.
