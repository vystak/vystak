# Channel Runtime + Discord Channel — Design

**Date:** 2026-05-02
**Status:** Approved (brainstorm complete; awaiting implementation plan)

## Summary

Two coupled changes:

1. Extract a new shared package `vystak-channel-runtime` that defines the
   runtime shape every channel container follows (event ingestion → routing
   → agent call → reply → state persistence). Retrofit `vystak-channel-slack`
   and `vystak-channel-chat` onto it without changing their user-visible
   behavior.
2. Add `vystak-channel-discord` as the first channel built natively on the
   new runtime. Slack-parity feature set minus streaming and status
   reactions (deferred).

Concurrent architectural pivot: channel packages stop emitting Python
source. Each channel package is a real, pip-installable library with a
`__main__.py` entrypoint. The plugin's `generate_code()` emits only
configuration files plus a generic Dockerfile.

## Goals

- Eliminate duplicated runtime logic across channels (today: Slack hand-rolls
  routing, store, allow-from policy, A2A client; Chat reinvents what little
  it shares; Discord would have repeated the cycle a third time).
- Make channel packages ordinary Python libraries — importable, unit-testable
  in-process, runnable with `python -m vystak_channel_<type>` for local
  debugging. Today the runnable code only exists as multi-thousand-character
  strings inside `server_template.py`.
- Add Discord as a first-class channel with feature parity to Slack on the
  routing/UX core (mentions, DMs, slash commands, threads, allow-from,
  channel overrides, welcome on bot-join).
- Keep the existing three-axis design intact: framework adapter, platform
  provider, channel adapter remain orthogonal.

## Non-goals

- Discord streaming (rate-limited edit-in-place during agent generation).
  Deferred to a follow-up. Slack's streaming work over the past month
  (`b3519c5`, `a90b1fe`, `cc58459`) shows the pattern needs more iteration
  per platform than is wise to bundle here.
- Discord status reactions on the user's original message. Deferred for the
  same reason.
- Discord voice / stage channels. Different `ChannelType` entirely (the enum
  already declares `voice`).
- Discord HTTP Interactions transport. Gateway-only for now (matches Slack's
  Socket Mode UX — no public URL needed).
- Migration of existing Slack `routes.db` data into the new generic schema.
  Fresh schema; documented as breaking change.
- Changes to `vystak.providers.base.ChannelPlugin` itself (the build-time
  ABC). Stays where it lives in core.
- Changes to `vystak-adapter-langchain` codegen. Agents continue to ship as
  generated source; only channels move off codegen.
- TypeScript port. None of the TS channel packages are implemented yet; this
  is Python-only.

## Architecture

### Package layout

```
packages/python/
├── vystak                       # unchanged — ChannelPlugin ABC stays here
├── vystak-channel-runtime       # NEW — runtime base, agent client, store
├── vystak-channel-api           # unchanged stub
├── vystak-channel-chat          # retrofitted onto runtime
├── vystak-channel-slack         # retrofitted onto runtime
└── vystak-channel-discord       # NEW — first native runtime consumer
```

### Dependency direction

```
vystak (schema, ChannelPlugin ABC, hash, providers)
    ▲
    │
vystak-channel-runtime  (depends on: vystak, httpx, aiosqlite, asyncpg)
    ▲
    │
vystak-channel-{slack,chat,discord}  (each adds: its platform SDK)
```

`vystak` core gains zero new dependencies. Channel SDKs (`slack-bolt`,
`discord.py`, `fastapi`) live only in their channel package. The runtime
lib has no SDK dependencies.

### Three-axis placement

```
Channel Adapter (HOW users reach it)
├── vystak-channel-api       — stub, unchanged
├── vystak-channel-chat      — retrofitted onto ChannelRuntime
├── vystak-channel-slack     — retrofitted onto ChannelRuntime
└── vystak-channel-discord   — NEW, built on ChannelRuntime
                                    │
                                    ▼
                        vystak-channel-runtime
                                    │
                ┌───────────────────┴────────────────────┐
                ▼                                        ▼
        AgentClient (Protocol)                   ChannelStore (Protocol)
        └─ A2AAgentClient (default)              ├─ MemoryChannelStore
                                                 ├─ SqliteChannelStore
                                                 └─ PostgresChannelStore
```

## `ChannelRuntime` contract

`vystak_channel_runtime.runtime.ChannelRuntime` is an abstract base class
implementing the message lifecycle as a template method. Async throughout.

