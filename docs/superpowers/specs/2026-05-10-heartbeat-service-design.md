# Heartbeat Service — separate scheduler with transport-based delivery

**Status:** design
**Date:** 2026-05-10
**Author:** Anatoliy Kolodkin
**Supersedes:** [2026-05-09 channel-hosted heartbeat](./2026-05-09-heartbeat-design.md). The earlier design hosted the scheduler inside each channel runtime; this design extracts it into its own service and adds a per-platform model-override capability with session-stored model persistence.

## Summary

Move the heartbeat scheduler out of channel runtimes and into a new
standalone deployable, `vystak-heartbeat`. The new service:

- Holds every heartbeat config on the platform (one process per platform,
  auto-spawned by the provider whenever any agent has `heartbeat`).
- Calls agents over the existing `Transport` abstraction (HTTP or NATS).
- Delivers alerts to channels via a new `ChannelDelivery` interface
  (HTTP or NATS), parallel to but distinct from `Transport`.
- Supports per-heartbeat **model override** that the agent honors per
  turn and **persists on the session** so subsequent fires on the same
  thread reuse the chosen model.

The agent gains a multi-model dispatch capability: `Agent.default_model`
plus `Agent.models: list[Model]`. The langchain template's A2A handler
selects the model from `session-stored > metadata.model_override > default`
and persists the choice on first resolve.

## Goals

1. Decouple scheduling from channel I/O. A bad agent's heartbeat must
   not interfere with a channel's user-message handling.
2. Reuse `Transport` (HTTP/NATS) for agent calls and a parallel
   `ChannelDelivery` (HTTP/NATS) for channel pushes — same transport
   selection governs both directions on a platform.
3. First-class model override per heartbeat with stable per-thread
   model selection across fires. Switching models mid-conversation is
   incoherent; the session pins the choice.
4. Replace the channel-hosted scheduler entirely. No two ways to do it.

## Non-goals

- Auth on the channel delivery surface. Heartbeat ↔ channel runs on
  the same Docker network / Azure VNet; network isolation is the trust
  boundary for v1.
- Retries or dead-letter for failed deliveries. Log and drop; the next
  fire will deliver fresh.
- Multi-platform heartbeat. One `vystak-heartbeat` per platform; an
  agent on platform A cannot heartbeat into a channel on platform B.
- Pluggable LLM frameworks beyond LangChain. Multi-model dispatch is
  scoped to the langchain template; Mastra parity is a separate spec.

## Architecture

```
        Platform (e.g. local docker, namespace=dev)
        ┌────────────────────────────────────────────────────┐
        │                                                    │
        │  Agent containers       (unchanged interface)      │
        │     vystak-<agent>-agent                           │
        │       Serves A2A. New: honors model_override +     │
        │       persists chosen model on session.            │
        │                                                    │
        │  Channel containers     (gain delivery inbox)      │
        │     vystak-channel-<name>                          │
        │       Existing: native client → user inbound       │
        │       NEW:      delivery receiver → outbound push  │
        │                                                    │
        │  vystak-heartbeat       NEW                        │
        │     Auto-spawned when any agent has heartbeat.     │
        │     Holds every (agent, heartbeat) on the platform.│
        │     Calls agents via Transport.                    │
        │     Pushes alerts via ChannelDelivery.             │
        │                                                    │
        │  vystak-otel            (unchanged)                │
        │  vystak-nats            (only when transport=nats) │
        └────────────────────────────────────────────────────┘
```

**Wire directions:**

- Agent ↔ Heartbeat → existing `Transport` (HTTP `/a2a` or NATS subjects).
- Heartbeat → Channel → new `ChannelDelivery` (HTTP `POST /deliver` or
  NATS `vystak.channel.<canonical>.deliver`).
- Channel ↔ User → existing platform-native (Slack-bolt, Discord client,
  chat HTTP). Unchanged.

## Schema changes

