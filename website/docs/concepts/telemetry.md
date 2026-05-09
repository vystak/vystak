---
title: Telemetry
sidebar_label: Telemetry
---

# Telemetry

Vystak deployments emit OpenTelemetry **traces and metrics** when telemetry is configured on `Platform`. Channels and agents are pre-instrumented; trace context (W3C `traceparent`) propagates across HTTP and NATS so a single user message produces one connected trace from the entry channel through every agent it touches. Token-usage metrics from each model call ship to the same endpoint.

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

When telemetry is enabled and no `endpoint` is set, the Docker provider auto-provisions a [`grafana/otel-lgtm`](https://github.com/grafana/docker-otel-lgtm) container on `vystak-net`. It bundles **Tempo** (traces) + **Mimir** (metrics) + **Grafana** (UI) behind a single OTLP gRPC receiver, so traces and metrics land in one place and you browse them through one UI at `http://localhost:13000`.

To send to your own collector instead:

```python
telemetry=ast.Telemetry(endpoint="http://my-collector:4317")
```

To turn it off entirely, omit the field — agents and channels skip OTel init and pay no instrumentation cost.

## What gets instrumented

- **FastAPI** — every inbound HTTP request (e.g. an agent's `/a2a` endpoint) becomes a server span automatically.
- **httpx** — outbound HTTP from agents and channels (subagent calls, model calls) becomes a client span automatically and injects `traceparent`.
- **NATS path** — `traceparent` is injected into the JSON-RPC envelope's `params._meta.headers` on publish, and the NATS↔HTTP bridge inside the receiving agent extracts it and starts the agent-side span as a child of the caller's.
- **Slack channel** — the Socket Mode handler doesn't go through FastAPI, so the channel manually wraps each `message` and `app_mention` event in a root span (`slack.message` / `slack.app_mention`). Without this, traces from Slack would be disconnected.
- **GenAI calls** — a LangChain callback handler reads `usage_metadata` off each model response and emits OTel histogram metrics (see below) plus span attributes per the [OTel GenAI semantic conventions](https://opentelemetry.io/docs/specs/semconv/gen-ai/).

The result: a single Slack `@bot` mention that the coordinator agent forwards to two specialist agents shows up as one trace with ~150–200 spans across four services, plus one or more histogram data points per model call on the metrics side.

## Token-usage metrics

Every chat-model call publishes:

| Instrument | Type | Description |
|------------|------|-------------|
| `gen_ai.client.token.usage` | Histogram | Tokens consumed per call. One data point per direction. |
| `gen_ai.client.operation.duration` | Histogram | Wall-clock time for the model call (seconds). |

The token histogram is broken down by `gen_ai.token.type` ∈ `{input, output, cache_read, cache_creation}`. Other attributes on every metric:

| Attribute | Example | Source |
|-----------|---------|--------|
| `gen_ai.system` | `anthropic` | Default for Vystak's anthropic-compat endpoints |
| `gen_ai.request.model` | `claude-haiku-4-5-20251001` | LangChain `response_metadata.model` |
| `service.name` | `vystak-assistant-agent` | Resource attribute set on the MeterProvider |

The same numbers are also stamped as span attributes on whichever span is active when the model returns (typically the agent's `/a2a` server span):

- `gen_ai.usage.input_tokens`
- `gen_ai.usage.output_tokens`
- `gen_ai.usage.cache_read_input_tokens`
- `gen_ai.usage.cache_creation_input_tokens`
- `gen_ai.request.model`, `gen_ai.system`

In Grafana, query the metrics with PromQL:

```promql
# Total input tokens across all agents in the last hour
sum(rate(gen_ai_client_token_usage_sum{gen_ai_token_type="input"}[1h]))

# Cache hit ratio per agent
sum by (service_name) (rate(gen_ai_client_token_usage_sum{gen_ai_token_type="cache_read"}[5m]))
  /
sum by (service_name) (rate(gen_ai_client_token_usage_sum{gen_ai_token_type="input"}[5m]))
```

## Service naming

Each container reports under a deterministic `service.name`:

| Component | service.name |
|-----------|--------------|
| Agent | `vystak-{agent-name}` |
| Chat channel | `vystak-channel-chat` |
| Slack channel | `vystak-channel-slack` |
| Discord channel | `vystak-channel-discord` |

So a Tempo query like *"Service: vystak-channel-slack, Operation: slack.app_mention"* gives you the entry point of every Slack-triggered turn.

## Suppressed noise

The bundled telemetry init registers a `SpanProcessor` that downgrades known a2a-sdk control-flow exceptions (currently `culsans.QueueShutDown` on `a2a.server.events.event_queue_v2.*` paths) from `ERROR` to `UNSET`. The a2a-sdk uses these as end-of-stream signals, catches them internally, and does not propagate them — but its `@trace_function` decorator stamps the span ERROR before the catch fires. Without the suppressor, every successful turn would surface 3+ red spans that don't represent failures.

Real exceptions on the same code path (`ValueError`, `RuntimeError`, etc.) still surface as ERROR. A span with both a benign and a real exception stays ERROR.

## Disabling telemetry per-environment

Set the env var `OTEL_EXPORTER_OTLP_ENDPOINT` to empty in a specific environment to disable export at runtime without changing your `vystak.py`:

```bash
OTEL_EXPORTER_OTLP_ENDPOINT= vystak apply
```

The agent and channel containers detect the unset endpoint and skip OTel init entirely.
