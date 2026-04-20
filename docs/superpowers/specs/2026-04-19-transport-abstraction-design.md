# Transport Abstraction Design

**Date:** 2026-04-19
**Status:** Draft — pending user review
**Branch:** `pivot/channel-architecture`

## Problem

Today, Vystak wires HTTP directly into every piece of east-west communication:

- Channel plugins (`vystak-channel-slack`, `vystak-channel-chat`) POST to `{agent_url}/a2a` via raw `httpx`.
- Agent-to-agent tool code (`examples/.../tools/ask_*_agent.py`) hardcodes URLs such as `http://vystak-time-agent:8000/a2a` or reads per-agent env vars (`TIME_AGENT_URL`, `WEATHER_AGENT_URL`).
- The LangChain adapter emits a FastAPI server with `/a2a` as the only A2A ingress.
- Route tables (`resolved_routes: dict[str, str]`) carry raw URLs.

We want to introduce a **transport abstraction** so the same agents and channels can communicate over alternative mediums — starting with **NATS (JetStream)** and leaving room for **Azure Service Bus** — without rewriting user tool code or channel plugins each time.

## Scope

In scope:

- **Internal east-west** communication only:
  - Channel → agent dispatch (A2A `tasks/send`, `tasks/sendSubscribe`).
  - Agent → agent dispatch (peer calls from inside tools).

Out of scope:

- **Outward client-facing** traffic (end users hitting a channel, Slack Socket Mode, OpenAI-compatible `/v1/chat/completions` exposed to humans). Those remain HTTP-native.
- New wire protocols beyond A2A JSON-RPC. The envelope stays identical on every transport — only the framing changes.

## Design principles

1. **Platform-wide transport.** A `Platform` declares a single `Transport`; all agents and channels on it speak that transport for east-west traffic. No per-agent / per-edge mixing in v1.
2. **Pluggable, minimal ABC.** Three reference implementations designed alongside the ABC: `http`, `nats`, `azure-service-bus`. Future transports (Kafka, Redis Streams, gRPC) slot in by implementing the ABC.
3. **Canonical addressing.** Agents already have a canonical name (`{name}.agents.{namespace}`). Every wire address on every transport is **derived deterministically** from the canonical name by the transport implementation. No user-chosen URLs, subjects, or queue names for agents.
4. **Streaming is first-class, with graceful degradation.** `supports_streaming: bool` on each transport; streaming callers hitting a non-streaming transport auto-degrade to one-shot replies.
5. **FastAPI always-on.** The generated agent always exposes its HTTP surface (OpenAI-compat, `/health`, `/.well-known/agent.json`, `/a2a`), even when the platform transport is NATS/SB. A non-HTTP transport adds a *parallel* listener; it does not replace HTTP.
6. **Replication-safe.** Load balancing across replicas of an agent and reply correlation back to the specific caller replica are **required behaviors** of every transport, not optional.
7. **Backward compatible by default.** A `Platform` without a `transport` field gets a synthesized `http` transport and behaves exactly as today.

## Architecture

### Components

```
┌────────────────────────────────────────────────────────────────────┐
│  Caller side (channel server, tool inside an agent)                │
│                                                                    │
│  ask_agent("time-agent", q)   AgentClient.send_task/stream_task    │
│                         │          │                               │
│                         ▼          ▼                               │
│                    ┌──────────────────┐                            │
│                    │  Transport (ABC) │  ← from platform env       │
│                    └──────────────────┘                            │
│                     │        │        │                            │
│                     ▼        ▼        ▼                            │
│                HttpTransport  NatsTransport  ServiceBusTransport   │
└─────────────────────│──────────│────────────│─────────────────────┘
                      │          │            │
                      ▼          ▼            ▼
                   HTTP/A2A   NATS subject   SB queue + session
                      │          │            │
┌─────────────────────│──────────│────────────│─────────────────────┐
│  Callee side (agent process)                                       │
│                                                                    │
│     FastAPI /a2a ──┐     NatsListener ──┐     SbListener ──┐       │
│                    ▼                    ▼                   ▼      │
│                   A2AHandler  (transport-agnostic)                 │
└────────────────────────────────────────────────────────────────────┘
```