```python
class Agent(NamedModel):
    default_model: Model                 # required, used when no override
    models: list[Model] = []             # additional dispatchable models
    # ... everything else unchanged

class Heartbeat(BaseModel):
    schedule: str                        # 5-field cron
    timezone: str = "UTC"
    target_channel: str                  # channel canonical_name
    target_thread: str | None = None
    prompt: str | None = None
    isolated_session: bool = True
    skip_when_busy: bool = True
    ack_max_chars: int = 300
    enabled: bool = True
    model: str | None = None             # NEW — name of a Model in
                                         # {agent.default_model, *agent.models}
                                         # None → use agent.default_model
```

`Agent.model` (the existing field) renames to `Agent.default_model`.
This is a breaking schema rename; the migration sweep updates every
existing example, fixture, codegen reference, and test.

### Plan-time validation (multi_loader.py)

`_validate_heartbeat_targets` extends to also enforce:

- If `heartbeat.model` is set, its value must match
  `{agent.default_model.name} ∪ {m.name for m in agent.models}`.
  Otherwise raise `ValueError(f"agent X heartbeat.model 'Y' not in agent's model pool")`.

### Hash contribution

- `Agent.models` participates in the `brain` slot of `AgentHashTree`
  (analog to how `default_model` does today).
- `Heartbeat.model` is already part of the heartbeat-section hash.
- Channels that route an agent inherit hash changes via the existing
  `_hash_list(channel.agents)` path.

## Channel delivery surface

```python
# vystak-channel-runtime/src/vystak_channel_runtime/delivery.py

class DeliveryRequest(BaseModel):
    thread_id: str                       # platform-native channel/thread id
    text: str
    metadata: dict[str, Any] = {}

class ChannelDelivery(ABC):
    """Sender side. Used by vystak-heartbeat."""
    @abstractmethod
    async def deliver(
        self,
        channel_canonical_name: str,
        request: DeliveryRequest,
        *, timeout: float = 30,
    ) -> None: ...
```

### HTTP impl (`vystak-transport-http`)

```python
class HttpChannelDelivery(ChannelDelivery):
    def __init__(self, channel_routes: dict[str, str]) -> None:
        # canonical_name → http://host:9999 (delivery port, internal only)
        self._routes = channel_routes

    async def deliver(self, name, req, *, timeout=30):
        url = self._routes[name].rstrip("/") + "/deliver"
        async with httpx.AsyncClient(timeout=timeout) as c:
            r = await c.post(url, json=req.model_dump(mode="json"))
            r.raise_for_status()
```

### NATS impl (`vystak-transport-nats`)

```python
class NatsChannelDelivery(ChannelDelivery):
    SUBJECT_FMT = "vystak.channel.{canonical_name}.deliver"

    async def deliver(self, name, req, *, timeout=30):
        nc = await self._connect()
        await nc.publish(
            self.SUBJECT_FMT.format(canonical_name=name),
            req.model_dump_json().encode(),
        )
```

### Wire shape

```json
{
  "thread_id": "C0AV6PJ4VHU",
  "text": "🕐 02:10 UTC | 🌤️ NYC: clear, 18°C",
  "metadata": {
    "heartbeat": true,
    "agent": "assistant-agent",
    "fired_at": "2026-05-10T02:10:00Z"
  }
}
```

### Receiver scaffolding (base `ChannelRuntime`)

```python
class ChannelRuntime(ABC):
    @abstractmethod
    async def deliver_message(
        self,
        thread_id: str,
        text: str,
        metadata: dict[str, Any],
    ) -> None:
        """Subclass: post `text` into `thread_id` via the native API."""

    async def _start_delivery_receiver(self) -> None:
        """Mounts HTTP /deliver or NATS subscription based on
        platform.transport.type. Called from start()."""

    async def _stop_delivery_receiver(self) -> None: ...

    async def _on_inbound_delivery(self, body: dict) -> None:
        try:
            req = DeliveryRequest.model_validate(body)
        except ValidationError as exc:
            logger.warning("deliver: invalid body %s", exc); return
        try:
            await self.deliver_message(req.thread_id, req.text, req.metadata)
        except Exception:
            logger.exception("deliver_message failed for %s", req.thread_id)
```

For HTTP, the base spins up a sidecar uvicorn on `delivery_port`
(default `9999`, configurable). For Slack-bolt / discord.py runtimes
that don't already serve HTTP, this is a separate task; for the chat
runtime that already runs uvicorn, the route is mounted on the existing
app. The receiver listens only on the internal Docker network — never
exposed on the host.

