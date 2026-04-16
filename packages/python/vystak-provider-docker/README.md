# vystak-provider-docker

Platform provider that deploys Vystak agents to Docker.

## Install

```bash
pip install vystak-provider-docker
```

Usually you don't install this directly — [`vystak-cli`](https://pypi.org/project/vystak-cli/) depends on it and invokes it automatically when your agent's `platform.type` is `docker`.

## What it does

On `vystak apply`, the provider builds a `ProvisionGraph` and rolls out, in topological order:

- **Docker network** (`vystak-net`) — shared bridge for inter-agent A2A calls
- **Postgres containers** — managed session / memory stores (if declared)
- **SQLite volumes** — persistent local-only alternative
- **Agent container** — builds the image from generated code, runs it on the shared network
- **Gateway container** — optional; routes Slack / OpenAI-compatible traffic to one or more agents

Each node has a health check; the provider waits for each to report healthy before proceeding to dependents.

## License

Apache-2.0