### Lifecycle

Subclass implements:

- `async start() -> None` — connect to platform (Discord gateway, Slack
  Socket Mode, FastAPI uvicorn).
- `async stop() -> None` — disconnect cleanly.

### Pipeline (template method)

```python
async def handle_event(self, raw_event: Any) -> None:
    event = self.parse_event(raw_event)
    if not await self.authorize(event):
        return
    route = await self.resolve_route(event)
    if route is None:
        await self.on_no_route(event)
        return
    history = await self.fetch_history(event)
    await self.before_call(event, route)
    try:
        reply = await self.call_agent(event, route, history)
    except AgentCallError as exc:
        await self.on_agent_error(event, route, exc)
        return
    await self.post_reply(event, route, reply)
    await self.after_reply(event, route, reply)
```

### `InboundEvent` (Pydantic model in runtime lib)

```python
class InboundEvent(BaseModel):
    channel_type: ChannelType
    scope_id: str        # team_id (Slack) | guild_id/channel_id (Discord) | session_id (Chat)
    thread_id: str | None
    user_id: str
    text: str
    is_dm: bool
    mentions_bot: bool
    metadata: dict       # platform-specific extras subclass needs later
    raw: Any             # original SDK event, opaque to base
```

### Base owns (not normally overridden)

- `authorize()` — applies `allow_from`, `allow_bots`, `require_mention`,
  `dm_policy`, `group_policy` from the channel config.
- `resolve_route()` — order: `channel_overrides[scope_id]` → `thread_bindings`
  via `ChannelStore` → `default_agent`. Same logic Slack's current
  `resolver.py` encodes. All channels share identical routing semantics; no
  drift possible.
- `call_agent()` — picks `AgentClient` impl based on `agent_protocol`;
  invokes `send_turn` or `stream_turn`; handles transient retry (3×
  exponential backoff for 5xx / connection errors / timeouts).

### Subclass must implement

- `parse_event(raw)` — platform event → `InboundEvent`. Raises sentinel
  `SkipEvent` for events to ignore (own messages, system messages, voice
  events).
- `post_reply(event, route, reply)` — actually send reply back to platform.
- `start()` / `stop()`.

### Subclass may optionally override (default no-op)

- `fetch_history(event)` — Slack/Discord override to pull thread replies;
  Chat does not need it.
- `before_call(event, route)` — placeholder posting, status setup.
- `after_reply(event, route, reply)` — persist binding, clear status.
- `on_no_route(event)` — UX for "no agent bound to this channel/thread."
- `on_agent_error(event, route, exc)` — UX for agent failures.

### Configuration

`ChannelRuntime.__init__(config: dict, routes: dict, store: ChannelStore)`.

`config` is the existing `channel_config.json` shape Slack already produces,
plus two added keys:

- `channel_type: str` — literal channel type string.
- `agent_protocol: str` — was implicit before; now explicit.

All existing Slack `channel_config.json` files are forward-compatible — the
runtime fills in defaults if the new keys are missing.

## `AgentClient` port

`vystak_channel_runtime.agent_client.AgentClient` is a Protocol:

```python
class AgentClient(Protocol):
    async def send_turn(
        self,
        agent_url: str,
        text: str,
        thread_id: str,
        history: list[Message] | None = None,
        metadata: dict | None = None,
    ) -> AgentReply: ...

    async def stream_turn(
        self,
        agent_url: str,
        text: str,
        thread_id: str,
        history: list[Message] | None = None,
        metadata: dict | None = None,
    ) -> AsyncIterator[AgentChunk]: ...
```

`AgentReply`, `AgentChunk`, and `Message` are Pydantic models defined in
`vystak_channel_runtime.types` — `AgentReply` carries `text`, `tool_calls`,
`finish_reason`, and a raw passthrough; `AgentChunk` is the streaming
delta variant; `Message` matches the A2A history shape (`role`, `content`).

### Default impl: `A2AAgentClient`

- `send_turn` → JSON-RPC `tasks/send` over HTTP via `httpx.AsyncClient`.
- `stream_turn` → JSON-RPC `tasks/sendSubscribe` over SSE.
- Owns retry policy (3× exponential backoff on 5xx / connection errors /
  timeouts), structured logging, request timeouts (30s default,
  configurable via channel config).
- Reads `agent_url` from `routes.json` (already produced by every channel
  plugin today).