For NATS, the runtime subscribes to its canonical subject at start;
unsubscribes on stop.

### Concrete `deliver_message` per channel

```python
# Slack
async def deliver_message(self, thread_id, text, metadata):
    await self._app.client.chat_postMessage(channel=thread_id, text=text)

# Discord
async def deliver_message(self, thread_id, text, metadata):
    channel = self._client.get_channel(int(thread_id)) \
              or await self._client.fetch_channel(int(thread_id))
    for chunk in _chunk(text, MAX_DISCORD_MESSAGE_CHARS):
        await channel.send(chunk)

# Chat
async def deliver_message(self, thread_id, text, metadata):
    await self._broadcast(thread_id, text, metadata)
```

## `vystak-heartbeat` service internals

### Container layout

```
/etc/vystak/
  service_config.json       # transport.type, OTel env, session store config
  routes.json               # agents-with-heartbeat plus their delivery target
```

`routes.json` example:

```json
{
  "assistant-agent": {
    "canonical": "assistant-agent.agents.dev",
    "address": "http://vystak-assistant-agent:8000/a2a",
    "heartbeat": {
      "schedule": "*/10 * * * *",
      "target_channel": "slack-main.channels.dev",
      "target_thread": "C0AV6PJ4VHU",
      "model": "haiku",
      "...": "..."
    },
    "delivery": {
      "channel_canonical_name": "slack-main.channels.dev",
      "url": "http://vystak-channel-slack-main:9999",
      "subject": "vystak.channel.slack-main.channels.dev.deliver"
    }
  }
}
```

Codegen fully resolves at deploy time — no runtime service discovery.

### Process structure

```python
async def main():
    cfg = load_service_config()
    routes = load_routes()

    transport = build_transport(cfg)              # HttpTransport | NatsTransport
    delivery = build_channel_delivery(cfg, routes)
    sessions = build_session_store(cfg)           # in-memory or sqlite

    schedulers = []
    for agent_name, route in routes.items():
        if "heartbeat" not in route:
            continue
        hb = Heartbeat.model_validate(route["heartbeat"])
        if not hb.enabled:
            continue
        schedulers.append(HeartbeatScheduler(
            agent_name=agent_name,
            agent_canonical=route["canonical"],
            channel_canonical=route["delivery"]["channel_canonical_name"],
            heartbeat=hb,
            transport=transport,
            delivery=delivery,
            sessions=sessions,
        ))
    for s in schedulers: await s.start()
    await wait_for_shutdown()
    for s in schedulers: await s.stop()
```

### `HeartbeatScheduler._fire`

```python
async def _fire(self):
    if self.hb.skip_when_busy and self._busy:
        return
    thread_id = self._resolve_thread()
    if thread_id is None:
        return

    session_id = (synthetic if self.hb.isolated_session else thread_id)

    stored_model = await self.sessions.get_model(session_id)
    request_model = stored_model or self.hb.model        # may be None

    self._busy = True
    try:
        reply = await self.transport.send_task(
            AgentRef(canonical_name=self.agent_canonical),
            A2AMessage(
                parts=[TextPart(text=self.hb.prompt or DEFAULT_PROMPT)],
                correlation_id=session_id,
            ),
            metadata={
                "heartbeat": True,
                "model_override": request_model,
                "session_id": session_id,
            },
            timeout=120,
        )
        chosen = (reply.metadata or {}).get("model_resolved")
        if stored_model is None and chosen:
            await self.sessions.set_model(session_id, chosen)

        if is_heartbeat_ok(reply.text, self.hb.ack_max_chars):
            logger.info("heartbeat.acked agent=%s", self.agent_name)
            return
        await self.delivery.deliver(
            self.channel_canonical,
            DeliveryRequest(
                thread_id=thread_id,
                text=reply.text,
                metadata={"heartbeat": True, "agent": self.agent_name,
                          "fired_at": datetime.now(UTC).isoformat()},
            ),
        )
    finally:
        self._busy = False
```

