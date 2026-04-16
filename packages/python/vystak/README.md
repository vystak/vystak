# vystak

Core SDK for Vystak — declarative, platform-agnostic orchestration for AI agents.

This package provides the foundational schema, hashing engine, provisioning graph, and provider base classes that the rest of the Vystak ecosystem builds on. You typically don't install this directly — use [`vystak-cli`](https://pypi.org/project/vystak-cli/) instead, which pulls it in.

## Install

```bash
pip install vystak
```

## What's in this package

- **`vystak.schema`** — Pydantic models for `Agent`, `Model`, `Provider`, `Platform`, `Channel`, `Service`, `Skill`, `Workspace`, `Secret`, `Mcp`. This is the contract adapters and providers consume.
- **`vystak.hash`** — content-addressable hashing (`AgentHashTree`) for stateless change detection.
- **`vystak.provisioning`** — `ProvisionGraph`, a DAG of `Provisionable` nodes for topological resource rollout with health checks.
- **`vystak.providers`** — `PlatformProvider`, `FrameworkAdapter`, `ChannelAdapter` ABCs.
- **`vystak.stores`** — async SQLite-backed key-value store for long-term memory.

## Example

```python
import vystak as ast

anthropic = ast.Provider(name="anthropic", type="anthropic")
model = ast.Model(name="claude", provider=anthropic, model_name="claude-sonnet-4-20250514")
agent = ast.Agent(name="support-bot", model=model)
```

See the [main repository](https://github.com/vystak/vystak) for the full CLI, adapters, and providers.

## License

Apache-2.0