- `Transport` ABC (Python, in `vystak.transport`) — three methods: `send_task`, `stream_task`, `serve`, plus `resolve_address`.
- `AgentRef` — typed wrapper over an agent's identity for transport-facing calls:
  ```python
  class AgentRef(BaseModel):
      canonical_name: str  # "{name}.agents.{namespace}"
  ```
  The client resolves a user-supplied short name (e.g. `"time-agent"`) into an `AgentRef` via the route map, then passes it to the transport. The transport uses `canonical_name` to derive the wire address.
- `AgentClient` — caller-side client; loads transport from env at construction, exposes `send_task` / `stream_task`.
- `ask_agent` — one-shot convenience helper over `AgentClient`.
- `A2AHandler` — transport-agnostic request dispatcher, extracted from today's `a2a.py`. Reused by the FastAPI `/a2a` route *and* by any non-HTTP listener.
- `TransportPlugin` ABC — mirrors `ChannelPlugin`: owns broker provisioning and the code snippets injected into generated agent/channel code.
- Three concrete plugin packages: `vystak-transport-http`, `vystak-transport-nats`, `vystak-transport-azure-service-bus`.

### Transport ABC

```python
class Transport(ABC):
    type: str                   # "http" | "nats" | "azure-service-bus"
    supports_streaming: bool    # false => stream_task degrades to send_task

    @abstractmethod
    def resolve_address(self, canonical_name: str) -> str:
        """Derive the transport's wire address from an agent's canonical name."""

    @abstractmethod
    async def send_task(self, agent: AgentRef, message: A2AMessage,
                        metadata: dict, *, timeout: float) -> A2AResult: ...

    async def stream_task(self, agent: AgentRef, message: A2AMessage,
                          metadata: dict, *, timeout: float) -> AsyncIterator[A2AEvent]:
        # Default: call send_task, yield one terminal event.
        # NATS / HTTP override natively.

    @abstractmethod
    async def serve(self, canonical_name: str, handler: A2AHandler) -> None:
        """Join the load-balanced group for this agent and dispatch incoming
        messages into `handler`. `canonical_name` is the full {name}.agents.{ns}
        identifier; the transport derives its own subject / queue name from it."""
```

**Mandatory behaviors of every non-HTTP transport implementation:**

- Load balancing across replicas (NATS queue group, SB competing consumer, etc.).
- Per-call reply correlation routed to the exact caller replica (NATS `_INBOX`, SB `session-id`, etc.).
- Clean teardown of reply subscriptions on timeout (no orphan inboxes/sessions).

### A2A envelope (unchanged across transports)

The JSON-RPC 2.0 envelope already in `vystak-adapter-langchain/a2a.py` remains the wire payload on every transport. Fields kept identical; one new field added:

- `correlation_id` (UUID, per-call, application-level) — echoed by the reply. Orthogonal to `thread_id` (conversation state) and `task_id` (A2A identifier).

Existing metadata fields (`trace_id`, `user_id`, `project_id`, `parent_task_id`) travel through transports unchanged.

## Canonical addressing

Every agent has a canonical name: `{name}.agents.{namespace}` (already modelled in `vystak/schema/agent.py:46`). Channels and transports follow the same shape.

The wire address on every transport is derived from the canonical name by `Transport.resolve_address()`:

| Transport | Derivation rule | Example (`time-agent`, ns `prod`) |
|---|---|---|
| `http` (Docker) | `http://{slug(name)}-{slug(ns)}:{port}/a2a` | `http://time-agent-prod:8000/a2a` |
| `http` (Azure ACA) | `https://{slug(name)}-{slug(ns)}.{region}.azurecontainerapps.io/a2a` | (ACA-derived) |
| `nats` | `{prefix}.{ns}.agents.{name}.tasks` (+ `.stream` for streaming) | `vystak.prod.agents.time-agent.tasks` |
| `azure-service-bus` | `{prefix}-{slug(ns)}-agents-{slug(name)}-tasks` | `vystak-prod-agents-time-agent-tasks` |

**Defaults:** `prefix = "vystak"`. `slug(s)` = lowercase, `[a-z0-9-]`, max 63 chars, matching existing Azure ACA + Docker Compose conventions in the repo.

Centralized in a new module: `packages/python/vystak/src/vystak/transport/naming.py`. Tested once; consumed by every transport implementation, every provider, and the codegen path.

Route tables become transport-agnostic. `VYSTAK_ROUTES_JSON` carries only canonical names; the client derives the wire address at call time via the active transport.

## Schema

New model at `packages/python/vystak/src/vystak/schema/transport.py`:

```python
class Transport(BaseModel):
    name: str
    type: Literal["http", "nats", "azure-service-bus"]
    namespace: str | None = None

    # Provision-or-BYO, mirrors Service(type="postgres"):
    connection: TransportConnection | None = None

    # Discriminated union on type:
    config: HttpConfig | NatsConfig | ServiceBusConfig | None = None

    @property
    def canonical_name(self) -> str:
        return f"{self.name}.transports.{self.namespace}"


class TransportConnection(BaseModel):
    url_env: str | None = None            # env var name holding the URL
    credentials_secret: str | None = None # Secret ref


class HttpConfig(BaseModel):
    type: Literal["http"] = "http"
    # reserved; currently empty (timeouts, TLS later)


class NatsConfig(BaseModel):
    type: Literal["nats"] = "nats"
    jetstream: bool = True
    subject_prefix: str = "vystak"
    stream_name: str | None = None        # auto-derived if unset
    max_message_size_mb: int = 1


class ServiceBusConfig(BaseModel):
    type: Literal["azure-service-bus"] = "azure-service-bus"
    namespace_name: str | None = None     # BYO or auto-created
    use_sessions: bool = True             # for ordered request/reply
```

`Platform` gains one field:

```python
class Platform(BaseModel):
    provider: Literal["docker", "azure", ...]
    transport: str | None = None   # name of a Transport resource
    ...
```

If unset, Vystak synthesises `Transport(name="default-http", type="http")` and behaviour is identical to today.

### User-facing examples

Docker + auto-provisioned NATS:

```python
nats = Transport(name="bus", type="nats", config=NatsConfig(jetstream=True))
platform = Platform(provider="docker", transport="bus")
workspace = Workspace(agents=[...], channels=[...], transports=[nats], platforms=[platform])
```

(`Workspace` gains a `transports: list[Transport]` field, following the same pattern as `agents`, `channels`, and `services`.)

Azure + BYO Service Bus:

```python
sb = Transport(
    name="bus", type="azure-service-bus",
    connection=TransportConnection(
        url_env="SB_CONNECTION_STRING",
        credentials_secret="sb-creds",
    ),
    config=ServiceBusConfig(namespace_name="existing-sb-ns"),
)
platform = Platform(provider="azure", transport="bus")
```

### Hash tree

`AgentHashTree` incorporates:

- `platform.transport` reference name,
- the resolved transport's `type`,
- the transport's `config` (broker-specific config that affects wire behaviour).

Excluded from the hash:

- `TransportConnection` URL / credentials (same agent, different broker instance should be portable).

Switching transport type or changing `config` triggers redeploy; BYO endpoint changes do not.

## Environment overlays

Projects often need per-environment transport config — for example, HTTP locally for fast dev iteration and NATS in production. Rather than forcing users to fork `vystak.py` per environment or juggle env vars for every transport knob, Vystak supports a thin **overlay** mechanism scoped tightly to transport/platform fields in v1.

