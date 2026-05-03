---
title: Channel Runtime — Internals
sidebar_position: 99
---

# `vystak-channel-runtime`

`vystak-channel-runtime` is the shared library every channel container uses.
If you want to add a new channel (Telegram, Teams, Matrix, ...), this is
the surface to subclass.

## Architecture

Each channel container imports `vystak_channel_runtime` and runs a subclass
of `ChannelRuntime`. The base class owns the message lifecycle as a
template method:

```
parse_event → authorize → resolve_route → fetch_history
            → before_call → call_agent → post_reply → after_reply
```

`authorize`, `resolve_route`, and `call_agent` are implemented on the base.
`parse_event`, `post_reply`, `start`, and `stop` are abstract — subclasses
implement them. Optional hooks (`fetch_history`, `before_call`,
`after_reply`, `on_no_route`, `on_agent_error`) default to no-ops.

## Writing a new channel

1. Subclass `ChannelRuntime`. Implement `start`, `stop`, `parse_event`,
   `post_reply`. Override optional hooks as needed.
2. Build a `__main__.py` that reads `channel_config.json` and `routes.json`,
   then calls `vystak_channel_runtime.launch(MyRuntime, config, routes)`.
3. Build a `ChannelPlugin` subclass that emits `Dockerfile`,
   `requirements.txt`, `channel_config.json`, `routes.json`. Set
   `entrypoint = "python -m my_package"`.

See `vystak-channel-discord` for a complete example.

## Storage

`ChannelStore` defines a generic interface keyed by
`(channel_type, scope_id, thread_id)`. Default implementations:

- `MemoryChannelStore` — for tests / ephemeral deployments.
- `SqliteChannelStore` — single-file SQLite (`aiosqlite`).
- `PostgresChannelStore` — `asyncpg` pool.

Pick one via `channel_config.json`'s `state` key:

```json
{"state": {"type": "sqlite", "path": "/data/channel.db"}}
```

## Agent client

`AgentClient` is a Protocol. The default `A2AAgentClient` speaks A2A
JSON-RPC over HTTP. To integrate a different protocol (e.g. media bridge for
voice channels), subclass `AgentClient`, then inject it into your runtime
via the `agent_client=` constructor arg.

## Test fixtures

The `/test/event` synthetic-dispatch endpoint, gated by
`VYSTAK_TEST_EVENTS=1`, lets you POST a JSON-shaped `InboundEvent` directly
into your runtime without needing a live platform connection. Used by both
unit and release-cell tests.
