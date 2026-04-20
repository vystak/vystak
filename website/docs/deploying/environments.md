---
title: Environment Overlays
sidebar_label: Environments
---

# Environment Overlays

Different environments often need different transports. A typical setup uses plain HTTP locally (no broker to run) and NATS or Azure Service Bus in staging and production. Environment overlays let you swap the transport — or any other platform-level config — without duplicating your entire agent definition.

## File naming

Place an overlay file next to your base `vystak.py` and name it `vystak.<env>.py`:

```
my-project/
├── vystak.py          # base definition (all agents)
├── vystak.prod.py     # production overlay
└── vystak.staging.py  # staging overlay
```

Python-file overlays are the only format supported in v1. YAML overlay support is a planned follow-up.

## Overlay shape

An overlay file must expose a module-level `override` binding of type `EnvironmentOverride`. The `transports` dict maps a **platform name** to the replacement `Transport` to use for that platform:

```python
# vystak.prod.py
import vystak
from vystak.schema.overrides import EnvironmentOverride

override = EnvironmentOverride(
    transports={
        "docker": vystak.Transport(
            name="nats-prod",
            type="nats",
            config=vystak.NatsConfig(
                subject_prefix="myapp-prod",
            ),
            connection=vystak.TransportConnection(
                url_env="NATS_URL",
            ),
        ),
    }
)
```

When `apply` loads this overlay, every agent whose `platform.name` is `"docker"` gets the NATS transport instead of the default HTTP one. Agents on a different platform are unchanged.

## CLI

Pass `--env` to `vystak apply` or set the `VYSTAK_ENV` environment variable:

```bash
# Named flag
vystak apply --env prod

# Env var (useful in CI)
VYSTAK_ENV=prod vystak apply
```

The `--env` flag is supported on `apply` only in v1. `plan`, `destroy`, `status`, and `logs` still use the base configuration.

## Merge semantics

Each entry in `transports` **fully replaces** the matching platform's transport. There is no field-level merging — if you override a platform's transport, the entire `Transport` object is swapped for the value in the overlay.

Validation is eager: if any key in `transports` does not match a platform name present in the loaded agents, Vystak raises a `ValueError` at load time. This catches typos before any infrastructure is touched.

The original agent list is not mutated. `EnvironmentOverride.apply()` returns a new list of deep-copied agents, so re-applying the same overlay is safe.

## Hash tree interaction

Changing the transport `type` or `config` in an overlay will trigger a redeploy because `hash_agent` includes both fields in the content hash.

Changing only the transport `connection` (the `url_env` / `credentials_secret` fields for BYO brokers) does **not** trigger a redeploy. Connection details are intentionally excluded from the hash — they are portable across environments and you can rotate them without rebuilding containers.

In practice this means:
- Switching from HTTP to NATS in prod the first time: redeploy.
- Rotating the NATS URL secret after the broker migrates: no redeploy needed.