### Session store

```python
class HeartbeatSessionStore(ABC):
    async def get_model(self, session_id: str) -> str | None: ...
    async def set_model(self, session_id: str, model_name: str) -> None: ...

class InMemoryStore(HeartbeatSessionStore): ...
class SqliteStore(HeartbeatSessionStore): ...
```

For `isolated_session=true`, `session_id` is a fresh synthetic per
fire — `set_model` writes a row never read again. Harmless. For
`isolated_session=false`, `session_id == target_thread`, so the stored
model survives across fires and across container restarts (when
SqliteStore is configured with a mounted volume).

## Agent-side changes (langchain template)

1. Codegen emits LLM bindings for `default_model` plus every entry in
   `models`. All bindings are constructed once at startup; per-turn
   the handler picks one from a name-keyed dict.

2. The A2A handler reads `metadata.model_override` and
   `metadata.session_id`.

3. Model picking precedence (stable, deterministic):

   ```
   if session_stored_model is not None:
       chosen = session_stored_model
   elif model_override is not None and model_override in agent_models:
       chosen = model_override
   else:
       chosen = default_model
   ```

4. After picking, if `session_stored_model is None`, persist the
   chosen name. Storage is a small sidecar table named
   `heartbeat_session_models` on the same SQLite/Postgres backing the
   agent's session checkpointer:

   ```sql
   CREATE TABLE IF NOT EXISTS heartbeat_session_models (
       session_id TEXT PRIMARY KEY,
       model_name TEXT NOT NULL,
       updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
   );
   ```

   Sidecar rather than extending the langgraph checkpointer schema so
   the change is independent of langgraph's storage internals.

5. The reply's `metadata.model_resolved` echoes the chosen model name
   back so `vystak-heartbeat` can record it in its own session store.

If `model_override` is present but does not match any of the agent's
declared models, the handler falls through to default_model and emits
a structured-log warning. Plan-time validation should prevent this in
practice; the runtime warning catches drift from manual A2A callers.

## Codegen contributors

- **Provider auto-spawn.** `vystak-provider-docker` and
  `vystak-provider-azure` build the provision graph. When any agent on
  the platform has `heartbeat`, they add a `vystak-heartbeat` node that
  depends on the network/transport plus every channel container the
  schedulers will deliver into.
- **`vystak-heartbeat/plugin.py` — new.** Emits Dockerfile,
  requirements.txt, service_config.json, routes.json. Standard scaffold
  matching the other plugin patterns.
- **Channel plugins** stop emitting heartbeat-enriched routes.json.
  They add `delivery_port` to channel_config.json (HTTP) and `EXPOSE
  9999` to Dockerfile (HTTP). NATS path requires no Dockerfile change.

## Migration order

Each step ends with `just ci` green.

1. **Schema rename only.** `Agent.model` → `Agent.default_model`,
   add `Agent.models: list[Model] = []`. Mechanical sweep: every
   `agent.model` reference in templates / codegen / tests / examples.
   Big diff, no behavior change.
2. **Add `Heartbeat.model: str | None`.** Schema only. No consumer.
3. **Agent multi-model dispatch.** Langchain template emits the
   dispatcher; A2A handler reads metadata + session-stored picks; new
   session column. Validates 1+2 via direct A2A calls in tests.
4. **Plan-time `heartbeat.model` validation.** Extend
   `_validate_heartbeat_targets`.
5. **`vystak-heartbeat` package.** Plugin, service, schedulers, session
   store, routes.json + service_config.json codegen. Not auto-spawned
   yet; can be deployed manually for unit/integration testing.
6. **`ChannelDelivery` interface.** New module in
   `vystak-channel-runtime`. HTTP+NATS impls in
   `vystak-transport-{http,nats}`. Channel-side
   `_start_delivery_receiver` + abstract `deliver_message`. Slack /
   Discord / Chat each implement `deliver_message`.
7. **Provider auto-spawn.** Docker + Azure providers detect any agent
   has heartbeat → add `vystak-heartbeat` to provision graph. Channel
   plugins emit delivery port + Dockerfile updates. End-to-end
   functional path now exists.