### Selection logic in `ChannelRuntime`

| `agent_protocol` | Client used                          |
|------------------|--------------------------------------|
| `a2a-turn`       | `A2AAgentClient.send_turn`           |
| `a2a-stream`     | `A2AAgentClient.stream_turn`         |
| `media-bridge`   | `NotImplementedError` (voice ships later) |

Subclasses can inject a different `AgentClient` via constructor argument
(this is how unit-test mocking works — see Testing).

## `ChannelStore` schema and impls

### Protocol

```python
class ChannelStore(Protocol):
    async def get_thread_binding(
        self, channel_type: str, scope_id: str, thread_id: str
    ) -> str | None: ...
    async def set_thread_binding(
        self, channel_type: str, scope_id: str, thread_id: str, agent_name: str
    ) -> None: ...
    async def delete_thread_binding(
        self, channel_type: str, scope_id: str, thread_id: str
    ) -> None: ...
    async def get_route_pref(
        self, channel_type: str, scope_id: str
    ) -> str | None: ...
    async def set_route_pref(
        self, channel_type: str, scope_id: str, agent_name: str
    ) -> None: ...
    async def delete_route_pref(
        self, channel_type: str, scope_id: str
    ) -> None: ...
    async def list_thread_bindings(
        self, channel_type: str, scope_id: str | None = None
    ) -> list[ThreadBinding]: ...
    async def close(self) -> None: ...
```

### Generic schema (SQLite + Postgres)

```sql
CREATE TABLE thread_bindings (
    channel_type TEXT NOT NULL,
    scope_id     TEXT NOT NULL,
    thread_id    TEXT NOT NULL,
    agent_name   TEXT NOT NULL,
    user_id      TEXT,
    created_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (channel_type, scope_id, thread_id)
);

CREATE TABLE route_prefs (
    channel_type TEXT NOT NULL,
    scope_id     TEXT NOT NULL,
    agent_name   TEXT NOT NULL,
    created_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (channel_type, scope_id)
);

CREATE INDEX idx_thread_bindings_scope
    ON thread_bindings (channel_type, scope_id);
```

### Impls

- `MemoryChannelStore()` — dict-backed, loses state on restart. Test
  default.
- `SqliteChannelStore(path: str)` — `aiosqlite`, single-file. Default for
  dev / single-container deployments.
- `PostgresChannelStore(dsn: str)` — `asyncpg`. For multi-container or HA
  deployments.

### Factory

```python
def make_channel_store(state_config: dict | None) -> ChannelStore: ...
```

Reads `Service(**state_config)`-style dict, returns the right impl.
`None` → `MemoryChannelStore` (test default).

### Schema management

DDL applied idempotently on `__init__` (`CREATE TABLE IF NOT EXISTS`). No
migration framework for v1. If schema changes later, add a `schema_version`
table at that point. YAGNI now.

### Mapping for existing channels

| Channel | `channel_type` | `scope_id`                          | `thread_id`                          |
|---------|----------------|-------------------------------------|--------------------------------------|
| Slack   | `slack`        | `team_id`                           | `channel_id:thread_ts`               |
| Discord | `discord`      | `guild_id/channel_id` (or `dm/{user_id}`) | `discord_thread_id` or message_id |
| Chat    | `chat`         | session originator (e.g. `vystak-chat:{user_id}`) | `session_id`              |

## No-codegen pivot — package shape

Channel packages stop emitting Python source. Each channel package is a
real importable library; the deploy artifact becomes config + Dockerfile.

### `__main__.py` (each channel package)

```python
import json, os
from vystak_channel_runtime import launch
from vystak_channel_<type>.runtime import <Type>ChannelRuntime

def main() -> None:
    cfg_dir = os.environ.get("VYSTAK_CONFIG_DIR", "/etc/vystak")
    config = json.load(open(f"{cfg_dir}/channel_config.json"))
    routes = json.load(open(f"{cfg_dir}/routes.json"))
    launch(<Type>ChannelRuntime, config, routes)

if __name__ == "__main__":
    main()
```

### Plugin's `generate_code()` after the pivot

Returns:

- `channel_config.json` — same shape as today (plus `channel_type`,
  `agent_protocol` keys).
