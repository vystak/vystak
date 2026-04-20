---
title: Transport
sidebar_label: Transport
---

# Transport

A **transport** is the east-west messaging layer for an agent system — it carries traffic from channels to agents and between agents calling each other (A2A). It is independent of how users reach an agent (that's the [channel](/docs/concepts/channels)) and independent of where the agent runs (that's the [platform](/docs/concepts/providers-and-platforms)).

Today the only shipping transport is **HTTP**. NATS and Azure Service Bus are on the roadmap and will follow the same schema once they land.

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

Compare that to writing the call by hand before the transport abstraction existed:

```python
import httpx, json, uuid

async def ask_time_agent(question: str) -> str:
    payload = {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": "tasks/send",
        "params": {
            "id": str(uuid.uuid4()),
            "message": {"role": "user", "parts": [{"text": question}]},
            "metadata": {},
        },
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post("http://time-agent-default:8000/a2a", json=payload)
        resp.raise_for_status()
        body = resp.json()
    parts = body["result"]["status"]["message"]["parts"]
    return "".join(p.get("text", "") for p in parts)
```

The three-line version is shorter and transport-agnostic.

## Replication and reply correlation

The transport handles load balancing and per-call reply routing transparently.

For **HTTP**, the platform's load balancer distributes inbound `/a2a` requests across agent replicas and the TCP connection carries the reply back.

For **NATS** (planned), agents join a queue group on their canonical subject; NATS delivers each message to exactly one member. Replies go to a per-call inbox (`_INBOX.{random}`).

For **Azure Service Bus** (planned), agents compete on a shared queue; reply correlation uses a Service Bus session ID attached to the original message.

In all cases the A2A envelope carries a `correlation_id` field that ties a reply to its request, so callers can multiplex many in-flight calls over a single transport connection.
