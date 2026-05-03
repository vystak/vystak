---
title: Discord
sidebar_position: 3
---

# Discord channel

The Discord channel runs a Vystak bot connected to Discord's gateway over
WebSocket. Mention the bot in a guild text channel, DM it, or start a
thread — all messages route to your agents.

## Setup

1. Create a Discord application: <https://discord.com/developers/applications>.
2. Add a bot user to the application. Copy the bot token (you will use it as
   `DISCORD_BOT_TOKEN`).
3. Enable the **`MESSAGE CONTENT`** privileged intent in the bot settings.
   This is required to read message content (it is a one-checkbox setup;
   Discord verifies bots once they reach 100+ guilds).
4. Invite the bot to a server with at least the **`Send Messages`**, **`Read
   Message History`**, and **`Use Slash Commands`** permissions.

## Configuration

Add a Discord channel to your `agent.yaml`:

```yaml
name: hero
model: anthropic/claude-haiku-4-5-20251001
adapter: langchain
provider: docker
channels:
  - name: discord-prod
    type: discord
    agents: [hero]
    default_agent: hero
    # Optional:
    group_policy: open
    dm_policy: open
    thread:
      initial_history_limit: 20
      require_explicit_mention: false
    register_slash_commands: true
    welcome_message: "Hi! I'm Vystak. Mention me to start."
```

Pass the bot token via the host environment when running `vystak apply`:

```bash
export DISCORD_BOT_TOKEN=...
vystak apply
```

## Slash commands

Once the bot is in your server, the following slash commands are available
(they show up in Discord's UI as `/vystak-route`, `/vystak-status`, etc.):

| Command           | Purpose                              |
|-------------------|--------------------------------------|
| `/vystak-route`   | Bind this channel/thread to an agent |
| `/vystak-unroute` | Remove the binding                   |
| `/vystak-prefer`  | Set a default agent for this scope   |
| `/vystak-unprefer`| Remove the preference                |
| `/vystak-status`  | Show current routing                 |

## Threads + forum channels

Discord native threads and forum channels are treated the same way Slack
threads are: when a thread is bound (either explicitly with `/vystak-route`
or implicitly after the first reply), subsequent thread replies go to the
same agent. Set `thread.require_explicit_mention: true` to require an
@mention for follow-up replies.

## Limits

The Discord channel splits replies longer than 2000 characters into multiple
messages (Discord's per-message limit). Streaming and status reactions are
not yet supported.