- `routes.json` — unchanged.
- `Dockerfile` — generic, ~10 lines:
  ```dockerfile
  FROM python:3.11-slim
  RUN pip install --no-cache-dir vystak-channel-discord==<pinned-version>
  COPY channel_config.json routes.json /etc/vystak/
  ENTRYPOINT ["python", "-m", "vystak_channel_discord"]
  ```
  `<pinned-version>` is substituted by the plugin at codegen time using
  the channel package's installed version (`importlib.metadata.version`),
  so the running container exactly matches what was installed when
  `vystak apply` ran.
- `requirements.txt` — single line: `vystak-channel-discord==<pinned-version>`.

`entrypoint` field on `GeneratedCode` becomes `"python -m vystak_channel_<type>"`.

### `vystak-channel-runtime.launcher`

```python
def launch(runtime_cls: type[ChannelRuntime], config: dict, routes: dict) -> None:
    store = make_channel_store(config.get("state"))
    runtime = runtime_cls(config=config, routes=routes, store=store)
    asyncio.run(runtime.start())
```

### Provider impact

Providers (`vystak-provider-docker`, `vystak-provider-azure`) consume
`GeneratedCode(files: dict[str, str], entrypoint: str)`. They write the
files to a build context and run `docker build`. They do not introspect
filenames or content. The pivot is invisible to providers — `files` simply
no longer contains `.py` keys, and `entrypoint` is now a shell command
string instead of a Python filename.

One verification needed during implementation: the Docker provider's
existing handling of `entrypoint` (today it threads into the Dockerfile via
`CMD`) works with both forms. Confirmed by inspection; flagged in the plan
as "verify in phase 1."

## `vystak-channel-discord` package

### Layout

```
packages/python/vystak-channel-discord/
├── pyproject.toml          # deps: vystak, vystak-channel-runtime, discord.py>=2.4
├── README.md
├── src/vystak_channel_discord/
│   ├── __init__.py
│   ├── __main__.py         # entrypoint
│   ├── plugin.py           # DiscordChannelPlugin (build-time)
│   ├── runtime.py          # DiscordChannelRuntime (subclass of ChannelRuntime)
│   ├── server_template.py  # DOCKERFILE + REQUIREMENTS only (no SERVER_PY)
│   ├── commands.py         # /vystak slash-command handlers
│   ├── welcome.py          # bot-join welcome + auto-bind
│   └── threads.py          # thread + forum channel logic
└── tests/
    ├── test_plugin.py
    ├── test_runtime.py
    ├── test_commands.py
    ├── test_welcome.py
    └── release/
        └── test_*_discord_*.py
```

### `DiscordChannelPlugin` (build-time)

- `type = ChannelType.DISCORD` (new enum value).
- `default_runtime_mode = SHARED`.
- `agent_protocol = A2A_TURN` (streaming deferred).
- `config_schema = DiscordChannelConfig` with: `port: int = 8080` (for
  `/test/event` + health), `application_id: str | None`,
  `register_slash_commands: bool = True`.
- `generate_code()` emits `channel_config.json`, `routes.json`,
  `Dockerfile`, `requirements.txt`. No `.py`. `entrypoint="python -m
  vystak_channel_discord"`.
- `thread_name(event)` →
  `f"thread:discord:{guild_id}:{channel_id}:{thread_id_or_root}"`.
- `health_check()` → matches Slack's shape.

### `DiscordChannelRuntime(ChannelRuntime)`

- `start()` → instantiates `discord.Client(intents=Intents(guild_messages=True,
  dm_messages=True, message_content=True, guilds=True, members=False))`,
  registers `on_message` and `on_interaction` event handlers, calls
  `client.start(token)`. Token read from env (`DISCORD_BOT_TOKEN`).
- `stop()` → `client.close()`.
- `parse_event(raw)` → for `discord.Message`, builds `InboundEvent`:
  - `is_dm` from `isinstance(channel, DMChannel)`.
  - `mentions_bot` from `client.user in raw.mentions`.
  - `scope_id` from `f"{guild_id}/{channel_id}"` for guilds,
    `f"dm/{user_id}"` for DMs.
  - `thread_id` from `raw.thread.id` if message is in a thread, else
    `raw.id` for root.
  - Raises `SkipEvent` for own messages, system messages, voice events.
- `post_reply(event, route, reply)` → `await raw_channel.send(reply.text)`.
  In a thread: posts in the thread. Splits messages > 2000 chars (Discord
  limit) into multiple sends.
- `fetch_history(event)` → if event is in a thread, fetches up to
  `thread.initial_history_limit` prior messages via `channel.history(limit=N)`,
  mapped into A2A `Message` shape.