### File layout

Overlays live next to the base definition, by filename convention:

```
my-agent/
  vystak.py                # base definition (unchanged)
  vystak.dev.py            # optional environment overlay (Python)
  vystak.prod.yaml         # optional environment overlay (YAML)
```

An overlay file is optional; if `vystak.<env>.{py,yaml}` is absent, the base definition is used as-is.

### Override shape — Python

The overlay module exports a single `WorkspaceOverride` (Pydantic model). Declarative, typed, validated at load time:

```python
# vystak.prod.py
from vystak import (
    WorkspaceOverride, TransportOverride, NatsConfig,
    PlatformOverride, TransportConnection,
)

override = WorkspaceOverride(
    transports={
        "bus": TransportOverride(
            type="nats",
            config=NatsConfig(jetstream=True, subject_prefix="vystak-prod"),
            connection=TransportConnection(
                url_env="NATS_URL",
                credentials_secret="nats-prod-creds",
            ),
        ),
    },
    platforms={
        "main": PlatformOverride(transport="bus"),
    },
)
```

### Override shape — YAML

Same structure, under a top-level `overrides:` key:

```yaml
# vystak.prod.yaml
overrides:
  transports:
    bus:
      type: nats
      config:
        jetstream: true
        subject_prefix: vystak-prod
      connection:
        url_env: NATS_URL
        credentials_secret: nats-prod-creds
  platforms:
    main:
      transport: bus
```

### Merge semantics

- Keyed by resource `name`. An overlay entry for `transports["bus"]` replaces specific fields of the base `Transport` named `bus`.
- Field-level replacement only. No deep-merging of nested dicts — if a `TransportOverride` supplies `config`, it replaces the base `config` entirely. Keeps reasoning local; no surprises from partial merges.
- Override models (`TransportOverride`, `PlatformOverride`) have all fields optional; only fields explicitly set by the user are applied.
- The merged workspace runs through `Workspace.model_validate` exactly as in the no-overlay case. Typos in overlay keys (e.g., referencing an unknown transport name) surface immediately.

### v1 override surface

Scoped tightly to what this design covers:

- `Transport.type`
- `Transport.config` (entire discriminated-union value; e.g., swap `HttpConfig` → `NatsConfig`)
- `Transport.connection`
- `Platform.transport`

Other resource overrides (agents, channels, their internals) are out of scope for this spec. The overlay mechanism extends naturally to broader resources in future specs; we do not promise those here.

### CLI

Added to every workspace-consuming command (`plan`, `apply`, `destroy`, `status`, `logs`):

```
vystak apply --env prod
vystak apply -e prod
vystak apply                 # no overlay; base only
```

`$VYSTAK_ENV=prod` is an equivalent alternative; the CLI flag wins when both are set. The resolved environment name is echoed in CLI output so misconfiguration is visible.

### Hash tree

The *resolved* (post-overlay) workspace is what feeds `AgentHashTree`. Different environments produce different hashes and therefore independent deploy identities. `vystak plan --env prod` compares against the prod-deployed hash label; `--env dev` against dev's. No cross-environment collisions.

### Loader changes

`vystak-cli/src/vystak_cli/loader.py` is extended:

1. Resolve env name (CLI flag → `$VYSTAK_ENV` → none).
2. Load base `vystak.py` or `vystak.yaml` → `Workspace`.
3. If env is set and `vystak.<env>.{py,yaml}` exists: load it, extract `WorkspaceOverride`, apply to the base workspace.
4. Run `Workspace.model_validate` on the resolved workspace.
5. Pass to the command handler.

`WorkspaceOverride.apply(base: Workspace) -> Workspace` is the merge function — pure, unit-tested, no side effects.

## Generated agent runtime (server side)

FastAPI stays always-on. The agent always serves:

- `GET /health`
- `GET /.well-known/agent.json`
- `POST /a2a` (JSON-RPC + SSE) — **always present**
- `GET /v1/models`
- `POST /v1/chat/completions`
- `POST /v1/responses`, `GET /v1/responses/{id}`

When the platform transport is non-HTTP, a transport listener starts as a FastAPI lifespan task alongside the HTTP server. Both listeners feed the same `A2AHandler` instance:

```
peer call over NATS ─▶ nats subscriber ─┐
                                        ├─▶ A2AHandler.dispatch(msg, metadata)
curl POST /a2a      ─▶ FastAPI route  ─┘
```

### Refactor of `a2a.py`

`vystak-adapter-langchain/a2a.py` is refactored so:

- `A2AHandler` is a plain class that accepts `(A2AMessage, metadata) -> A2AResult | AsyncIterator[A2AEvent]`. No FastAPI dependency.
- The current FastAPI SSE route becomes a thin adapter wrapping `A2AHandler`.
- Transport-specific listeners (NATS, SB) wrap the same `A2AHandler` and bridge message envelopes in/out.

The existing E501 `per-file-ignores` for `a2a.py` and `templates.py` remain; changes are additive to generated code, not edits to the existing string-template bodies.

### Listener snippet injection

The `TransportPlugin` for each transport provides a `generate_listener_code()` method that returns a code fragment inserted into the generated `server.py`. HTTP plugin returns `None` (FastAPI already handles `/a2a`). NATS plugin returns something like:

```python
@app.on_event("startup")
async def _start_transport_listener():
    transport = build_transport_from_env()
    if transport.type != "http":
        asyncio.create_task(
            transport.serve(canonical_name=AGENT_CANONICAL_NAME, handler=handler)
        )
```

## Caller side: client and helper

### AgentClient

```python
class AgentClient:
    @classmethod
    def from_env(cls) -> "AgentClient":
        """Reads VYSTAK_TRANSPORT_* env vars injected at deploy time."""

    async def send_task(self, agent: str, text: str | A2AMessage, *,
                        metadata: dict | None = None,
                        timeout: float = 60) -> str: ...

    async def stream_task(self, agent: str, text: str | A2AMessage, *,
                          metadata: dict | None = None,
                          timeout: float = 60) -> AsyncIterator[A2AEvent]:
        """Auto-degrades to send_task if transport.supports_streaming is False."""
```

`AgentClient`:

- Fills in `correlation_id` (per call) and metadata (`trace_id`, `user_id`, `project_id`, `parent_task_id`) from `langchain_core.runnables.config.get_config()` when running inside a LangGraph node.
- Resolves the target agent's wire address via `transport.resolve_address(canonical_name)`.
- Sets up the per-call reply primitive (NATS `_INBOX`, SB `session-id`) before sending.
- Tears down the reply subscription on success, failure, or timeout.

### Helper

```python
from vystak.transport import ask_agent

async def ask_time_agent(question: str) -> str:
    return await ask_agent("time-agent", question)
```

Cached default `AgentClient.from_env()`. This is the recommended form for tool code.

### Env-var contract

Injected by the active `TransportPlugin` into every agent and channel container:

- `VYSTAK_TRANSPORT_TYPE` — `http | nats | azure-service-bus`
- `VYSTAK_TRANSPORT_ENDPOINT` — broker URL or connection string
- `VYSTAK_TRANSPORT_CREDENTIALS_*` — auth material per transport
- `VYSTAK_ROUTES_JSON` — JSON-encoded `{short_name: canonical_name}` mapping for peer discovery. `short_name` is the name the caller uses (e.g. `"time-agent"` in `ask_agent("time-agent", ...)`); `canonical_name` is the full `{name}.agents.{namespace}` used by the transport to resolve the wire address. The provider populates this map from the workspace at deploy time based on which peers each agent/channel is allowed to reach.

This replaces the current per-agent `TIME_AGENT_URL` / `WEATHER_AGENT_URL` pattern. A single contract, transport-agnostic.

