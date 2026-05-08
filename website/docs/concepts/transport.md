---
title: Transport
sidebar_label: Transport
---

# Transport

A **transport** is the east-west messaging layer for an agent system — it carries traffic from channels to agents and between agents calling each other (A2A). It is independent of how users reach an agent (that's the [channel](/docs/concepts/channels)) and independent of where the agent runs (that's the [platform](/docs/concepts/providers-and-platforms)).

Two transports ship today: **HTTP** (default) and **NATS** (JetStream-backed). Both speak the same A2A JSON-RPC contract on the wire, so switching is a one-line change on `Platform`. Azure Service Bus is on the roadmap.

## Where it lives

Transport is an embedded field on `Platform`:

```python
import vystak

transport = vystak.Transport(
    name="nats-bus",
    type="nats",
    config=vystak.NatsConfig(subject_prefix="myapp"),
)

platform = vystak.Platform(
    name="docker",
    type="docker",
    provider=vystak.Provider(name="docker", type="docker"),
    transport=transport,
)
```

When `transport` is not set, a default HTTP transport named `default-http` is synthesised automatically by `Platform`'s model validator:

```python
# These two are equivalent:
Platform(name="docker", type="docker", provider=...)
Platform(name="docker", type="docker", provider=...,
         transport=Transport(name="default-http", type="http"))
```

You only need to set `transport` explicitly when you want to switch to a non-HTTP backend or tune its configuration.

## Canonical addressing

You don't pick URLs. Every agent is identified by a **canonical name** (`{name}.agents.{namespace}`) and the transport derives a wire address from it. The derivation is transport-specific:

| Transport | Target | Wire address |
|-----------|--------|--------------|
| `http` | Docker | `http://{slug(name)}-{slug(namespace)}:{port}/a2a` |
| `http` | Azure ACA | HTTPS ingress FQDN provisioned by ACA (stored in deploy context) |
| `nats` | any | Subject `{prefix}.agents.{namespace}.{name}` (queue group) |
| `azure-service-bus` | Azure | Queue `{namespace}-{name}` with session-based reply |

When Vystak deploys a multi-agent system, it computes the peer-route map for every agent and injects it as `VYSTAK_ROUTES_JSON`. Agent code never constructs a URL by hand.

## How tools use it

The `ask_agent()` helper is the standard way for one agent to call another. Import it from `vystak.transport`:

```python
from vystak.transport import ask_agent

async def ask_time_agent(question: str) -> str:
    return await ask_agent("time-agent", question)
```

The transport is wired up at deploy time; your tool code stays the same regardless of whether the system runs over HTTP locally or over NATS in production.

Compare that to writing the call by hand:

```python
import uuid
from a2a.client import create_client
from a2a.types import Message, Part, Role, SendMessageRequest

async def ask_time_agent(question: str) -> str:
    client = await create_client(
        agent="http://vystak-time-agent:8000",
        relative_card_path="/.well-known/agent.json",
    )
    request = SendMessageRequest(
        message=Message(
            role=Role.ROLE_USER,
            message_id=uuid.uuid4().hex,
            parts=[Part(text=question)],
        ),
    )
    parts: list[str] = []
    async for event in client.send_message(request):
        kind = event.WhichOneof("payload")
        if kind == "status_update":
            msg = event.status_update.status.message
            if msg and msg.parts:
                parts = [p.text for p in msg.parts if p.text]
    return "".join(parts) or "(no response)"
```

The three-line version is shorter and transport-agnostic. It also lets vystak swap HTTP for NATS without you having to switch SDK contracts.

(For agent-to-agent calls within a project that declares `subagents:`, vystak generates exactly the call above as an `ask_<peer>` LangChain tool — you usually don't write it by hand. See [Multi-agent](/docs/concepts/multi-agent).)

## Replication and reply correlation

The transport handles load balancing and per-call reply routing transparently.

For **HTTP**, the platform's load balancer distributes inbound `/a2a` requests across agent replicas and the TCP connection carries the reply back.

For **NATS**, agents join a queue group on their canonical subject; NATS delivers each message to exactly one member. Replies go to a per-call inbox (`_INBOX.{random}`). Inside the agent container, a small NATS↔HTTP bridge subscribes to the agent's subject and proxies each request to its local `/a2a` endpoint, so the same a2a-sdk server-side plumbing handles both transports — only the inbound delivery differs.

For **Azure Service Bus** (planned), agents compete on a shared queue; reply correlation uses a Service Bus session ID attached to the original message.

In all cases the A2A envelope carries a `correlation_id` field that ties a reply to its request, so callers can multiplex many in-flight calls over a single transport connection.

## Selecting a transport

The transport is set on `Platform`. Switching is a one-line change — agent code, channel config, and tool implementations are all unchanged.

### HTTP (default)

```python
import vystak as ast

docker = ast.Provider(name="docker", type="docker")
platform = ast.Platform(name="local", type="docker", provider=docker)
```

No `transport=...` argument needed. Each agent runs a FastAPI server, channels and peers POST JSON-RPC `message/send` (or `message/stream` for SSE) at `/a2a`. The Docker provider gives every agent its own DNS name on the shared `vystak-net` network, so peers reach each other by canonical name.

### NATS (JetStream)

```python
import vystak as ast

docker = ast.Provider(name="docker", type="docker")
platform = ast.Platform(
    name="local",
    type="docker",
    provider=docker,
    transport=ast.Transport(
        name="bus",
        type="nats",
        config=ast.NatsConfig(jetstream=True, subject_prefix="vystak"),
    ),
)
```

The Docker provider auto-provisions a `nats:2-alpine` container with JetStream enabled, wires every agent and channel container with `VYSTAK_TRANSPORT_TYPE=nats` and `VYSTAK_NATS_URL`, and computes the per-agent subject from the canonical name. Peer calls are queue-grouped publishes — replication and load-balancing happen at the NATS layer, not at an HTTP load balancer.

The wire envelope is identical (A2A JSON-RPC); the only behavioural change is how messages are delivered. See [`examples/docker-multi-chat-nats/`](https://github.com/vystak/vystak/tree/main/examples/docker-multi-chat-nats) for a full multi-agent + Slack + chat-channel deployment.