- `before_call(event, route)` → posts `Responding…` placeholder if config
  enables it; stores message id on `event.metadata['placeholder_id']`.
- `after_reply(event, route, reply)` → persists thread binding via
  `ChannelStore.set_thread_binding(...)`. Deletes placeholder if posted.
- `on_no_route(event)` → posts configured "no agent bound" message (matches
  Slack commit `601a4cf`).
- `on_agent_error(event, route, exc)` → posts truncated error in a thread
  reply.

### Slash commands (`commands.py`)

`/vystak route|prefer|status|unroute|unprefer` — same surface Slack got in
commit `ac2d980`. Implemented via `discord.app_commands` if
`register_slash_commands=True`. Routes through `ChannelStore` (no
Discord-specific state needed). Slash-command interactions arrive via the
gateway as `INTERACTION_CREATE` events (gateway-only transport).

### Welcome / auto-bind (`welcome.py`)

- `on_guild_join` → if exactly one agent declared, auto-bind it for that
  guild's default channel (or guild-wide via `route_prefs`). Mirrors Slack
  commit `3ab6cad`.
- Posts welcome message (configurable) when bot is added to a channel via
  `on_guild_channel_create` heuristic (Discord doesn't have a clean "bot
  joined this channel" event).

### Threads (`threads.py`)

- Detects whether a message is in a thread (`raw.thread is not None` or
  `raw.channel.type in [ThreadType, ForumType]`).
- Forum channels treated as threaded by default.
- `thread.require_explicit_mention` semantics from the channel config
  respected — if true, mid-thread messages without a bot mention are
  ignored.

### MVP scope (in)

- Mentions in guild text channels.
- Direct messages.
- Slash commands (`/vystak ...`).
- Threads (Discord native + forum channels).
- `allow_from` user/role allowlists.
- Per-channel agent overrides.
- Welcome on bot-join + single-agent auto-bind.

### MVP scope (out — deferred)

- Streaming (edit-in-place during agent generation).
- Status reactions on user's original message.
- Voice channels (different `ChannelType`).
- Stage channels.
- User/message context-menu commands.
- HTTP Interactions transport (gateway-only for v1).

## Slack and Chat retrofit

Behavior-preserving. Existing test suites are the gates.

### `vystak-channel-slack` retrofit

- `__main__.py` (new) — launches `SlackChannelRuntime`.
- `runtime.py` (new) — `SlackChannelRuntime(ChannelRuntime)`. Owns
  `parse_event` (Bolt event → `InboundEvent`), `post_reply`
  (`client.chat_postMessage`), `fetch_history` (existing
  `conversations.replies` logic from commit `1fc9ddf`), plus optional hooks
  for placeholder posting / status reactions / streaming.
- `server_template.py` — `SERVER_PY` blob deleted (multi-KB string).
  `DOCKERFILE` shrinks to generic.
  `REQUIREMENTS = "vystak-channel-slack==<version>"`.
- `plugin.py` — `generate_code()` emits configs + Dockerfile only;
  `entrypoint="python -m vystak_channel_slack"`. `channel_config.json` shape
  unchanged.
- Existing modules collapse:
  - `resolver.py` → deleted; logic moves into base
    `ChannelRuntime.resolve_route()`. Existing `test_resolver.py` re-pointed
    at runtime lib.
  - `store.py` → deleted; replaced by `vystak_channel_runtime` store impls.
    `test_store.py` re-pointed.
  - `commands.py`, `welcome.py`, `threads.py` → kept as Slack-specific
    modules called from `SlackChannelRuntime` hooks.
- Bolt entrypoint stays Bolt-shaped; Socket Mode connection lifecycle
  preserved exactly.

### `vystak-channel-chat` retrofit

- `__main__.py` (new) — launches `ChatChannelRuntime`.
- `runtime.py` (new) — `ChatChannelRuntime(ChannelRuntime)`. `start()` runs
  uvicorn against an internal FastAPI app whose request handler turns each
  `/v1/chat/completions` request into an `InboundEvent` and feeds it into
  `runtime.handle_event()`. Reply propagated back to the HTTP response
  (synchronous response model).
- `fetch_history` no-op (Chat is stateless per request; history comes in the
  request body).
- `before_call` / `after_reply` no-ops.
- Inherits routing / authorize / agent client / store from base. Chat gains
  routing prefs + thread bindings for free, opt-in via
  `channel_config.state` (existing Chat: no state by default).
- `server_template.py` — same shrinkage as Slack/Discord.

### `/test/event` synthetic-dispatch endpoint

Currently lives in Slack's `server_template.py` (commit `948db33`). Moves
into `vystak-channel-runtime` as an opt-in HTTP endpoint, gated by
`VYSTAK_TEST_EVENTS=1`. POST `/test/event` with a JSON-shaped `InboundEvent`
invokes `handle_event()` directly — no platform SDK required. All channels
get it for free in dev/test; production deploys leave the env var unset.

### Risk mitigation

The Slack channel commit log shows ~30 commits in the past few weeks with
subtle behavior tweaks (memory scoping, retry behavior, thread placeholders,
table flattening). The retrofit must preserve every one. Plan: existing
Slack test suite is the gate. Anything that breaks a Slack test is a
retrofit bug; if a behavior we want to preserve is not test-covered, write
the test first then retrofit.

## Migration and breaking changes

Documented in CHANGELOG; single release.

1. **Slack thread bindings + route prefs reset.** Existing `routes.db`
   (SQLite) and `routes` table (Postgres) ignored. Schema is fresh per the
   new `(channel_type, scope_id, thread_id)` shape. Users re-route via
   `/vystak route ...` after upgrade — auto-bind-on-mention repopulates
   organically.
2. **`channel_config.json` shape additions.** New keys: `channel_type`,
   `agent_protocol`. Existing keys all preserved. Old configs are
   forward-compatible — runtime defaults if keys are missing.
3. **Container entrypoint change.** Old: `python server.py`. New:
   `python -m vystak_channel_<type>`. `vystak apply` regenerates the
   Dockerfile so most users do not notice. Anyone with custom downstream
   Dockerfiles needs to update.
4. **`ChannelType.DISCORD` added.** Non-breaking for consumers; mentioned
   for completeness.

Non-breaking but worth flagging:

- `vystak-channel-runtime` is a new PyPI package and a new transitive
  dependency of every channel package. `pip install vystak-channel-slack`
  pulls it in automatically.
- Channel packages become real importable libraries — anyone can
  `from vystak_channel_discord.runtime import DiscordChannelRuntime` and
  embed it directly. Previously impossible.

## Hash-tree contributions

`vystak.hash` adds two new fields to a channel's hash:

- `channel_package_version` — pinned semver of `vystak-channel-<type>`.
- `channel_runtime_version` — pinned semver of `vystak-channel-runtime`.

Both flow into `AgentHashTree`. A package bump triggers `vystak plan` to
mark the channel as drifted, which triggers a redeploy on `apply`.

## Testing strategy

Three layers.

### 1. `vystak-channel-runtime` unit tests

Exercise the template-method pipeline via a `MockChannelRuntime` (a test
fixture, not a production class) whose `parse_event` / `post_reply` /
`start` / `stop` are trivial.

Coverage:

- `authorize()` with every combination of `allow_from`, `allow_bots`,
  `require_mention`, `dm_policy`, `group_policy`.
- `resolve_route()` with overrides + bindings + default agent + missing
  route.
- Retry behavior in `A2AAgentClient`.
- `ChannelStore` round-trips against `MemoryChannelStore` and
  `SqliteChannelStore` (parametrised).
- One full pipeline test running `handle_event()` end-to-end against mocks.

Goal: ~80% of channel logic now lives here and is tested here.

### 2. Per-channel unit tests

Each channel package tests only its own hooks: `parse_event` for a few
representative platform-shaped events, `post_reply` against a mocked SDK
client, `fetch_history` if implemented, plus channel-specific modules
(`commands.py`, `welcome.py`, `threads.py`).

No re-testing of routing / authorize / store — that is the runtime lib's
job. Slack's existing test suite shrinks substantially in the retrofit; the
"behavior preserved" gate is `pytest packages/python/vystak-channel-slack
-v` stays green.

### 3. Release-cell integration tests

Each channel ships `tests/release/` cells that spin a real container and
exercise V1–V9 verification dimensions. Slack cells unchanged. Discord adds
4 cells gated on `release_discord` + `DISCORD_BOT_TOKEN`:

- `D9_discord_default_chat_http` — single agent, default routing, mention +
  reply.
- `D10_discord_dm_chat_http` — DM-only flow, no guild.
- `D11_discord_threads` — thread-follow with `require_explicit_mention=False`.
- `D12_discord_postgres` — Postgres-backed `ChannelStore` (covers new
  schema's Postgres path).

### CI gates

Per CLAUDE.md, the four live ones:

- `lint-python` — runtime lib + Discord package both pass `ruff check`.
- `test-python` — all unit tests pass with `-m 'not docker'`. New
  `release_discord` marker excluded by default.
- `typecheck-typescript` — N/A (no TS changes).
- `test-typescript` — N/A.

`docker`-marked tests for Discord run in the existing Docker integration
job. `release_discord` cells gated locally on `DISCORD_BOT_TOKEN`; CI does
not have the token, so cells auto-skip in CI (matches `release_slack`).

## Rollout sequencing — Approach A

| Phase | Scope | Gate |
|-------|-------|------|
| 1 | Create `vystak-channel-runtime` skeleton: package layout, `ChannelRuntime` ABC, `InboundEvent`, `AgentClient` Protocol + `A2AAgentClient`, `ChannelStore` Protocol + 3 impls, `launch()` helper. Unit tests for everything except SDK integration. | Runtime lib passes `lint-python` + `test-python`; `MockChannelRuntime` end-to-end test green. |
| 2 | Retrofit `vystak-channel-slack` onto runtime. Behavior-preserving. Existing Slack test suite is the gate. Delete `SERVER_PY` blob, `resolver.py`, `store.py`. New thin Slack `runtime.py`, `__main__.py`, slim `Dockerfile`. | `pytest packages/python/vystak-channel-slack -v` stays green. Manual smoke (one DM, one mention, one threaded reply). |
| 3 | Retrofit `vystak-channel-chat`. | `pytest packages/python/vystak-channel-chat -v` stays green. |
| 4 | Build `vystak-channel-discord`: package skeleton, `DiscordChannelRuntime`, `commands.py`, `welcome.py`, `threads.py`, slim `Dockerfile`, `__main__.py`. Unit tests with mocked `discord.Client`. `/test/event`-driven integration tests. | Unit tests pass; `/test/event` end-to-end test green. |
| 5 | Release cells D9–D12 + docs page. | Cells pass locally with a real bot token. |
| 6 | Hash-tree contributions (`channel_package_version` + `channel_runtime_version`). | `vystak plan` correctly diffs on a package bump. |

## Risks called out for the implementation plan

- **Slack retrofit drift.** Phase 2 gate is "all existing Slack tests
  pass" — no new tests required, no behavior changes. Anything that
  requires changing a Slack test is a retrofit bug, not a feature.
- **`channel_config.json` shape compatibility.** Runtime accepts the
  existing Slack config shape verbatim; new keys default-fill if missing.
- **`vystak.hash` change ripples.** Phase 6 last; channel work all ships
  first with hash unchanged. Hash addition is a separate small change after
  Discord is green.
- **Provider `entrypoint` handling.** Verify in phase 1 that
  `vystak-provider-docker` and `vystak-provider-azure` correctly handle
  shell-command-shaped `entrypoint` strings (they already thread into
  Dockerfile `CMD`).
- **Discord rate limits.** `discord.py` handles them transparently via a
  global rate-limit bucket. No special handling needed for MVP since we
  are not streaming.
- **Postgres async lifecycle in tests.** Parametrise the `channel_store`
  fixture; tests run against `MemoryChannelStore` + `SqliteChannelStore`
  by default (fast); Postgres tests guarded by `docker` marker so they only
  run in the Docker job.

## Documentation

- New page: `Channels → Discord` with setup instructions (bot token, intents
  checkbox, slash command registration). Mirrors existing Slack docs.
- New page: `Channels → Internals` documenting `ChannelRuntime` for users
  who want to write their own channel (Telegram, Teams, Matrix as future
  work). Concise — the API is the docs.
- Existing Slack docs get a "what changed" callout for the thread-binding
  reset.

## Out of scope (explicit non-scope reminders)

- Telegram, Teams, Matrix, WhatsApp, IRC, Mattermost, Google Chat, etc. —
  future channels. The runtime lib makes them all small subclass jobs;
  picking the next one is a separate brainstorm.
- TS port of channel packages.
- Any change to `vystak-adapter-langchain` codegen (agents continue to
  emit Python source; the no-codegen pivot is channels-only).
- Any change to `vystak.providers.base.ChannelPlugin` ABC. Kept stable.