## Replication and reply correlation

### Load balancing across replicas

- **HTTP.** Replicas sit behind DNS / ACA load balancer; `Transport.resolve_address()` returns a single logical URL; LB distributes.
- **NATS.** Each replica joins a queue group named after the agent (e.g. `agents.time-agent`). Queue-group semantics guarantee one-of-N delivery. Required behaviour of `NatsTransport.serve()`.
- **Azure Service Bus.** Competing-consumer on the agent's queue; SB delivers each message to exactly one receiver. With `use_sessions=True`, each call is its own session, handled end-to-end by one replica.

The wire address resolved for an agent is always a single logical address; replica fan-in is handled by the transport, not by the route table. Replica count lives on the provider's container spec (ACA replica range, Docker Compose `replicas`), not on the transport.

### Reply correlation

Two layered concepts:

1. **Correlation id (application-level).** UUID per call, lives in the A2A envelope. Echoed in the reply. Logged / traced. Orthogonal to `thread_id` (conversation) and `task_id` (A2A identifier).
2. **Reply address (transport-level).** Ephemeral, per-call, only the calling replica process receives replies on it. Mechanism differs per transport:
   - **HTTP** — implicit: reply flows back on the open TCP connection.
   - **NATS** — unique reply subject (`_INBOX.{uuid}`). Caller subscribes before sending; callee publishes to it; broker delivers only to that subscriber.
   - **Azure Service Bus** — per-call `session-id` on a shared reply queue/topic. Caller opens a session receiver locked to its session-id; SB guarantees only that receiver gets those messages.

Streaming replies use the same mechanism — the stream is bound to the same reply primitive, so stream events only reach the calling replica.

Timeouts bound the reply subscription's lifetime; on expiry the subscription/session is torn down to avoid orphaned primitives.

## Channels

Channel plugins (`vystak-channel-slack`, `vystak-channel-chat`) stop using `httpx` directly. They receive an `AgentClient` instance constructed from env (same env contract as above) and call `client.send_task(agent)` / `client.stream_task(agent)`.

`resolved_routes` evolves from `dict[str, str]` to `dict[str, AgentRef]` where `AgentRef` carries only the canonical name; the transport resolves addresses at runtime. `ChannelPlugin.generate_code()` signature is updated accordingly.

Chat channel's streaming SSE endpoint (`/v1/chat/completions` with `stream=true`) calls `client.stream_task()` and re-emits events as SSE chunks to the end-user. On a non-streaming transport this degrades cleanly: a single final chunk is emitted instead of tokens.

## Provisioning

### TransportPlugin ABC

Mirrors `ChannelPlugin`, lives in `vystak.providers.base`:

```python
class TransportPlugin(ABC):
    type: str  # "http" | "nats" | "azure-service-bus"

    def build_provision_nodes(self, transport: Transport,
                              platform: Platform) -> list[Provisionable]:
        """Broker infra nodes. Empty for http / BYO."""

    def generate_env_contract(self, transport: Transport,
                              context: dict) -> dict[str, str]:
        """VYSTAK_TRANSPORT_* env vars to inject into agents/channels."""

    def generate_listener_code(self, transport: Transport) -> GeneratedCode | None:
        """Code snippet appended to generated agent server.py. None for http."""
```

### Per-provider integration

- **Docker provider** — when `transport.type == "nats"` and `connection is None`: adds a `NatsContainerNode` (NATS server image with JetStream enabled, persistent volume) to the `ProvisionGraph`. Every agent and channel container gains a `depends_on` edge to it. BYO path: no node added, just plumbs the URL env var.
- **Azure provider** — when `transport.type == "azure-service-bus"` and `connection is None`: adds `ServiceBusNamespaceNode` (Standard tier, sessions enabled) + per-agent queue nodes. BYO path: references the existing namespace by name and queue-creates within it.
- **HTTP transport** — `build_provision_nodes()` returns `[]` across all providers.