8. **Remove channel-hosted heartbeat.** Delete `_start_heartbeats` /
   `_stop_heartbeats` / `_handle_synthetic_event` / `_heartbeat_for_route` /
   `_heartbeats` / `enrich_routes_with_heartbeat`. Delete Slack and
   Discord `post_reply` heartbeat branches. Replace
   `tests/release/test_heartbeat.py` with the new integration cell.

Step 8 is the only one that removes infrastructure; it lands last so
the existing channel-hosted impl is the safety net while the new path
matures.

## Testing

### 1. Unit — heartbeat service (`vystak-heartbeat/tests/`)

- `HeartbeatScheduler._fire`:
  - model selection precedence (session > override > default)
  - session-store persistence on first resolve
  - cron loop survives transport errors
  - ack-stripping path drops `HEARTBEAT_OK`
  - delivery is invoked with the correct `DeliveryRequest`
- `HeartbeatSessionStore`: in-memory + sqlite get/set; sqlite survives
  instance restart.

### 2. Unit — channel runtime delivery (`vystak-channel-runtime/tests/`)

- `_on_inbound_delivery`: valid payload calls `deliver_message`;
  invalid JSON → warning + drop; subclass exception → log + swallow.
- `_start_delivery_receiver` HTTP: route mounted, POST dispatched.
- `_start_delivery_receiver` NATS: subscription, publish dispatched.
- Lifecycle: `_stop_delivery_receiver` cleanly shuts down both.

### 3. Unit — agent multi-model dispatch (`vystak-template-langchain-python/tests/`)

- Codegen with `default_model` + `models=[A, B]` emits all three
  bindings.
- A2A handler picks `default_model` when no override.
- Picks override when set and present in pool.
- Picks session-stored when present (override ignored).
- First-time resolve persists to session column.
- Returned reply carries `metadata.model_resolved`.

### 4. Schema + plan-time (`vystak/tests/`)

- Round-trip `Heartbeat` with `model: "haiku"` through YAML.
- `_validate_heartbeat_targets`: heartbeat.model in pool → pass;
  not in pool → fail with helpful message; no model → pass.
- Rename: existing `agent.model` references in tests updated; load_multi_yaml
  parses the new shape.
- Hash propagation: `extra_models` change → root hash changes →
  channel root hash changes (transitive).

### 5. Release integration (`vystak-provider-docker/tests/release/`)

Replaces the soon-removed channel-hosted `test_heartbeat.py`.

Setup: 1 chat channel + 1 agent with `default_model=A`, `models=[B]`,
heartbeat `model=B`, `schedule="* * * * *"`, `isolated_session=false`.

Verifies in order:
1. `vystak-heartbeat` container exists and is healthy.
2. Agent + channel containers running.
3. Wait ≤90s — assert `heartbeat.fired` log line in heartbeat container.
4. Assert `deliver_message called` log line in channel container.
5. Wait next minute — assert second fire used the same model. Read
   either the agent's session column or the heartbeat service's stored
   `model_resolved`. Assert equality across two fires.

Slack delivery (`release_slack` marker) gated on Slack tokens.

## Removed pieces (from the v1 channel-hosted design)

- `ChannelRuntime._start_heartbeats` / `_stop_heartbeats`
- `ChannelRuntime._handle_synthetic_event`
- `ChannelRuntime._heartbeat_for_route`
- `ChannelRuntime._heartbeats: list[HeartbeatScheduler]`
- `enrich_routes_with_heartbeat` helper in `vystak-channel-runtime`
- Slack `post_reply` heartbeat branch (replaced by `deliver_message`)
- Discord `post_reply` heartbeat branch (replaced)
- Chat plugin's `enrich_routes_with_heartbeat` call
- Per-channel routes.json heartbeat enrichment
- `tests/release/test_heartbeat.py` (replaced by the new cell)

## Out of scope

- Auth on the delivery surface. Future work if cross-platform delivery
  is added.
- Retries / dead-letter for failed deliveries.
- Mastra adapter parity for multi-model dispatch.
- `target_channel: "last"` magic from OpenClaw — still pinned-only.

## Open questions

None. All design choices made during brainstorming.
