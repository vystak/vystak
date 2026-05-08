---
title: Telemetry
sidebar_label: Telemetry
---

# Telemetry

Vystak deployments emit OpenTelemetry traces by default when telemetry is configured on `Platform`. Channels and agents are pre-instrumented; trace context (W3C `traceparent`) propagates across HTTP and NATS so a single user message produces one connected trace from the entry channel through every agent it touches.

## Turning it on

Add `telemetry=...` to `Platform`. With Docker, the simplest form is enough:

```python
import vystak as ast

docker = ast.Provider(name="docker", type="docker")
platform = ast.Platform(
    name="local",
    type="docker",
    provider=docker,
    telemetry=ast.Telemetry(),
)
```

When telemetry is enabled and no `endpoint` is set, the Docker provider auto-provisions a `jaegertracing/all-in-one` container on `vystak-net` and points every agent and channel at its OTLP gRPC endpoint. The Jaeger UI is then available on `http://localhost:16686`.

To send to your own collector instead of the bundled Jaeger:

```python
telemetry=ast.Telemetry(endpoint="http://my-collector:4317")
```

To turn it off entirely, omit the field — agents and channels skip OTel init and pay no instrumentation cost.

## What gets instrumented

- **FastAPI** — every inbound HTTP request (e.g. an agent's `/a2a` endpoint) becomes a server span automatically.
- **httpx** — outbound HTTP from agents and channels (subagent calls, model calls) becomes a client span automatically and injects `traceparent`.
- **NATS path** — `traceparent` is injected into the JSON-RPC envelope's `params._meta.headers` on publish, and the NATS↔HTTP bridge inside the receiving agent extracts it and starts the agent-side span as a child of the caller's.
- **Slack channel** — the Socket Mode handler doesn't go through FastAPI, so the channel manually wraps each `message` and `app_mention` event in a root span (`slack.message` / `slack.app_mention`). Without this, traces from Slack would be disconnected.

The result: a single Slack `@bot` mention that the coordinator agent forwards to two specialist agents shows up as one trace with ~150–200 spans across four services in Jaeger.

## Service naming

Each container reports under a deterministic `service.name`:

| Component | service.name |
|-----------|--------------|
| Agent | `vystak-{agent-name}` |
| Chat channel | `vystak-channel-chat` |
| Slack channel | `vystak-channel-slack` |
| Discord channel | `vystak-channel-discord` |
| Bundled Jaeger | `jaeger-all-in-one` |

So a Jaeger query like *"Service: vystak-channel-slack, Operation: slack.app_mention"* gives you the entry point of every Slack-triggered turn.

## Suppressed noise

The bundled telemetry init registers a `SpanProcessor` that downgrades known a2a-sdk control-flow exceptions (currently `culsans.QueueShutDown` on `a2a.server.events.event_queue_v2.*` paths) from `ERROR` to `UNSET`. The a2a-sdk uses these as end-of-stream signals, catches them internally, and does not propagate them — but its `@trace_function` decorator stamps the span ERROR before the catch fires. Without the suppressor, every successful turn would surface 3+ red spans in Jaeger that don't represent failures.

Real exceptions on the same code path (`ValueError`, `RuntimeError`, etc.) still surface as ERROR. A span with both a benign and a real exception stays ERROR.

## Disabling telemetry per-environment

Set the env var `OTEL_EXPORTER_OTLP_ENDPOINT` to empty in a specific environment to disable export at runtime without changing your `vystak.py`:

```bash
OTEL_EXPORTER_OTLP_ENDPOINT= vystak apply
```

The agent and channel containers detect the unset endpoint and skip OTel init entirely.