### ProvisionGraph ordering

`TransportNodes → (AgentNodes, ChannelNodes)`. The broker must be healthy before agents start so listener subscription succeeds on first try.

## Testing

### Unit

Per-package tests for each transport implementation — in-memory / mocked. Standard.

### Contract tests

Shared `transport_contract.py` test module in `vystak` that any concrete `Transport` must pass:

- Single-reply-per-call.
- Queue-group / competing-consumer load balancing across two subscribers.
- Reply correlation under concurrent calls.
- Streaming degradation when `supports_streaming=False`.
- Timeout cleanup (no orphan reply primitives).

Adding Service Bus (or Kafka, etc.) later means implementing the ABC and passing the contract tests — no new test scaffolding required.

### Docker integration

Opt-in via `-m docker` (existing pattern, excluded by default in `just test-python`). Spins up a NATS container + two replicas of a test agent and verifies:

- Queue-group load balancing across the two replicas (each of N messages handled by exactly one replica).
- Reply correlation — caller replica always receives its own replies.
- End-to-end streaming over NATS.

### Example parity

Port one existing example (`examples/azure-multi-agent/`) to a NATS-on-Docker variant (`examples/docker-multi-agent-nats/`). Smallest viable end-to-end proof that the abstraction holds in real deployments.

## Migration

### Backward compatibility

- `Platform` without `transport` field → synthesised `http` transport. No user change required.
- Existing channel servers and generated agents keep working on HTTP identically to today.

### User tool code

Existing tool files (`examples/.../tools/ask_*_agent.py`) continue to work in HTTP mode unchanged — they read env vars and call `httpx`. Recommended path forward: rewrite to the 4-line `ask_agent()` form. In-repo examples are migrated; user code is left untouched.

### Env-var deprecation

Per-agent env vars (`TIME_AGENT_URL`, `WEATHER_AGENT_URL`) are no longer generated by Vystak. `VYSTAK_ROUTES_JSON` is the single source of truth. Hand-written tool code that still reads the old vars keeps working if the user sets them manually; Vystak simply stops emitting them.

### Rollout order

Each step independently mergeable; `just lint-python`, `just test-python`, `just typecheck-typescript`, `just test-typescript` stay green.

1. `vystak.transport` module — `Transport` ABC, `AgentRef`, `A2AMessage/Event/Result`, `AgentClient`, `ask_agent`, `naming.py`, contract tests.
2. `vystak-transport-http` package — extracts current behaviour as the default transport plugin.
3. Refactor `a2a.py` into transport-agnostic `A2AHandler`; wire the FastAPI route as an adapter; templates emit the listener snippet.
4. Update `vystak-channel-slack` and `vystak-channel-chat` server templates to use `AgentClient`.
5. `WorkspaceOverride` + overlay loader in `vystak-cli` + `--env` / `-e` flag on `plan`/`apply`/`destroy`/`status`/`logs`. Ships *before* the NATS package so a single repo can keep base on HTTP and opt a single environment onto NATS during migration.
6. `vystak-transport-nats` package + Docker provider integration (`NatsContainerNode`) + `examples/docker-multi-agent-nats/` example.
7. Docs update (transport concept, schema reference, environment overlays, examples).
8. *Future PR, separate spec.* `vystak-transport-azure-service-bus` + Azure provider integration.

## Open questions

None blocking. Intentionally deferred to implementation:

- Exact slug-length truncation strategy for canonical names that exceed 63 chars after slugging (short hash suffix vs. deterministic truncation).
- JetStream stream retention / max-age policy defaults for NATS (likely short TTL bound to task timeout; finalise when writing `NatsTransport`).
- SB request/reply reply-queue topology — one reply queue per caller replica vs. one shared reply queue with session-id routing. Both work; pick when implementing the SB transport in the follow-up spec.
