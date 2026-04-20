# Transport Abstraction — Plan A (Abstraction + HTTP + Environment Overlays)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Introduce a pluggable `Transport` abstraction for east-west A2A traffic (channel→agent, agent→agent), extract existing HTTP behaviour into a concrete `HttpTransport`, and add per-environment config overlays driven by a `--env` CLI flag. No user-visible wire-protocol change: HTTP remains the default and backward compatibility is maintained.

**Architecture:** New module `vystak.transport` holds the ABC (`Transport`, `A2AHandler`, `AgentClient`, `ask_agent`, naming helpers). Existing `/a2a` handler logic is extracted from the LangChain adapter into a transport-agnostic `A2AHandler` imported from `vystak.transport`. A new `vystak-transport-http` package implements `Transport` using FastAPI + httpx. Channel plugins (`vystak-channel-slack`, `vystak-channel-chat`) stop using `httpx` directly and route through `AgentClient`. A new Pydantic `Transport` resource is added to the schema; `Platform.transport` references it by name. `WorkspaceOverride` + `vystak apply --env <name>` enables per-environment config swaps.

**Tech Stack:** Python 3.11+, Pydantic v2, FastAPI, httpx, sse-starlette, pytest, uv workspace.

---

## Plan Errata (2026-04-19, post-Task-1)

When writing the plan I mis-modelled the existing schema: the spec referenced a top-level `Workspace` bundle with `.agents`, `.platforms`, `.transports`, `.services` lists. **That class does not exist in this codebase.** The existing `Workspace` is a per-agent execution sandbox (filesystem / terminal / browser flags). Users declare `Agent`, `Channel`, `Platform`, etc. as module-level variables in `vystak.py`; the CLI loader scans the module for `Agent` and `Channel` instances into a `Definitions` dataclass.

**The repo-wide pattern is embedded objects, not name-refs**: `Agent.platform: Platform`, `Platform.provider: Provider`. This plan is realigned to use the same pattern for transport.

**Realignment (decided 2026-04-19, user-approved):**

- `Platform` gains `transport: Transport | None = None` — a direct instance, not a name ref. Populated by a `Platform` model-validator that synthesises `Transport(name="default-http", type="http")` when unset.
- No top-level `Workspace.transports` list; no synthesis logic on a bundle.
- `EnvironmentOverride` (renamed from `WorkspaceOverride`) operates on the `Definitions` dataclass produced by the loader, not on a `Workspace`. Shape: `{platforms: dict[str, PlatformOverride]}` where `PlatformOverride.transport: Transport | None` replaces `platform.transport` wholesale.
- No new transport-scanning in the CLI loader — transports are embedded in platforms, so overlays find them by walking `definitions.agents` and inspecting `.platform`.

**Tasks affected:** 2 (rewritten below), 17, 18, 19, 20, 21, 22, 23. Tasks 1, 3–16, and 24–26 are unaffected (they touch `vystak.transport` internals, which are orthogonal to the schema wiring). **Tasks 17–23 must be rewritten in-place when the plan reaches them** — they currently still reference the old Workspace model; do not execute them as-written.

The spec document (`docs/superpowers/specs/2026-04-19-transport-abstraction-design.md`) will get a matching erratum when the plan reaches Task 25 (docs).

---

## Important Notes for the Engineer

- **Package name is `vystak`, not `agentstack`.** Older plans in this directory reference the legacy name; ignore that.
- **Live CI gates (must stay green after every commit):** `just lint-python`, `just test-python`, `just typecheck-typescript`, `just test-typescript`. `typecheck-python` and `lint-typescript` have pre-existing failures; **don't regress them further** but don't attempt to fix unrelated issues.
- **Codegen strings with long lines:** `vystak-adapter-langchain/a2a.py` and `templates.py` have `per-file-ignores` for E501. Keep that; don't break existing long lines inside generated code.
- **Test-mock import quirks:** `vystak_provider_docker.network` and `vystak_provider_docker.resources` have intentional `import docker` / `import docker.errors` lines preserved via `# noqa: F401` — keep.
- **Test fixtures elsewhere use obvious fakes** (`testpass`, `mock-*`, `test-sub-123`). Follow that convention.
- **The generated agent gains `vystak` as a runtime dependency.** `generate_requirements_txt` in `vystak-adapter-langchain/templates.py` must include `vystak>=0.1` once `vystak.transport` is consumed by the generated server.
- **Frequent commits.** One commit per task minimum (often several). Each task's final step is an explicit commit.

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `packages/python/vystak/src/vystak/schema/transport.py` | Create | `Transport`, `TransportConnection`, `HttpConfig`, `NatsConfig`, `ServiceBusConfig` Pydantic models |
| `packages/python/vystak/src/vystak/schema/overrides.py` | Create | `WorkspaceOverride`, `TransportOverride`, `PlatformOverride` + `apply()` merge function |
| `packages/python/vystak/src/vystak/schema/platform.py` | Modify | Add `transport: str \| None` field |
| `packages/python/vystak/src/vystak/schema/workspace.py` | Modify | Add `transports: list[Transport]` field + default-http synthesis + validator |
| `packages/python/vystak/src/vystak/schema/__init__.py` | Modify | Export new schema models |
| `packages/python/vystak/src/vystak/transport/__init__.py` | Create | Public exports: `Transport`, `AgentRef`, `AgentClient`, `ask_agent`, `A2AHandler`, `A2AMessage`, etc. |
| `packages/python/vystak/src/vystak/transport/types.py` | Create | `AgentRef`, `A2AMessage`, `A2AEvent`, `A2AResult` Pydantic models |
| `packages/python/vystak/src/vystak/transport/base.py` | Create | `Transport` ABC |
| `packages/python/vystak/src/vystak/transport/naming.py` | Create | `slug()`, canonical-name helpers, address format helpers |
| `packages/python/vystak/src/vystak/transport/handler.py` | Create | `A2AHandler` — transport-agnostic request dispatcher |
| `packages/python/vystak/src/vystak/transport/client.py` | Create | `AgentClient` + `ask_agent` helper |
| `packages/python/vystak/src/vystak/transport/contract.py` | Create | `TransportContractTests` — shared pytest mixin / parametrized tests for any concrete `Transport` |
| `packages/python/vystak/src/vystak/providers/base.py` | Modify | Add `TransportPlugin` ABC |
| `packages/python/vystak/src/vystak/hash/tree.py` | Modify | Incorporate `platform.transport` ref + resolved transport type/config |
| `packages/python/vystak/tests/transport/test_naming.py` | Create | Naming tests |
| `packages/python/vystak/tests/transport/test_types.py` | Create | A2A type tests |
| `packages/python/vystak/tests/transport/test_base.py` | Create | ABC tests |
| `packages/python/vystak/tests/transport/test_handler.py` | Create | Handler tests |
| `packages/python/vystak/tests/transport/test_client.py` | Create | Client tests |
| `packages/python/vystak/tests/schema/test_transport_schema.py` | Create | Transport/Platform/Workspace schema tests |
| `packages/python/vystak/tests/schema/test_overrides.py` | Create | Overrides tests |
| `packages/python/vystak-transport-http/pyproject.toml` | Create | Package manifest |
| `packages/python/vystak-transport-http/src/vystak_transport_http/__init__.py` | Create | Public exports |
| `packages/python/vystak-transport-http/src/vystak_transport_http/transport.py` | Create | `HttpTransport` concrete |
| `packages/python/vystak-transport-http/src/vystak_transport_http/plugin.py` | Create | `HttpTransportPlugin` |
| `packages/python/vystak-transport-http/tests/test_http_transport.py` | Create | Passes `TransportContractTests` |
| `packages/python/vystak-transport-http/tests/test_http_plugin.py` | Create | Plugin tests |
| `pyproject.toml` (root) | Modify | Add `vystak-transport-http` to workspace members |
| `packages/python/vystak-adapter-langchain/src/vystak_adapter_langchain/a2a.py` | Modify | FastAPI route delegates to `A2AHandler` from `vystak.transport`; wire generation unchanged |
| `packages/python/vystak-adapter-langchain/src/vystak_adapter_langchain/templates.py` | Modify | Emit transport listener startup; add `vystak` to `requirements.txt` |
| `packages/python/vystak-channel-slack/src/vystak_channel_slack/plugin.py` | Modify | Update `generate_code` to take `dict[str, AgentRef]` |
| `packages/python/vystak-channel-slack/src/vystak_channel_slack/server_template.py` | Modify | Use `AgentClient` instead of raw `httpx` |
| `packages/python/vystak-channel-chat/src/vystak_channel_chat/plugin.py` | Modify | Same |
| `packages/python/vystak-channel-chat/src/vystak_channel_chat/server_template.py` | Modify | Same |
| `packages/python/vystak-provider-docker/src/vystak_provider_docker/provider.py` | Modify | Load `TransportPlugin` from schema; pass to generators |
| `packages/python/vystak-provider-azure/src/vystak_provider_azure/provider.py` | Modify | Same |
| `packages/python/vystak-cli/src/vystak_cli/loader.py` | Modify | Overlay file resolution + merge |
| `packages/python/vystak-cli/src/vystak_cli/main.py` | Modify | `--env` / `-e` flag on `plan`, `apply`, `destroy`, `status`, `logs` |
| `packages/python/vystak-cli/tests/test_loader_overlay.py` | Create | Overlay loader tests |
| `examples/multi-agent/assistant/tools/ask_time_agent.py` | Modify | Use `ask_agent()` |
| `examples/multi-agent/assistant/tools/ask_weather_agent.py` | Modify | Use `ask_agent()` |
| `examples/multi-agent/vystak.py` | Modify | Declare `Transport` resource, reference in `Platform` |

---

### Task 1: Transport schema — Pydantic models

**Files:**
- Create: `packages/python/vystak/src/vystak/schema/transport.py`
- Modify: `packages/python/vystak/src/vystak/schema/__init__.py`
- Create: `packages/python/vystak/tests/schema/test_transport_schema.py`

- [ ] **Step 1: Write failing tests**

Create `packages/python/vystak/tests/schema/test_transport_schema.py`:

```python
"""Tests for Transport schema models."""

import pytest
from pydantic import ValidationError

from vystak.schema import (
    HttpConfig,
    NatsConfig,
    ServiceBusConfig,
    Transport,
    TransportConnection,
)


class TestTransport:
    def test_minimal_http(self):
        t = Transport(name="default", type="http")
        assert t.name == "default"
        assert t.type == "http"
        assert t.config is None
        assert t.connection is None

    def test_nats_with_config(self):
        t = Transport(
            name="bus",
            type="nats",
            config=NatsConfig(jetstream=True, subject_prefix="vystak"),
        )
        assert t.type == "nats"
        assert t.config.jetstream is True
        assert t.config.subject_prefix == "vystak"

    def test_service_bus_with_byo(self):
        t = Transport(
            name="bus",
            type="azure-service-bus",
            connection=TransportConnection(
                url_env="SB_URL",
                credentials_secret="sb-creds",
            ),
            config=ServiceBusConfig(namespace_name="my-sb-ns"),
        )
        assert t.connection.url_env == "SB_URL"
        assert t.config.namespace_name == "my-sb-ns"
        assert t.config.use_sessions is True

    def test_invalid_type_rejected(self):
        with pytest.raises(ValidationError):
            Transport(name="x", type="kafka")

    def test_canonical_name(self):
        t = Transport(name="bus", type="nats", namespace="prod")
        assert t.canonical_name == "bus.transports.prod"

    def test_canonical_name_default_namespace(self):
        t = Transport(name="bus", type="nats")
        assert t.canonical_name == "bus.transports.default"


class TestNatsConfig:
    def test_defaults(self):
        c = NatsConfig()
        assert c.type == "nats"
        assert c.jetstream is True
        assert c.subject_prefix == "vystak"
        assert c.stream_name is None
        assert c.max_message_size_mb == 1


class TestServiceBusConfig:
    def test_defaults(self):
        c = ServiceBusConfig()
        assert c.type == "azure-service-bus"
        assert c.use_sessions is True
        assert c.namespace_name is None


class TestHttpConfig:
    def test_defaults(self):
        c = HttpConfig()
        assert c.type == "http"


class TestTransportConnection:
    def test_both_optional(self):
        c = TransportConnection()
        assert c.url_env is None
        assert c.credentials_secret is None

    def test_byo(self):
        c = TransportConnection(url_env="FOO_URL", credentials_secret="foo-creds")
        assert c.url_env == "FOO_URL"
```

- [ ] **Step 2: Run tests and verify they fail**

```bash
cd /Users/akolodkin/Developer/work/AgentsStack
uv run pytest packages/python/vystak/tests/schema/test_transport_schema.py -v
```

Expected: FAIL with `ImportError: cannot import name 'Transport' from 'vystak.schema'`.

- [ ] **Step 3: Create `transport.py`**

Create `packages/python/vystak/src/vystak/schema/transport.py`:

```python
"""Transport resource schema — declares how east-west A2A traffic flows."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class TransportConnection(BaseModel):
    """BYO connection details for an externally-managed broker.

    When set, the provider will not provision broker infrastructure and will
    instead plumb these values through to agents and channels.
    """

    url_env: str | None = None
    credentials_secret: str | None = None


class HttpConfig(BaseModel):
    """HTTP transport config. Currently empty; reserved for future tuning."""

    type: Literal["http"] = "http"


class NatsConfig(BaseModel):
    """NATS transport config."""

    type: Literal["nats"] = "nats"
    jetstream: bool = True
    subject_prefix: str = "vystak"
    stream_name: str | None = None
    max_message_size_mb: int = 1


class ServiceBusConfig(BaseModel):
    """Azure Service Bus transport config."""

    type: Literal["azure-service-bus"] = "azure-service-bus"
    namespace_name: str | None = None
    use_sessions: bool = True


TransportType = Literal["http", "nats", "azure-service-bus"]
TransportConfig = HttpConfig | NatsConfig | ServiceBusConfig


class Transport(BaseModel):
    """Declares a transport for east-west A2A traffic on a Platform."""

    name: str
    type: TransportType
    namespace: str | None = None
    connection: TransportConnection | None = None
    config: TransportConfig | None = Field(default=None, discriminator="type")

    @property
    def canonical_name(self) -> str:
        ns = self.namespace or "default"
        return f"{self.name}.transports.{ns}"
```

- [ ] **Step 4: Export from `schema/__init__.py`**

Append the following imports and add the names to `__all__` in `packages/python/vystak/src/vystak/schema/__init__.py` (find the existing `__all__` block and add these names; don't duplicate or reorder existing entries):

```python
from vystak.schema.transport import (
    HttpConfig,
    NatsConfig,
    ServiceBusConfig,
    Transport,
    TransportConfig,
    TransportConnection,
    TransportType,
)
```

Add `"HttpConfig"`, `"NatsConfig"`, `"ServiceBusConfig"`, `"Transport"`, `"TransportConfig"`, `"TransportConnection"`, `"TransportType"` to the `__all__` list.

- [ ] **Step 5: Run tests and verify they pass**

```bash
uv run pytest packages/python/vystak/tests/schema/test_transport_schema.py -v
```

Expected: all 10 tests PASS.

- [ ] **Step 6: Run full lint + test**

```bash
just lint-python && just test-python
```

Expected: both PASS (no regressions).

- [ ] **Step 7: Commit**

```bash
git add packages/python/vystak/src/vystak/schema/transport.py \
        packages/python/vystak/src/vystak/schema/__init__.py \
        packages/python/vystak/tests/schema/test_transport_schema.py
git commit -m "feat(schema): add Transport resource Pydantic models

Introduces Transport, TransportConnection, and discriminated-union configs
(HttpConfig, NatsConfig, ServiceBusConfig) as the foundation for the
transport abstraction. No behaviour change yet — Platform and Workspace
integration lands in a follow-up commit."
```

---

### Task 2: Embed `transport` on `Platform`

**Files:**
- Modify: `packages/python/vystak/src/vystak/schema/platform.py`
- Modify: `packages/python/vystak/tests/schema/test_transport_schema.py`

**What this task does:** Add `transport: Transport | None = None` to `Platform`. A `model_validator(mode="after")` on `Platform` fills in a default `Transport(name="default-http", type="http")` when unset. This is the embedded-object pattern (matching `Platform.provider: Provider`).

**Before you begin, read:**
- `packages/python/vystak/src/vystak/schema/platform.py` — current `Platform` shape. Its fields today are `type: str`, `provider: Provider`, `namespace: str = "default"`, `config: dict = {}`. It already inherits from `NamedModel`.
- `packages/python/vystak/src/vystak/schema/transport.py` (committed in Task 1) — the `Transport` model.

- [ ] **Step 1: Write failing tests**

Append to `packages/python/vystak/tests/schema/test_transport_schema.py` (keep existing imports; the file already imports `pytest`, `ValidationError`, and the transport models):

```python
from vystak.schema import Platform, Provider


class TestPlatformTransport:
    def _provider(self) -> Provider:
        return Provider(name="docker", type="docker")

    def test_default_transport_synthesized(self):
        """Platform without an explicit transport gets a default-http."""
        p = Platform(name="main", type="docker", provider=self._provider())
        assert p.transport is not None
        assert p.transport.name == "default-http"
        assert p.transport.type == "http"

    def test_explicit_http_transport_preserved(self):
        p = Platform(
            name="main",
            type="docker",
            provider=self._provider(),
            transport=Transport(name="my-http", type="http"),
        )
        assert p.transport.name == "my-http"
        assert p.transport.type == "http"

    def test_explicit_nats_transport_preserved(self):
        p = Platform(
            name="aca",
            type="container-apps",
            provider=Provider(name="azure", type="azure"),
            transport=Transport(
                name="bus",
                type="nats",
                config=NatsConfig(jetstream=True),
            ),
        )
        assert p.transport.type == "nats"
        assert p.transport.config.jetstream is True

    def test_transport_config_mismatch_still_rejected(self):
        """The Transport-level validator (from Task 1) still fires when
        Transport is embedded in a Platform."""
        with pytest.raises(ValidationError, match="config.type"):
            Platform(
                name="main",
                type="docker",
                provider=self._provider(),
                transport=Transport(
                    name="bus", type="nats", config=HttpConfig()
                ),
            )

    def test_default_transport_is_a_new_instance_per_platform(self):
        """Two platforms should not share the same default-http instance —
        mutating one must not affect the other."""
        p1 = Platform(name="a", type="docker", provider=self._provider())
        p2 = Platform(name="b", type="docker", provider=self._provider())
        assert p1.transport is not p2.transport
```

- [ ] **Step 2: Run tests to see them fail**

```bash
uv run pytest packages/python/vystak/tests/schema/test_transport_schema.py -v -k TestPlatformTransport
```

Expected: tests fail with `Platform` rejecting the `transport=` kwarg (field doesn't exist yet).

- [ ] **Step 3: Add the `transport` field and default-synthesis validator to `Platform`**

Open `packages/python/vystak/src/vystak/schema/platform.py` and replace its body with:

```python
"""Platform model — deployment target for agents."""

from typing import Self

from pydantic import model_validator

from vystak.schema.common import NamedModel
from vystak.schema.provider import Provider
from vystak.schema.transport import Transport


class Platform(NamedModel):
    """A deployment target where agents run."""

    type: str
    provider: Provider
    namespace: str = "default"
    config: dict = {}
    transport: Transport | None = None

    @model_validator(mode="after")
    def _default_transport(self) -> Self:
        if self.transport is None:
            self.transport = Transport(name="default-http", type="http")
        return self
```

Notes:
- The validator synthesises a **new** `Transport` instance each time (critical for the `test_default_transport_is_a_new_instance_per_platform` test — Pydantic would otherwise share a class-level default).
- `Self` comes from `typing` (Python 3.11+); matches the existing style of `agent.py`.

- [ ] **Step 4: Run tests and verify they pass**

```bash
uv run pytest packages/python/vystak/tests/schema/test_transport_schema.py -v -k TestPlatformTransport
```

Expected: 5/5 new tests pass.

- [ ] **Step 5: Run full lint + test**

```bash
just lint-python && just test-python
```

Expected: PASS. If any pre-existing `Platform`-using tests break because they now assert `platform.transport is None`, update only the failing assertion to `platform.transport.type == "http"` or `platform.transport.name == "default-http"` — do not change test intent.

If `just fmt-python` auto-fixes anything (import ordering, line length), stage the formatted files and include them in the commit.

- [ ] **Step 6: Commit**

```bash
git add packages/python/vystak/src/vystak/schema/platform.py \
        packages/python/vystak/tests/schema/test_transport_schema.py
git commit -m "feat(schema): embed Transport on Platform

Platform gains a transport: Transport | None field. A model_validator
synthesises Transport(name='default-http', type='http') when unset so
every platform always resolves to a concrete transport. Matches the
existing embedded-object pattern (Platform.provider: Provider)."
```

---

### Task 3: Naming module — slug + canonical-name helpers

**Files:**
- Create: `packages/python/vystak/src/vystak/transport/__init__.py`
- Create: `packages/python/vystak/src/vystak/transport/naming.py`
- Create: `packages/python/vystak/tests/transport/__init__.py`
- Create: `packages/python/vystak/tests/transport/test_naming.py`

- [ ] **Step 1: Write failing tests**

Create `packages/python/vystak/tests/transport/__init__.py` (empty).

Create `packages/python/vystak/tests/transport/test_naming.py`:

```python
"""Tests for transport naming helpers."""

import pytest

from vystak.transport.naming import (
    canonical_agent_name,
    parse_canonical_name,
    slug,
)


class TestSlug:
    def test_lowercase(self):
        assert slug("TimeAgent") == "timeagent"

    def test_spaces_to_hyphens(self):
        assert slug("my agent") == "my-agent"

    def test_underscores_to_hyphens(self):
        assert slug("my_agent") == "my-agent"

    def test_dots_to_hyphens(self):
        assert slug("my.agent.prod") == "my-agent-prod"

    def test_strips_illegal(self):
        assert slug("my/agent!") == "myagent"

    def test_collapses_runs(self):
        assert slug("my---agent") == "my-agent"

    def test_strips_leading_trailing(self):
        assert slug("-my-agent-") == "my-agent"

    def test_truncates_at_63(self):
        long = "a" * 100
        assert len(slug(long)) == 63

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            slug("")

    def test_only_illegal_raises(self):
        with pytest.raises(ValueError):
            slug("!!!")


class TestCanonicalAgentName:
    def test_explicit_namespace(self):
        assert canonical_agent_name("time-agent", "prod") == "time-agent.agents.prod"

    def test_default_namespace(self):
        assert canonical_agent_name("time-agent") == "time-agent.agents.default"

    def test_none_namespace(self):
        assert canonical_agent_name("time-agent", None) == "time-agent.agents.default"


class TestParseCanonicalName:
    def test_basic(self):
        name, kind, ns = parse_canonical_name("time-agent.agents.prod")
        assert (name, kind, ns) == ("time-agent", "agents", "prod")

    def test_channel(self):
        name, kind, ns = parse_canonical_name("chat.channels.default")
        assert (name, kind, ns) == ("chat", "channels", "default")

    def test_invalid_format_raises(self):
        with pytest.raises(ValueError):
            parse_canonical_name("notcanonical")

    def test_wrong_kind_position_raises(self):
        with pytest.raises(ValueError):
            parse_canonical_name("a.b.c.d")
```

- [ ] **Step 2: Run tests to see them fail**

```bash
uv run pytest packages/python/vystak/tests/transport/test_naming.py -v
```

Expected: ModuleNotFoundError for `vystak.transport.naming`.

- [ ] **Step 3: Create transport package init**

Create `packages/python/vystak/src/vystak/transport/__init__.py`:

```python
"""Transport abstraction for east-west A2A traffic."""

from vystak.transport.naming import (
    canonical_agent_name,
    parse_canonical_name,
    slug,
)

__all__ = [
    "canonical_agent_name",
    "parse_canonical_name",
    "slug",
]
```

- [ ] **Step 4: Create `naming.py`**

Create `packages/python/vystak/src/vystak/transport/naming.py`:

```python
"""Naming helpers — canonical names and transport-independent slugs.

Every wire address on every transport is derived from an agent's canonical
name by the transport implementation. This module owns the input side of
that derivation.
"""

from __future__ import annotations

import re

SLUG_MAX = 63
_ALLOWED = re.compile(r"[^a-z0-9-]+")
_RUNS = re.compile(r"-+")


def slug(value: str) -> str:
    """Lowercase + normalise to `[a-z0-9-]`, max 63 chars.

    Matches the existing Azure ACA and Docker Compose naming conventions
    used throughout the repo.
    """
    if not value:
        raise ValueError("slug() received empty string")
    lowered = value.lower().replace("_", "-").replace(".", "-").replace(" ", "-")
    cleaned = _ALLOWED.sub("", lowered)
    collapsed = _RUNS.sub("-", cleaned).strip("-")
    if not collapsed:
        raise ValueError(f"slug({value!r}) produced empty result after cleaning")
    return collapsed[:SLUG_MAX]


def canonical_agent_name(name: str, namespace: str | None = None) -> str:
    """Build the canonical name for an agent.

    Matches `Agent.canonical_name` (`vystak/schema/agent.py:46`). Kept as a
    free function so transport code can build names without an Agent instance.
    """
    ns = namespace or "default"
    return f"{name}.agents.{ns}"


def parse_canonical_name(canonical: str) -> tuple[str, str, str]:
    """Parse `{name}.{kind}.{namespace}` into its three parts.

    Returns `(name, kind, namespace)`. Raises `ValueError` if the format is
    wrong.
    """
    parts = canonical.split(".")
    if len(parts) != 3:
        raise ValueError(
            f"canonical name must be '{{name}}.{{kind}}.{{namespace}}', "
            f"got {canonical!r}"
        )
    name, kind, namespace = parts
    if kind not in {"agents", "channels", "transports"}:
        raise ValueError(
            f"unknown kind {kind!r} in canonical name {canonical!r}"
        )
    return name, kind, namespace
```

- [ ] **Step 5: Run tests and verify they pass**

```bash
uv run pytest packages/python/vystak/tests/transport/test_naming.py -v
```

Expected: all 18 tests PASS.

- [ ] **Step 6: Run full lint + test**

```bash
just lint-python && just test-python
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add packages/python/vystak/src/vystak/transport/__init__.py \
        packages/python/vystak/src/vystak/transport/naming.py \
        packages/python/vystak/tests/transport/__init__.py \
        packages/python/vystak/tests/transport/test_naming.py
git commit -m "feat(transport): naming helpers — slug + canonical-name parser

Centralises slugging and canonical-name parsing in vystak.transport.naming
so every transport implementation and every provider uses the same rules."
```

---

### Task 4: A2A types — `AgentRef`, `A2AMessage`, `A2AEvent`, `A2AResult`

**Files:**
- Create: `packages/python/vystak/src/vystak/transport/types.py`
- Modify: `packages/python/vystak/src/vystak/transport/__init__.py`
- Create: `packages/python/vystak/tests/transport/test_types.py`

- [ ] **Step 1: Write failing tests**

Create `packages/python/vystak/tests/transport/test_types.py`:

```python
"""Tests for transport A2A envelope types."""

import pytest
from pydantic import ValidationError

from vystak.transport import (
    A2AEvent,
    A2AMessage,
    A2AResult,
    AgentRef,
)


class TestAgentRef:
    def test_minimal(self):
        ref = AgentRef(canonical_name="time-agent.agents.prod")
        assert ref.canonical_name == "time-agent.agents.prod"

    def test_invalid_canonical_rejected(self):
        with pytest.raises(ValidationError):
            AgentRef(canonical_name="not-canonical")


class TestA2AMessage:
    def test_text_only(self):
        m = A2AMessage.from_text("hello")
        assert m.role == "user"
        assert m.parts == [{"text": "hello"}]

    def test_with_metadata(self):
        m = A2AMessage.from_text("hi", correlation_id="c-1")
        assert m.correlation_id == "c-1"

    def test_correlation_defaults_to_uuid(self):
        m = A2AMessage.from_text("hi")
        assert m.correlation_id is not None
        assert len(m.correlation_id) > 0


class TestA2AEvent:
    def test_token(self):
        e = A2AEvent(type="token", text="hello")
        assert e.type == "token"
        assert e.text == "hello"
        assert e.final is False

    def test_final(self):
        e = A2AEvent(type="final", text="done", final=True)
        assert e.final is True


class TestA2AResult:
    def test_basic(self):
        r = A2AResult(text="reply", correlation_id="c-1")
        assert r.text == "reply"
        assert r.correlation_id == "c-1"
```

- [ ] **Step 2: Run tests to see them fail**

```bash
uv run pytest packages/python/vystak/tests/transport/test_types.py -v
```

Expected: ImportError.

- [ ] **Step 3: Create `types.py`**

Create `packages/python/vystak/src/vystak/transport/types.py`:

```python
"""A2A envelope types carried across every transport.

The wire format on every transport is the same JSON-RPC A2A envelope that
`vystak-adapter-langchain/a2a.py` emits today. These classes are the
in-process representation used by the transport ABC and the A2AHandler.
"""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, Field, field_validator

from vystak.transport.naming import parse_canonical_name


class AgentRef(BaseModel):
    """Transport-facing identity for a peer agent.

    Carries only the canonical name; the wire address is derived by the
    active transport at call time via `Transport.resolve_address()`.
    """

    canonical_name: str

    @field_validator("canonical_name")
    @classmethod
    def _validate_canonical(cls, v: str) -> str:
        # Raises ValueError if malformed, which Pydantic converts into
        # ValidationError.
        parse_canonical_name(v)
        return v


class A2AMessage(BaseModel):
    """A single A2A message (a task's input or output)."""

    role: str = "user"
    parts: list[dict[str, Any]] = Field(default_factory=list)
    correlation_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_text(
        cls,
        text: str,
        *,
        role: str = "user",
        correlation_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> "A2AMessage":
        kwargs: dict[str, Any] = {
            "role": role,
            "parts": [{"text": text}],
            "metadata": metadata or {},
        }
        if correlation_id is not None:
            kwargs["correlation_id"] = correlation_id
        return cls(**kwargs)


class A2AEvent(BaseModel):
    """A single streaming event emitted by `tasks/sendSubscribe`."""

    type: str  # "token" | "status" | "tool_call" | "tool_result" | "final"
    text: str | None = None
    data: dict[str, Any] | None = None
    final: bool = False


class A2AResult(BaseModel):
    """Result of a one-shot `tasks/send` call."""

    text: str
    correlation_id: str
    metadata: dict[str, Any] = Field(default_factory=dict)
```

- [ ] **Step 4: Extend `transport/__init__.py` with new exports**

Update `packages/python/vystak/src/vystak/transport/__init__.py`:

```python
"""Transport abstraction for east-west A2A traffic."""

from vystak.transport.naming import (
    canonical_agent_name,
    parse_canonical_name,
    slug,
)
from vystak.transport.types import (
    A2AEvent,
    A2AMessage,
    A2AResult,
    AgentRef,
)

__all__ = [
    "A2AEvent",
    "A2AMessage",
    "A2AResult",
    "AgentRef",
    "canonical_agent_name",
    "parse_canonical_name",
    "slug",
]
```

- [ ] **Step 5: Run tests + full suite**

```bash
uv run pytest packages/python/vystak/tests/transport/ -v
just lint-python && just test-python
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add packages/python/vystak/src/vystak/transport/types.py \
        packages/python/vystak/src/vystak/transport/__init__.py \
        packages/python/vystak/tests/transport/test_types.py
git commit -m "feat(transport): A2A envelope types — AgentRef, A2AMessage, A2AEvent, A2AResult

Pydantic models used by the Transport ABC and A2AHandler to carry A2A
traffic across transports. AgentRef validates canonical-name format."
```

---

### Task 5: `Transport` ABC

**Files:**
- Create: `packages/python/vystak/src/vystak/transport/base.py`
- Modify: `packages/python/vystak/src/vystak/transport/__init__.py`
- Create: `packages/python/vystak/tests/transport/test_base.py`

- [ ] **Step 1: Write failing tests**

Create `packages/python/vystak/tests/transport/test_base.py`:

```python
"""Tests for the Transport ABC contract."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable

import pytest

from vystak.transport import (
    A2AEvent,
    A2AMessage,
    A2AResult,
    AgentRef,
    Transport,
)
from vystak.transport.base import A2AHandlerProtocol


class FakeTransport(Transport):
    """Minimal concrete Transport for testing ABC behaviour."""

    type = "fake"
    supports_streaming = False

    def __init__(self) -> None:
        self.sent: list[tuple[AgentRef, A2AMessage]] = []
        self.served: list[str] = []

    def resolve_address(self, canonical_name: str) -> str:
        return f"fake://{canonical_name}"

    async def send_task(
        self,
        agent: AgentRef,
        message: A2AMessage,
        metadata: dict,
        *,
        timeout: float,
    ) -> A2AResult:
        self.sent.append((agent, message))
        return A2AResult(text="ack", correlation_id=message.correlation_id)

    async def serve(
        self, canonical_name: str, handler: A2AHandlerProtocol
    ) -> None:
        self.served.append(canonical_name)


class TestTransport:
    def test_cannot_instantiate_abstract(self):
        with pytest.raises(TypeError):
            Transport()

    def test_concrete_subclass(self):
        t = FakeTransport()
        assert t.type == "fake"
        assert t.supports_streaming is False

    @pytest.mark.asyncio
    async def test_send_task(self):
        t = FakeTransport()
        ref = AgentRef(canonical_name="x.agents.default")
        msg = A2AMessage.from_text("hi", correlation_id="c-1")
        result = await t.send_task(ref, msg, {}, timeout=5)
        assert result.text == "ack"
        assert result.correlation_id == "c-1"

    @pytest.mark.asyncio
    async def test_default_stream_task_degrades(self):
        """A non-streaming transport's stream_task() yields one terminal event."""
        t = FakeTransport()
        ref = AgentRef(canonical_name="x.agents.default")
        msg = A2AMessage.from_text("hi")
        events: list[A2AEvent] = []
        async for ev in t.stream_task(ref, msg, {}, timeout=5):
            events.append(ev)
        assert len(events) == 1
        assert events[0].final is True
        assert events[0].type == "final"
        assert events[0].text == "ack"

    def test_resolve_address(self):
        t = FakeTransport()
        assert t.resolve_address("x.agents.prod") == "fake://x.agents.prod"
```

- [ ] **Step 2: Run tests to see them fail**

```bash
uv run pytest packages/python/vystak/tests/transport/test_base.py -v
```

Expected: ImportError for `Transport` from `vystak.transport`.

- [ ] **Step 3: Create `base.py`**

Create `packages/python/vystak/src/vystak/transport/base.py`:

```python
"""Transport abstract base class.

A Transport carries A2A traffic between agents and channels. Every Platform
selects exactly one Transport; all east-west A2A calls flow over it.

Implementations must provide:

- `resolve_address(canonical_name)` — turn a canonical name into the wire
  address format native to this transport.
- `send_task()` — one-shot request/reply.
- `serve()` — listener side; join the load-balanced group for the agent
  and dispatch incoming messages to the provided handler.

Streaming is optional (see `supports_streaming`). The default `stream_task()`
implementation degrades to `send_task()` and emits a single terminal event.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable

from vystak.transport.types import (
    A2AEvent,
    A2AMessage,
    A2AResult,
    AgentRef,
)


@runtime_checkable
class A2AHandlerProtocol(Protocol):
    """Structural type for A2AHandler — avoids a circular import."""

    async def dispatch(
        self,
        message: A2AMessage,
        metadata: dict,
    ) -> A2AResult: ...

    async def dispatch_stream(
        self,
        message: A2AMessage,
        metadata: dict,
    ) -> AsyncIterator[A2AEvent]: ...


class Transport(ABC):
    """Base class for all transports."""

    type: str = ""
    supports_streaming: bool = False

    @abstractmethod
    def resolve_address(self, canonical_name: str) -> str:
        """Derive the wire address for an agent on this transport."""

    @abstractmethod
    async def send_task(
        self,
        agent: AgentRef,
        message: A2AMessage,
        metadata: dict,
        *,
        timeout: float,
    ) -> A2AResult:
        """One-shot request/reply."""

    async def stream_task(
        self,
        agent: AgentRef,
        message: A2AMessage,
        metadata: dict,
        *,
        timeout: float,
    ) -> AsyncIterator[A2AEvent]:
        """Stream events back. Default: call send_task and emit one final event.

        Concrete transports that support native streaming must override this.
        """
        result = await self.send_task(agent, message, metadata, timeout=timeout)
        yield A2AEvent(type="final", text=result.text, final=True)

    @abstractmethod
    async def serve(
        self, canonical_name: str, handler: A2AHandlerProtocol
    ) -> None:
        """Join the load-balanced group for this agent and feed incoming
        messages into `handler`.

        `canonical_name` is the full `{name}.agents.{ns}` identifier; the
        transport derives its own subject / queue / URL routing from it.

        For the HTTP transport this is typically a no-op (FastAPI's /a2a
        route is already running).
        """
```

- [ ] **Step 4: Add to `transport/__init__.py` exports**

Edit `packages/python/vystak/src/vystak/transport/__init__.py` — add `Transport` to the imports and `__all__`:

```python
from vystak.transport.base import Transport

__all__ = [
    "A2AEvent",
    "A2AMessage",
    "A2AResult",
    "AgentRef",
    "Transport",
    "canonical_agent_name",
    "parse_canonical_name",
    "slug",
]
```

- [ ] **Step 5: Ensure pytest-asyncio is available**

Check `packages/python/vystak/pyproject.toml` has `pytest-asyncio` in dev deps; if not, add it:

```toml
[dependency-groups]
dev = [
  # ... existing entries ...
  "pytest-asyncio>=0.23",
]
```

And in the `[tool.pytest.ini_options]` section (create it if missing):

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
```

- [ ] **Step 6: Run tests**

```bash
uv sync
uv run pytest packages/python/vystak/tests/transport/test_base.py -v
just lint-python && just test-python
```

Expected: all tests PASS.

- [ ] **Step 7: Commit**

```bash
git add packages/python/vystak/src/vystak/transport/base.py \
        packages/python/vystak/src/vystak/transport/__init__.py \
        packages/python/vystak/pyproject.toml \
        packages/python/vystak/tests/transport/test_base.py
git commit -m "feat(transport): Transport ABC with default streaming degradation

Defines the transport contract: resolve_address, send_task, serve, and a
default stream_task that degrades to one-shot when a transport declares
supports_streaming=False. A2AHandlerProtocol pins the handler shape
without a circular import."
```

---

### Task 6: `A2AHandler` — transport-agnostic dispatcher

**Files:**
- Create: `packages/python/vystak/src/vystak/transport/handler.py`
- Modify: `packages/python/vystak/src/vystak/transport/__init__.py`
- Create: `packages/python/vystak/tests/transport/test_handler.py`

**Context:** The existing `vystak-adapter-langchain/a2a.py` emits FastAPI handlers that call into LangGraph directly. In this task we introduce a transport-agnostic `A2AHandler` that owns *just the dispatch loop* — inputs and outputs are A2A envelope types, no FastAPI Request/Response. The LangChain adapter's code-generated server will later instantiate `A2AHandler` with its agent callable and wire it into both the FastAPI `/a2a` route and any transport listener.

- [ ] **Step 1: Write failing tests**

Create `packages/python/vystak/tests/transport/test_handler.py`:

```python
"""Tests for A2AHandler dispatch semantics."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from vystak.transport import (
    A2AEvent,
    A2AHandler,
    A2AMessage,
    A2AResult,
)


async def _echo_handler(msg: A2AMessage, metadata: dict) -> str:
    text = msg.parts[0]["text"] if msg.parts else ""
    return f"echo:{text}"


async def _streaming_echo(
    msg: A2AMessage, metadata: dict
) -> AsyncIterator[A2AEvent]:
    text = msg.parts[0]["text"] if msg.parts else ""
    for ch in text:
        yield A2AEvent(type="token", text=ch)
    yield A2AEvent(type="final", text=f"done:{text}", final=True)


class TestA2AHandler:
    @pytest.mark.asyncio
    async def test_dispatch_one_shot(self):
        h = A2AHandler(
            one_shot=_echo_handler,
            streaming=_streaming_echo,
        )
        msg = A2AMessage.from_text("hi", correlation_id="c-1")
        result = await h.dispatch(msg, {})
        assert isinstance(result, A2AResult)
        assert result.text == "echo:hi"
        assert result.correlation_id == "c-1"

    @pytest.mark.asyncio
    async def test_dispatch_stream(self):
        h = A2AHandler(
            one_shot=_echo_handler,
            streaming=_streaming_echo,
        )
        msg = A2AMessage.from_text("ab")
        events: list[A2AEvent] = []
        async for ev in h.dispatch_stream(msg, {}):
            events.append(ev)
        assert [e.text for e in events[:2]] == ["a", "b"]
        assert events[-1].final is True
        assert events[-1].text == "done:ab"

    @pytest.mark.asyncio
    async def test_dispatch_surfaces_errors(self):
        async def bad(msg, metadata):
            raise RuntimeError("boom")

        h = A2AHandler(one_shot=bad, streaming=_streaming_echo)
        msg = A2AMessage.from_text("hi")
        with pytest.raises(RuntimeError, match="boom"):
            await h.dispatch(msg, {})
```

- [ ] **Step 2: Run tests — they should fail with ImportError**

```bash
uv run pytest packages/python/vystak/tests/transport/test_handler.py -v
```

Expected: ImportError for `A2AHandler`.

- [ ] **Step 3: Create `handler.py`**

Create `packages/python/vystak/src/vystak/transport/handler.py`:

```python
"""Transport-agnostic A2A request dispatcher.

A2AHandler is the *callee-side* counterpart of Transport. It wraps the
agent's underlying callable (LangGraph agent, static function, whatever)
behind a uniform async interface that accepts A2A envelope types.

FastAPI routes, NATS listeners, and Service Bus receivers all hand raw
incoming messages to A2AHandler.dispatch() or dispatch_stream() and forward
the result back over their medium.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from vystak.transport.types import (
    A2AEvent,
    A2AMessage,
    A2AResult,
)

OneShotCallable = Callable[[A2AMessage, dict[str, Any]], Awaitable[str]]
StreamingCallable = Callable[
    [A2AMessage, dict[str, Any]], AsyncIterator[A2AEvent]
]


class A2AHandler:
    """Dispatches A2A messages to an underlying agent callable."""

    def __init__(
        self,
        *,
        one_shot: OneShotCallable,
        streaming: StreamingCallable,
    ) -> None:
        self._one_shot = one_shot
        self._streaming = streaming

    async def dispatch(
        self, message: A2AMessage, metadata: dict[str, Any]
    ) -> A2AResult:
        """Run the one-shot path and wrap the returned text as `A2AResult`.

        The agent callable's exceptions propagate. The transport caller is
        responsible for turning them into wire-level error responses.
        """
        text = await self._one_shot(message, metadata)
        return A2AResult(
            text=text,
            correlation_id=message.correlation_id,
            metadata={},
        )

    async def dispatch_stream(
        self, message: A2AMessage, metadata: dict[str, Any]
    ) -> AsyncIterator[A2AEvent]:
        """Yield streaming events from the agent callable.

        Events flow through unchanged. Callers receiving a transport without
        native streaming should use `Transport.stream_task()` which degrades
        automatically.
        """
        async for event in self._streaming(message, metadata):
            yield event
```

- [ ] **Step 4: Export `A2AHandler` from `transport/__init__.py`**

```python
from vystak.transport.handler import A2AHandler

__all__ = [
    "A2AEvent",
    "A2AHandler",
    "A2AMessage",
    "A2AResult",
    "AgentRef",
    "Transport",
    "canonical_agent_name",
    "parse_canonical_name",
    "slug",
]
```

- [ ] **Step 5: Run tests + full suite**

```bash
uv run pytest packages/python/vystak/tests/transport/test_handler.py -v
just lint-python && just test-python
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add packages/python/vystak/src/vystak/transport/handler.py \
        packages/python/vystak/src/vystak/transport/__init__.py \
        packages/python/vystak/tests/transport/test_handler.py
git commit -m "feat(transport): A2AHandler — transport-agnostic dispatcher

Owns the dispatch loop separate from FastAPI/NATS/SB. Concrete transports
invoke dispatch() / dispatch_stream() after extracting the A2A envelope
from their native message format; they handle serialisation and error
wrapping on their own side."
```

---

### Task 7: `TransportContractTests` — shared contract test suite

**Files:**
- Create: `packages/python/vystak/src/vystak/transport/contract.py`
- Modify: `packages/python/vystak/src/vystak/transport/__init__.py`

**Context:** Every concrete `Transport` implementation must pass a common set of tests for the behaviours the ABC requires — single-reply-per-call, streaming degradation, timeouts. We provide a shared pytest-compatible class that implementations subclass and configure with a factory.

- [ ] **Step 1: Create the contract test module**

Create `packages/python/vystak/src/vystak/transport/contract.py`:

```python
"""Shared pytest contract tests for concrete Transport implementations.

Usage: in a concrete transport's test file,

    from vystak.transport.contract import TransportContract

    class TestHttpTransport(TransportContract):
        @pytest.fixture
        def serve_agent(self):
            # Return an async context manager factory: serve_agent(name, handler)
            # must set up the listener side and `yield` a client `Transport`
            # pre-configured to reach `name`.
            @asynccontextmanager
            async def _ctx(canonical_name, handler):
                ...  # spin up whatever the transport needs
                yield HttpTransport(routes={canonical_name: f"http://.../a2a"})
            return _ctx

`serve_agent(canonical_name, handler)` is an async context manager that
binds `handler` to the canonical name on the listener side and yields a
ready-to-use client `Transport` instance. On exit it tears down the
listener.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import pytest

from vystak.transport import (
    A2AEvent,
    A2AHandler,
    A2AMessage,
    AgentRef,
)


class TransportContract:
    """Pytest mixin. Subclass and provide a `serve_agent` fixture."""

    @pytest.fixture
    def serve_agent(self):
        raise NotImplementedError(
            "Concrete test class must provide a `serve_agent` fixture — an "
            "async context manager factory (canonical_name, handler) -> "
            "client Transport."
        )

    @pytest.mark.asyncio
    async def test_single_reply_per_call(self, serve_agent):
        async def one_shot(msg, metadata):
            text = msg.parts[0]["text"] if msg.parts else ""
            return f"reply:{text}"

        async def streaming(msg, metadata):
            yield A2AEvent(type="final", text="n/a", final=True)

        handler = A2AHandler(one_shot=one_shot, streaming=streaming)
        async with serve_agent("echo.agents.default", handler) as client:
            ref = AgentRef(canonical_name="echo.agents.default")
            msg = A2AMessage.from_text("hi")
            result = await client.send_task(ref, msg, {}, timeout=5)
            assert result.text == "reply:hi"
            assert result.correlation_id == msg.correlation_id

    @pytest.mark.asyncio
    async def test_concurrent_calls_do_not_cross(self, serve_agent):
        async def one_shot(msg, metadata):
            await asyncio.sleep(0.05)
            return msg.parts[0]["text"]

        async def streaming(msg, metadata):
            yield A2AEvent(type="final", text=msg.parts[0]["text"], final=True)

        handler = A2AHandler(one_shot=one_shot, streaming=streaming)
        async with serve_agent("echo.agents.default", handler) as client:
            ref = AgentRef(canonical_name="echo.agents.default")

            async def call(text):
                msg = A2AMessage.from_text(text)
                result = await client.send_task(ref, msg, {}, timeout=5)
                return result.correlation_id, result.text

            pairs = await asyncio.gather(*[call(f"m-{i}") for i in range(10)])
            for _cid, text in pairs:
                assert text.startswith("m-"), pairs
            assert len({cid for cid, _ in pairs}) == 10

    @pytest.mark.asyncio
    async def test_timeout_raises(self, serve_agent):
        async def one_shot(msg, metadata):
            await asyncio.sleep(2)
            return "late"

        async def streaming(msg, metadata):
            yield A2AEvent(type="final", text="late", final=True)

        handler = A2AHandler(one_shot=one_shot, streaming=streaming)
        async with serve_agent("slow.agents.default", handler) as client:
            ref = AgentRef(canonical_name="slow.agents.default")
            msg = A2AMessage.from_text("hi")
            with pytest.raises((asyncio.TimeoutError, TimeoutError)):
                await client.send_task(ref, msg, {}, timeout=0.2)

    @pytest.mark.asyncio
    async def test_streaming_or_degradation(self, serve_agent):
        async def one_shot(msg, metadata):
            return "full-reply"

        async def streaming(msg, metadata):
            for ch in "abc":
                yield A2AEvent(type="token", text=ch)
            yield A2AEvent(type="final", text="abc", final=True)

        handler = A2AHandler(one_shot=one_shot, streaming=streaming)
        async with serve_agent("s.agents.default", handler) as client:
            ref = AgentRef(canonical_name="s.agents.default")
            events = []
            async for ev in client.stream_task(
                ref, A2AMessage.from_text("hi"), {}, timeout=5
            ):
                events.append(ev)
            if client.supports_streaming:
                assert any(ev.type == "token" for ev in events)
            else:
                assert len(events) == 1
                assert events[0].final is True
            assert events[-1].final is True
```

- [ ] **Step 2: Export `TransportContract`**

Update `packages/python/vystak/src/vystak/transport/__init__.py`:

```python
from vystak.transport.contract import TransportContract

__all__ = [
    # ... existing ...
    "TransportContract",
]
```

Keep list alphabetically sorted.

- [ ] **Step 3: Verify imports**

```bash
uv run python -c "from vystak.transport import TransportContract; print(TransportContract)"
```

Expected: `<class 'vystak.transport.contract.TransportContract'>`

- [ ] **Step 4: Run lint + tests**

```bash
just lint-python && just test-python
```

Expected: PASS. (No tests for the contract module itself — it's tested via concrete impls.)

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak/src/vystak/transport/contract.py \
        packages/python/vystak/src/vystak/transport/__init__.py
git commit -m "feat(transport): shared TransportContract test mixin

Concrete Transport implementations subclass and provide transport_factory
and serve_agent fixtures. Covers single-reply-per-call, concurrent-call
correlation, timeouts, and streaming degradation."
```

---

### Task 8: `vystak-transport-http` package scaffold

**Files:**
- Create: `packages/python/vystak-transport-http/pyproject.toml`
- Create: `packages/python/vystak-transport-http/src/vystak_transport_http/__init__.py`
- Create: `packages/python/vystak-transport-http/README.md`
- Modify: `pyproject.toml` (root)

- [ ] **Step 1: Create the package manifest**

Create `packages/python/vystak-transport-http/pyproject.toml` (copy conventions from `packages/python/vystak-channel-chat/pyproject.toml`):

```toml
[project]
name = "vystak-transport-http"
version = "0.1.0"
description = "HTTP transport for Vystak east-west A2A traffic"
readme = "README.md"
requires-python = ">=3.11"
dependencies = [
    "vystak",
    "httpx>=0.27",
    "fastapi>=0.115",
    "sse-starlette>=2.0",
    "pydantic>=2.0",
]

[dependency-groups]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/vystak_transport_http"]

[tool.uv.sources]
vystak = { workspace = true }

[tool.pytest.ini_options]
asyncio_mode = "auto"
```

- [ ] **Step 2: Create package module**

Create `packages/python/vystak-transport-http/src/vystak_transport_http/__init__.py`:

```python
"""HTTP transport implementation for Vystak."""

__all__: list[str] = []  # populated in later tasks
```

Create `packages/python/vystak-transport-http/README.md`:

```markdown
# vystak-transport-http

HTTP implementation of the Vystak `Transport` ABC.

- `HttpTransport` — concrete Transport using httpx (client) and FastAPI (server's /a2a is already handled; serve() is a no-op).
- `HttpTransportPlugin` — `TransportPlugin` providing env-var contract and (empty) provisioning.
```

- [ ] **Step 3: Register in root workspace**

Open `pyproject.toml` at the repo root. In `[tool.uv.workspace]` members (or wherever the other `vystak-*` packages are listed), add:

```toml
"packages/python/vystak-transport-http",
```

Check: does the workspace use a `members = [...]` list or a glob? If glob (`"packages/python/*"`), the package is auto-included — skip the edit.

- [ ] **Step 4: Sync and verify**

```bash
uv sync
uv run python -c "import vystak_transport_http; print(vystak_transport_http)"
```

Expected: `<module 'vystak_transport_http' from '...'>`

- [ ] **Step 5: Run lint + tests**

```bash
just lint-python && just test-python
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add packages/python/vystak-transport-http/ pyproject.toml
git commit -m "feat(transport-http): scaffold vystak-transport-http package

Empty HTTP transport package registered in the uv workspace. Implementation
lands in follow-ups."
```

---

### Task 9: `HttpTransport` concrete

**Files:**
- Create: `packages/python/vystak-transport-http/src/vystak_transport_http/transport.py`
- Modify: `packages/python/vystak-transport-http/src/vystak_transport_http/__init__.py`
- Create: `packages/python/vystak-transport-http/tests/__init__.py`
- Create: `packages/python/vystak-transport-http/tests/test_http_transport.py`

**Context:** `HttpTransport` is the simplest implementation — no broker to manage. It wraps `httpx` for the client side; its `serve()` is a no-op because the generated agent already exposes `/a2a` via FastAPI. Its `resolve_address()` takes a canonical name and returns a URL derived from `VYSTAK_ROUTES_JSON` (the peer address map injected at deploy time).

- [ ] **Step 1: Write failing tests**

Create `packages/python/vystak-transport-http/tests/__init__.py` (empty).

Create `packages/python/vystak-transport-http/tests/test_http_transport.py`:

```python
"""Tests for HttpTransport."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
import uvicorn
from fastapi import FastAPI, Request
from sse_starlette.sse import EventSourceResponse

from vystak.transport import (
    A2AEvent,
    A2AHandler,
    A2AMessage,
    AgentRef,
)
from vystak.transport.contract import TransportContract
from vystak_transport_http import HttpTransport


def _build_app(handler: A2AHandler) -> FastAPI:
    """Minimal FastAPI app exposing /a2a for the test agent."""
    app = FastAPI()

    @app.post("/a2a")
    async def a2a_endpoint(request: Request):
        body = await request.json()
        params = body.get("params", {})
        metadata = params.get("metadata", {})
        msg_params = params.get("message", {})
        message = A2AMessage(
            role=msg_params.get("role", "user"),
            parts=msg_params.get("parts", []),
            correlation_id=params.get("id") or metadata.get("correlation_id", ""),
            metadata=metadata,
        )

        if body.get("method") == "tasks/sendSubscribe":
            async def gen():
                async for ev in handler.dispatch_stream(message, metadata):
                    yield {"data": ev.model_dump_json()}

            return EventSourceResponse(gen())

        result = await handler.dispatch(message, metadata)
        return {
            "jsonrpc": "2.0",
            "id": body.get("id"),
            "result": {
                "status": {
                    "message": {
                        "parts": [{"text": result.text}]
                    }
                },
                "correlation_id": result.correlation_id,
            },
        }

    return app


@asynccontextmanager
async def _serve(app: FastAPI, port: int):
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    # Wait for the server to bind.
    for _ in range(100):
        if server.started:
            break
        await asyncio.sleep(0.01)
    try:
        yield
    finally:
        server.should_exit = True
        await task


class TestHttpTransport(TransportContract):
    """Runs the shared transport contract against HttpTransport."""

    @pytest.fixture
    def serve_agent(self, unused_tcp_port):
        @asynccontextmanager
        async def _ctx(canonical_name: str, handler: A2AHandler):
            app = _build_app(handler)
            async with _serve(app, unused_tcp_port):
                client = HttpTransport(
                    routes={
                        canonical_name: f"http://127.0.0.1:{unused_tcp_port}/a2a"
                    }
                )
                yield client
        return _ctx


class TestHttpTransportBasics:
    def test_type(self):
        t = HttpTransport(routes={})
        assert t.type == "http"
        assert t.supports_streaming is True

    def test_resolve_address_lookup(self):
        t = HttpTransport(routes={"x.agents.default": "http://example:8000/a2a"})
        assert t.resolve_address("x.agents.default") == "http://example:8000/a2a"

    def test_resolve_address_unknown(self):
        t = HttpTransport(routes={})
        with pytest.raises(KeyError):
            t.resolve_address("unknown.agents.default")

    @pytest.mark.asyncio
    async def test_serve_is_noop(self):
        t = HttpTransport(routes={})
        # serve() returns immediately; the actual /a2a route is served by
        # the generated agent's FastAPI app.
        await t.serve("x.agents.default", handler=None)
```

- [ ] **Step 2: Run tests to see them fail**

```bash
uv run pytest packages/python/vystak-transport-http/tests/ -v
```

Expected: ImportError for `HttpTransport`.

- [ ] **Step 3: Implement `HttpTransport`**

Create `packages/python/vystak-transport-http/src/vystak_transport_http/transport.py`:

```python
"""HttpTransport — uses httpx (client) and relies on generated FastAPI /a2a (server)."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx

from vystak.transport import (
    A2AEvent,
    A2AMessage,
    A2AResult,
    AgentRef,
    Transport,
)
from vystak.transport.base import A2AHandlerProtocol


class HttpTransport(Transport):
    """HTTP implementation of the Transport ABC.

    Client side: httpx POST to `{agent_url}/a2a` with JSON-RPC A2A envelope.
    Server side: the generated agent already exposes `/a2a` via FastAPI;
    `serve()` is a no-op.

    Routes are supplied at construction time (typically built from
    `VYSTAK_ROUTES_JSON` + the platform's canonical-to-URL mapping).
    """

    type = "http"
    supports_streaming = True

    def __init__(self, routes: dict[str, str]) -> None:
        """`routes` maps canonical_name -> absolute URL ending in `/a2a`."""
        self._routes = dict(routes)

    def resolve_address(self, canonical_name: str) -> str:
        try:
            return self._routes[canonical_name]
        except KeyError:
            raise KeyError(
                f"HttpTransport has no route for canonical name "
                f"{canonical_name!r}; known: {sorted(self._routes)}"
            ) from None

    async def send_task(
        self,
        agent: AgentRef,
        message: A2AMessage,
        metadata: dict[str, Any],
        *,
        timeout: float,
    ) -> A2AResult:
        url = self.resolve_address(agent.canonical_name)
        payload = self._build_payload("tasks/send", message, metadata)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            body = response.json()
        return self._parse_result(body, message.correlation_id)

    async def stream_task(
        self,
        agent: AgentRef,
        message: A2AMessage,
        metadata: dict[str, Any],
        *,
        timeout: float,
    ) -> AsyncIterator[A2AEvent]:
        url = self.resolve_address(agent.canonical_name)
        payload = self._build_payload("tasks/sendSubscribe", message, metadata)
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream("POST", url, json=payload) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    data = line.removeprefix("data:").strip()
                    if not data:
                        continue
                    try:
                        parsed = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    # A2AEvent model_validate tolerates missing optional fields.
                    yield A2AEvent.model_validate(parsed)

    async def serve(
        self, canonical_name: str, handler: A2AHandlerProtocol
    ) -> None:
        # FastAPI's /a2a route already handles inbound HTTP; nothing to do.
        return None

    def _build_payload(
        self, method: str, message: A2AMessage, metadata: dict[str, Any]
    ) -> dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": method,
            "params": {
                "id": message.correlation_id,
                "message": {
                    "role": message.role,
                    "parts": message.parts,
                },
                "metadata": {**message.metadata, **metadata},
            },
        }

    def _parse_result(
        self, body: dict[str, Any], fallback_correlation: str
    ) -> A2AResult:
        result = body.get("result", {}) or {}
        parts = (
            result.get("status", {})
            .get("message", {})
            .get("parts", [])
        )
        text = ""
        for part in parts:
            if isinstance(part, dict) and "text" in part:
                text += part["text"]
        return A2AResult(
            text=text,
            correlation_id=result.get("correlation_id") or fallback_correlation,
            metadata={},
        )
```

- [ ] **Step 4: Export from the package**

Update `packages/python/vystak-transport-http/src/vystak_transport_http/__init__.py`:

```python
"""HTTP transport implementation for Vystak."""

from vystak_transport_http.transport import HttpTransport

__all__ = ["HttpTransport"]
```

- [ ] **Step 5: Add `pytest-asyncio` and `uvicorn` to test deps if missing**

Inspect `packages/python/vystak-transport-http/pyproject.toml`. Ensure `[dependency-groups].dev` contains `pytest>=8.0`, `pytest-asyncio>=0.23`, and `uvicorn>=0.34` (only if not already present). Also ensure `httpx>=0.27` is in `dependencies` (already added in Task 8).

- [ ] **Step 6: Sync and run tests**

```bash
uv sync
uv run pytest packages/python/vystak-transport-http/tests/ -v
```

Expected: all contract tests + basics tests PASS. If `unused_tcp_port` fixture is missing, add `pytest-asyncio>=0.23` — it's provided by `pytest` itself actually; if pytest doesn't have it, add `pytest-httpserver` or define a local `unused_tcp_port` fixture that uses `socket.socket()`.

If `unused_tcp_port` is not available, add this to `packages/python/vystak-transport-http/tests/conftest.py`:

```python
import socket

import pytest


@pytest.fixture
def unused_tcp_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
```

- [ ] **Step 7: Run lint + full test**

```bash
just lint-python && just test-python
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add packages/python/vystak-transport-http/
git commit -m "feat(transport-http): HttpTransport concrete implementation

httpx-based client; serve() is a no-op because generated agents already
expose /a2a via FastAPI. Passes the shared TransportContract test suite:
single-reply-per-call, concurrent correlation, timeouts, and streaming."
```

---

### Task 10: `TransportPlugin` ABC

**Files:**
- Modify: `packages/python/vystak/src/vystak/providers/base.py`
- Create: `packages/python/vystak/tests/providers/test_transport_plugin.py` (if `tests/providers/` doesn't exist, create `__init__.py` too)

- [ ] **Step 1: Write failing tests**

Create `packages/python/vystak/tests/providers/__init__.py` if missing (empty file).

Create `packages/python/vystak/tests/providers/test_transport_plugin.py`:

```python
"""Tests for TransportPlugin ABC."""

from __future__ import annotations

import pytest

from vystak.providers.base import GeneratedCode, TransportPlugin
from vystak.schema import Platform, Transport


class FakeTransportPlugin(TransportPlugin):
    type = "fake"

    def build_provision_nodes(self, transport, platform):
        return []

    def generate_env_contract(self, transport, context):
        return {"VYSTAK_TRANSPORT_TYPE": "fake"}

    def generate_listener_code(self, transport):
        return None


def test_cannot_instantiate_abstract():
    with pytest.raises(TypeError):
        TransportPlugin()


def test_concrete_plugin():
    p = FakeTransportPlugin()
    assert p.type == "fake"
    t = Transport(name="x", type="http")
    pl = Platform(name="p", provider="docker", transport="x")
    assert p.build_provision_nodes(t, pl) == []
    assert p.generate_env_contract(t, {}) == {"VYSTAK_TRANSPORT_TYPE": "fake"}
    assert p.generate_listener_code(t) is None
```

- [ ] **Step 2: Run tests to see ImportError**

```bash
uv run pytest packages/python/vystak/tests/providers/test_transport_plugin.py -v
```

Expected: ImportError.

- [ ] **Step 3: Add `TransportPlugin` ABC to `providers/base.py`**

Open `packages/python/vystak/src/vystak/providers/base.py`. Near the existing `ChannelPlugin` ABC, add:

```python
from vystak.schema.transport import Transport


class TransportPlugin(ABC):
    """Plugin that wires a specific Transport type into a platform.

    Mirrors ChannelPlugin: handles broker provisioning, env-contract
    generation for agent/channel containers, and the listener-startup code
    snippet injected into the generated agent server.py.
    """

    type: str = ""  # "http" | "nats" | "azure-service-bus"

    @abstractmethod
    def build_provision_nodes(
        self, transport: "Transport", platform: "Platform"
    ) -> list["Provisionable"]:
        """Return the broker infra nodes this transport needs on this
        platform. Returns an empty list for http or for BYO connections."""

    @abstractmethod
    def generate_env_contract(
        self, transport: "Transport", context: dict
    ) -> dict[str, str]:
        """Env vars the provider should inject into every agent/channel
        container so they can construct the matching Transport at runtime.

        Keys follow the `VYSTAK_TRANSPORT_*` convention. `context` carries
        provisioner-specific values (resolved broker URL, secret ARNs, etc.).
        """

    @abstractmethod
    def generate_listener_code(
        self, transport: "Transport"
    ) -> "GeneratedCode | None":
        """Return a Python source snippet to append to the generated agent
        server.py that starts the transport listener. Return None if the
        transport does not need a listener (HTTP — FastAPI already serves)."""
```

Note: the forward-reference strings avoid import cycles. Add imports at the top of the file as needed (e.g., `from vystak.schema import Platform` if not already present).

- [ ] **Step 4: Run tests and lint**

```bash
uv run pytest packages/python/vystak/tests/providers/test_transport_plugin.py -v
just lint-python && just test-python
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak/src/vystak/providers/base.py \
        packages/python/vystak/tests/providers/test_transport_plugin.py \
        packages/python/vystak/tests/providers/__init__.py
git commit -m "feat(providers): TransportPlugin ABC

Mirrors ChannelPlugin. Owns broker provisioning, env-contract generation
for agent/channel containers, and listener-startup codegen."
```

---

### Task 11: `HttpTransportPlugin`

**Files:**
- Create: `packages/python/vystak-transport-http/src/vystak_transport_http/plugin.py`
- Modify: `packages/python/vystak-transport-http/src/vystak_transport_http/__init__.py`
- Create: `packages/python/vystak-transport-http/tests/test_http_plugin.py`

- [ ] **Step 1: Write failing tests**

Create `packages/python/vystak-transport-http/tests/test_http_plugin.py`:

```python
"""Tests for HttpTransportPlugin."""

from __future__ import annotations

from vystak.schema import Platform, Transport
from vystak_transport_http import HttpTransportPlugin


def test_type():
    p = HttpTransportPlugin()
    assert p.type == "http"


def test_no_provision_nodes():
    p = HttpTransportPlugin()
    t = Transport(name="default-http", type="http")
    pl = Platform(name="main", provider="docker", transport="default-http")
    assert p.build_provision_nodes(t, pl) == []


def test_env_contract():
    p = HttpTransportPlugin()
    t = Transport(name="default-http", type="http")
    env = p.generate_env_contract(t, context={})
    assert env["VYSTAK_TRANSPORT_TYPE"] == "http"


def test_no_listener_code():
    p = HttpTransportPlugin()
    t = Transport(name="default-http", type="http")
    assert p.generate_listener_code(t) is None
```

- [ ] **Step 2: Run tests — they should fail**

```bash
uv run pytest packages/python/vystak-transport-http/tests/test_http_plugin.py -v
```

Expected: ImportError.

- [ ] **Step 3: Create `plugin.py`**

Create `packages/python/vystak-transport-http/src/vystak_transport_http/plugin.py`:

```python
"""HttpTransportPlugin — registers the HTTP transport with providers."""

from __future__ import annotations

from vystak.providers.base import GeneratedCode, TransportPlugin
from vystak.schema import Platform, Transport


class HttpTransportPlugin(TransportPlugin):
    """HTTP transport plugin. No broker to provision; listener handled by
    the generated FastAPI app already."""

    type = "http"

    def build_provision_nodes(self, transport: Transport, platform: Platform):
        return []

    def generate_env_contract(
        self, transport: Transport, context: dict
    ) -> dict[str, str]:
        return {"VYSTAK_TRANSPORT_TYPE": "http"}

    def generate_listener_code(self, transport: Transport) -> GeneratedCode | None:
        return None
```

- [ ] **Step 4: Update `__init__.py` exports**

`packages/python/vystak-transport-http/src/vystak_transport_http/__init__.py`:

```python
"""HTTP transport implementation for Vystak."""

from vystak_transport_http.plugin import HttpTransportPlugin
from vystak_transport_http.transport import HttpTransport

__all__ = ["HttpTransport", "HttpTransportPlugin"]
```

- [ ] **Step 5: Run tests and lint**

```bash
uv run pytest packages/python/vystak-transport-http/tests/ -v
just lint-python && just test-python
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add packages/python/vystak-transport-http/src/vystak_transport_http/plugin.py \
        packages/python/vystak-transport-http/src/vystak_transport_http/__init__.py \
        packages/python/vystak-transport-http/tests/test_http_plugin.py
git commit -m "feat(transport-http): HttpTransportPlugin

Registers the HTTP transport with providers: no provisioning needed, emits
VYSTAK_TRANSPORT_TYPE=http into the env contract, no listener code (FastAPI
already serves /a2a)."
```

---

### Task 12: `AgentClient` + `ask_agent` helper

**Files:**
- Create: `packages/python/vystak/src/vystak/transport/client.py`
- Modify: `packages/python/vystak/src/vystak/transport/__init__.py`
- Create: `packages/python/vystak/tests/transport/test_client.py`

- [ ] **Step 1: Write failing tests**

Create `packages/python/vystak/tests/transport/test_client.py`:

```python
"""Tests for AgentClient + ask_agent."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from vystak.transport import (
    A2AEvent,
    A2AMessage,
    A2AResult,
    AgentClient,
    AgentRef,
    Transport,
    ask_agent,
)
from vystak.transport.base import A2AHandlerProtocol


class FakeTransport(Transport):
    type = "fake"
    supports_streaming = True

    def __init__(self) -> None:
        self.sent: list[AgentRef] = []

    def resolve_address(self, canonical_name: str) -> str:
        return f"fake://{canonical_name}"

    async def send_task(
        self, agent, message, metadata, *, timeout
    ) -> A2AResult:
        self.sent.append(agent)
        return A2AResult(text=f"reply:{message.parts[0]['text']}", correlation_id=message.correlation_id)

    async def stream_task(
        self, agent, message, metadata, *, timeout
    ) -> AsyncIterator[A2AEvent]:
        for ch in message.parts[0]["text"]:
            yield A2AEvent(type="token", text=ch)
        yield A2AEvent(type="final", text=f"done:{message.parts[0]['text']}", final=True)

    async def serve(self, canonical_name: str, handler: A2AHandlerProtocol) -> None:
        return None


class TestAgentClient:
    @pytest.mark.asyncio
    async def test_send_task_resolves_short_name(self):
        t = FakeTransport()
        c = AgentClient(
            transport=t,
            routes={"time-agent": "time-agent.agents.default"},
        )
        reply = await c.send_task("time-agent", "hi")
        assert reply == "reply:hi"
        assert t.sent[0].canonical_name == "time-agent.agents.default"

    @pytest.mark.asyncio
    async def test_send_task_unknown_short_name(self):
        t = FakeTransport()
        c = AgentClient(transport=t, routes={})
        with pytest.raises(KeyError, match="unknown"):
            await c.send_task("unknown", "hi")

    @pytest.mark.asyncio
    async def test_stream_task(self):
        t = FakeTransport()
        c = AgentClient(
            transport=t,
            routes={"time-agent": "time-agent.agents.default"},
        )
        events = []
        async for ev in c.stream_task("time-agent", "ab"):
            events.append(ev)
        assert [e.text for e in events[:2]] == ["a", "b"]
        assert events[-1].final is True

    @pytest.mark.asyncio
    async def test_send_task_accepts_a2a_message(self):
        t = FakeTransport()
        c = AgentClient(
            transport=t,
            routes={"x": "x.agents.default"},
        )
        msg = A2AMessage.from_text("hi", correlation_id="fixed-id")
        reply = await c.send_task("x", msg)
        assert reply == "reply:hi"
        assert t.sent[0].canonical_name == "x.agents.default"


class TestAskAgent:
    @pytest.mark.asyncio
    async def test_uses_provided_client(self):
        t = FakeTransport()
        c = AgentClient(transport=t, routes={"x": "x.agents.default"})
        reply = await ask_agent("x", "hi", client=c)
        assert reply == "reply:hi"
```

- [ ] **Step 2: Run tests to see ImportError**

```bash
uv run pytest packages/python/vystak/tests/transport/test_client.py -v
```

Expected: ImportError.

- [ ] **Step 3: Create `client.py`**

Create `packages/python/vystak/src/vystak/transport/client.py`:

```python
"""Caller-side client for agent-to-agent and channel-to-agent traffic.

AgentClient wraps a Transport with a short-name → canonical-name route map.
The helper `ask_agent()` is a one-shot convenience.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from typing import Any

from vystak.transport.base import Transport
from vystak.transport.types import (
    A2AEvent,
    A2AMessage,
    A2AResult,
    AgentRef,
)

DEFAULT_TIMEOUT = 60.0


class AgentClient:
    """Transport-agnostic client for calling peer agents.

    Users call `send_task("short-name", text)` — the client looks up the
    canonical name in its route map and delegates to the transport.
    """

    def __init__(
        self,
        *,
        transport: Transport,
        routes: dict[str, str],
    ) -> None:
        self._transport = transport
        self._routes = dict(routes)

    @property
    def transport(self) -> Transport:
        return self._transport

    async def send_task(
        self,
        agent: str,
        text: str | A2AMessage,
        *,
        metadata: dict[str, Any] | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> str:
        ref = self._resolve(agent)
        message = (
            text
            if isinstance(text, A2AMessage)
            else A2AMessage.from_text(text, metadata=metadata)
        )
        result = await self._transport.send_task(
            ref, message, metadata or {}, timeout=timeout
        )
        return result.text

    async def stream_task(
        self,
        agent: str,
        text: str | A2AMessage,
        *,
        metadata: dict[str, Any] | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> AsyncIterator[A2AEvent]:
        ref = self._resolve(agent)
        message = (
            text
            if isinstance(text, A2AMessage)
            else A2AMessage.from_text(text, metadata=metadata)
        )
        async for event in self._transport.stream_task(
            ref, message, metadata or {}, timeout=timeout
        ):
            yield event

    def _resolve(self, short_name: str) -> AgentRef:
        try:
            canonical = self._routes[short_name]
        except KeyError:
            raise KeyError(
                f"unknown agent {short_name!r}; known: {sorted(self._routes)}"
            ) from None
        return AgentRef(canonical_name=canonical)


# --- one-shot helper ---

_DEFAULT_CLIENT: AgentClient | None = None


def _default_client() -> AgentClient:
    """Build (once) and return the process-level AgentClient from env vars.

    The env contract is populated at deploy time by the provider + transport
    plugin. Stub behaviour here: raise if not configured — `ask_agent`
    callers during tests should pass `client=` explicitly.
    """
    global _DEFAULT_CLIENT
    if _DEFAULT_CLIENT is not None:
        return _DEFAULT_CLIENT
    raise RuntimeError(
        "ask_agent() default client not configured; pass client= explicitly "
        "or install a transport via AgentClient.install_default_from_env()"
    )


async def ask_agent(
    agent: str,
    question: str,
    *,
    metadata: dict[str, Any] | None = None,
    client: AgentClient | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> str:
    """Short helper for one-shot agent calls.

    Example:
        from vystak.transport import ask_agent
        reply = await ask_agent("time-agent", "what time is it?")
    """
    c = client or _default_client()
    return await c.send_task(
        agent, question, metadata=metadata, timeout=timeout
    )
```

Note: `AgentClient.install_default_from_env()` is referenced in the error message but not yet implemented — that's intentional. Plan B (NATS) and the generated agent wiring will add it. For now, user tool code in tests passes `client=` explicitly, and production code gets the client constructed by the provider-generated bootstrap snippet.

- [ ] **Step 4: Export**

Update `packages/python/vystak/src/vystak/transport/__init__.py`:

```python
from vystak.transport.client import AgentClient, ask_agent

__all__ = [
    # ... existing entries plus:
    "AgentClient",
    "ask_agent",
]
```

Keep alphabetical.

- [ ] **Step 5: Run tests + lint**

```bash
uv run pytest packages/python/vystak/tests/transport/ -v
just lint-python && just test-python
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add packages/python/vystak/src/vystak/transport/client.py \
        packages/python/vystak/src/vystak/transport/__init__.py \
        packages/python/vystak/tests/transport/test_client.py
git commit -m "feat(transport): AgentClient + ask_agent helper

Caller-side client with short-name → canonical-name route map. Tools call
ask_agent('time-agent', question) and the active transport handles
routing. install_default_from_env() plumbing lands with the codegen wiring."
```

---

### Task 13: Refactor `a2a.py` — generated `/a2a` route delegates to `A2AHandler`

**Files:**
- Modify: `packages/python/vystak-adapter-langchain/src/vystak_adapter_langchain/a2a.py`
- Modify: `packages/python/vystak-adapter-langchain/src/vystak_adapter_langchain/templates.py`
- Modify: existing adapter tests as needed

**Context:** `a2a.py` today emits inlined Python source for the FastAPI `/a2a` route. We change the emitted code to:

1. Import `A2AHandler` and `A2AMessage` from `vystak.transport`.
2. Construct an `A2AHandler(one_shot=..., streaming=...)` where the two callables wrap the existing LangGraph agent invocation logic.
3. Keep the FastAPI route as a thin SSE / JSON-RPC adapter that calls `handler.dispatch()` or `handler.dispatch_stream()`.

This keeps behaviour identical; just reshapes the emitted source so the dispatch logic is importable and re-usable by future transport listeners.

- [ ] **Step 1: Re-read the current shape of `a2a.py`**

```bash
uv run python -c "from vystak_adapter_langchain.a2a import generate_a2a_handlers; import inspect; print(inspect.getsourcefile(generate_a2a_handlers))"
```

Open the file. Identify the string blocks that emit the `/a2a` route body. They currently build the task-state-machine and yield SSE events inline.

- [ ] **Step 2: Extract the one-shot and streaming adapter functions**

Refactor the emitted Python so it produces roughly this shape (the emitted source, not the generator code):

```python
# Emitted into generated server.py:

from vystak.transport import A2AHandler, A2AMessage, A2AResult, A2AEvent

async def _a2a_one_shot(message, metadata):
    # existing LangGraph agent.ainvoke logic, extracting final text
    ...
    return final_text

async def _a2a_streaming(message, metadata):
    # existing LangGraph streaming logic
    async for chunk in graph.astream(...):
        ...
        yield A2AEvent(type="token", text=token)
    yield A2AEvent(type="final", text=final_text, final=True)

_a2a_handler = A2AHandler(one_shot=_a2a_one_shot, streaming=_a2a_streaming)

@app.post("/a2a")
async def a2a_endpoint(request):
    body = await request.json()
    method = body.get("method")
    params = body.get("params", {})
    message = A2AMessage.model_validate({
        "role": params.get("message", {}).get("role", "user"),
        "parts": params.get("message", {}).get("parts", []),
        "correlation_id": params.get("id", ""),
        "metadata": params.get("metadata", {}),
    })
    metadata = params.get("metadata", {})

    if method == "tasks/sendSubscribe":
        async def gen():
            async for ev in _a2a_handler.dispatch_stream(message, metadata):
                yield {"data": ev.model_dump_json()}
        return EventSourceResponse(gen())

    if method == "tasks/send":
        result = await _a2a_handler.dispatch(message, metadata)
        return {
            "jsonrpc": "2.0",
            "id": body.get("id"),
            "result": {
                "status": {"message": {"parts": [{"text": result.text}]}},
                "correlation_id": result.correlation_id,
            },
        }
    ...
```

In `a2a.py`, rewrite the relevant emission functions to produce the above shape. Keep `tasks/get` and `tasks/cancel` handling as before — those are unchanged.

- [ ] **Step 3: Ensure generated `requirements.txt` includes `vystak`**

Open `packages/python/vystak-adapter-langchain/src/vystak_adapter_langchain/templates.py`, find `generate_requirements_txt`, and add `vystak` to the emitted list:

Change this block:

```python
    return dedent(f"""\
        langchain-core>=0.3
        langgraph>=0.2
        {provider_pkg}
        fastapi>=0.115
        uvicorn>=0.34
        sse-starlette>=2.0{checkpoint_pkg}{mcp_pkg}{tool_deps}
    """)
```

To:

```python
    return dedent(f"""\
        vystak>=0.1
        langchain-core>=0.3
        langgraph>=0.2
        {provider_pkg}
        fastapi>=0.115
        uvicorn>=0.34
        sse-starlette>=2.0{checkpoint_pkg}{mcp_pkg}{tool_deps}
    """)
```

- [ ] **Step 4: Update existing adapter tests if they snapshot the emitted source**

Find tests that match `generate_a2a_handlers` or similar names in `packages/python/vystak-adapter-langchain/tests/`:

```bash
grep -rn "generate_a2a" packages/python/vystak-adapter-langchain/tests/
```

If tests assert against emitted source strings, update expectations to the new shape. If tests only run the generated server end-to-end, they may already pass as-is.

- [ ] **Step 5: Run the adapter tests**

```bash
uv run pytest packages/python/vystak-adapter-langchain/tests/ -v
```

Expected: PASS. Iterate on the emitted source until all pass.

- [ ] **Step 6: Run full suite**

```bash
just lint-python && just test-python
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add packages/python/vystak-adapter-langchain/src/vystak_adapter_langchain/a2a.py \
        packages/python/vystak-adapter-langchain/src/vystak_adapter_langchain/templates.py \
        packages/python/vystak-adapter-langchain/tests/
git commit -m "refactor(langchain-adapter): FastAPI /a2a delegates to A2AHandler

Emits source that constructs vystak.transport.A2AHandler(one_shot, streaming)
and dispatches through it from the FastAPI route. No behavioural change —
same JSON-RPC envelope, same SSE events. Sets up for non-HTTP transports
to re-use the handler via their listener implementations.

Adds vystak>=0.1 to the generated requirements.txt."
```

---

### Task 14: Emit transport listener startup in generated server

**Files:**
- Modify: `packages/python/vystak-adapter-langchain/src/vystak_adapter_langchain/templates.py`
- Modify: adapter tests

**Context:** The generated `server.py` must construct a `Transport` from env at startup. For HTTP this is a no-op; for NATS (Plan B) it starts a subscriber. The template emits the bootstrap block unconditionally; the transport's `serve()` decides whether there's anything to do.

- [ ] **Step 1: Locate the FastAPI app construction block in templates.py**

Find the place in `generate_server_py` where the FastAPI app is built and lifespan is declared. Look for the `app = FastAPI(...)` emission.

- [ ] **Step 2: Append the transport bootstrap emission**

**The `VYSTAK_ROUTES_JSON` shape used by this plan is, from the start:**

```json
{
  "<short_name>": {"canonical": "<canonical_name>", "address": "<wire_address>"},
  ...
}
```

Where `<short_name>` is what tools pass to `ask_agent(...)`, `<canonical_name>` is the full `{name}.agents.{namespace}`, and `<wire_address>` is the HTTP URL (future transports ignore `address` and resolve from `canonical`). Providers populate this in Tasks 17 and 18.

After the FastAPI app is constructed and `_a2a_handler` is bound, emit the following. Match existing `lines.append(...)` indentation style:

```python
lines.append("")
lines.append("# --- Transport bootstrap ---")
lines.append("import os as _os")
lines.append("import json as _json")
lines.append("import asyncio as _asyncio")
lines.append("from vystak.transport import AgentClient as _AgentClient")
lines.append("from vystak.transport import client as _vystak_client_module")
lines.append("")
lines.append("_routes_raw = _json.loads(_os.environ.get('VYSTAK_ROUTES_JSON', '{}'))")
lines.append("# Short-name → canonical-name map for AgentClient:")
lines.append("_client_routes = {k: v['canonical'] for k, v in _routes_raw.items()}")
lines.append("# Canonical-name → wire-address map for HttpTransport:")
lines.append("_http_routes = {v['canonical']: v['address'] for v in _routes_raw.values()}")
lines.append("")
lines.append("def _build_transport_from_env():")
lines.append("    transport_type = _os.environ.get('VYSTAK_TRANSPORT_TYPE', 'http')")
lines.append("    if transport_type == 'http':")
lines.append("        from vystak_transport_http import HttpTransport")
lines.append("        return HttpTransport(routes=_http_routes)")
lines.append("    raise RuntimeError(f'unsupported VYSTAK_TRANSPORT_TYPE={transport_type}')")
lines.append("")
lines.append("_transport = _build_transport_from_env()")
lines.append(f'AGENT_CANONICAL_NAME = "{agent.canonical_name}"')
lines.append("")
lines.append("_vystak_client_module._DEFAULT_CLIENT = _AgentClient(")
lines.append("    transport=_transport,")
lines.append("    routes=_client_routes,")
lines.append(")")
lines.append("")
lines.append("@app.on_event('startup')")
lines.append("async def _start_transport_listener():")
lines.append("    if _transport.type != 'http':")
lines.append("        _asyncio.create_task(")
lines.append("            _transport.serve(canonical_name=AGENT_CANONICAL_NAME, handler=_a2a_handler)")
lines.append("        )")
```

This establishes the one-and-only `VYSTAK_ROUTES_JSON` shape for the rest of the codebase.

- [ ] **Step 3: Write an adapter test that confirms the emitted source parses**

Add a test to `packages/python/vystak-adapter-langchain/tests/test_templates.py` (or a new file if one doesn't exist):

```python
import ast

from vystak.schema import Agent, Model, Provider
from vystak_adapter_langchain.templates import generate_server_py


def _basic_agent():
    return Agent(
        name="basic",
        model=Model(
            name="m",
            provider=Provider(type="anthropic", api_key_env="K"),
        ),
    )


def test_generated_server_parses_as_python():
    source = generate_server_py(_basic_agent())
    # Must at least parse.
    ast.parse(source)


def test_generated_server_has_transport_bootstrap():
    source = generate_server_py(_basic_agent())
    assert "VYSTAK_TRANSPORT_TYPE" in source
    assert "VYSTAK_ROUTES_JSON" in source
    assert "AGENT_CANONICAL_NAME" in source
    assert "_transport.serve(" in source
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest packages/python/vystak-adapter-langchain/tests/ -v
```

Fix any parse errors in the emitted source.

- [ ] **Step 5: Run full suite**

```bash
just lint-python && just test-python
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add packages/python/vystak-adapter-langchain/src/vystak_adapter_langchain/templates.py \
        packages/python/vystak-adapter-langchain/tests/
git commit -m "feat(langchain-adapter): emit transport bootstrap in generated server

Generated server.py now reads VYSTAK_TRANSPORT_TYPE / VYSTAK_ROUTES_JSON
from env, constructs the appropriate Transport, installs a process-default
AgentClient, and starts the transport listener (no-op for HTTP). Sets
the shared shape of VYSTAK_ROUTES_JSON as
{short_name: {canonical, address}}."
```

---

### Task 15: Update `vystak-channel-chat` to use `AgentClient`

**Files:**
- Modify: `packages/python/vystak-channel-chat/src/vystak_channel_chat/plugin.py`
- Modify: `packages/python/vystak-channel-chat/src/vystak_channel_chat/server_template.py`
- Modify: tests in `packages/python/vystak-channel-chat/tests/`

- [ ] **Step 1: Locate current A2A dispatch in the chat channel server template**

Identify the block in `server_template.py` that builds a JSON-RPC payload and posts via httpx to `{agent_url}/a2a`.

- [ ] **Step 2: Replace the dispatch with `AgentClient`**

Change the emitted server code so, at startup:

```python
# Replaces the existing httpx.AsyncClient patterns:
from vystak.transport import AgentClient
from vystak.transport.client import _default_client

# (AgentClient is installed as the default client by the transport bootstrap
# emitted below; chat channel reuses it.)

async def _forward_to_agent(agent_short_name: str, text: str, metadata: dict) -> str:
    return await _default_client().send_task(agent_short_name, text, metadata=metadata)

async def _stream_from_agent(agent_short_name: str, text: str, metadata: dict):
    async for event in _default_client().stream_task(agent_short_name, text, metadata=metadata):
        yield event
```

The channel needs its own transport bootstrap (mirrors the agent's). Emit the same `_build_transport_from_env()` + `_DEFAULT_CLIENT` install at startup in the channel server template.

- [ ] **Step 3: Update the `plugin.py` signature**

Change `ChannelPlugin.generate_code`'s `resolved_routes: dict[str, str]` to a richer shape. Spec says v1 keeps the dict keyed by short name; value becomes `{"canonical": str, "address": str}`. Update `plugin.py`:

```python
def generate_code(
    self, channel: Channel, resolved_routes: dict[str, dict[str, str]]
) -> GeneratedCode:
    ...
```

And emit `routes.json` using the richer shape:

```python
routes_json = json.dumps(resolved_routes)
```

The channel's emitted server reads `routes.json` at startup and passes it to the transport bootstrap instead of reading from env (channels don't get `VYSTAK_ROUTES_JSON` injected the same way agents do — they ship with a static routes file baked into the container at codegen time).

Alternatively, unify on env vars: have the provider set `VYSTAK_ROUTES_JSON` on the channel container too. Pick env-var-based for consistency; delete the static `routes.json` reading if present.

- [ ] **Step 4: Update channel-chat tests**

```bash
grep -rn "resolved_routes\|routes.json" packages/python/vystak-channel-chat/tests/
```

Update mocks / fixtures to the new shape. Ensure tests that spin up the emitted server in-process still get a working A2A path — if they mock httpx directly, switch to mocking `Transport.send_task` or constructing a `FakeTransport` (reuse the pattern from `test_client.py`).

- [ ] **Step 5: Run chat tests**

```bash
uv run pytest packages/python/vystak-channel-chat/tests/ -v
```

Iterate until green.

- [ ] **Step 6: Run full suite**

```bash
just lint-python && just test-python
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add packages/python/vystak-channel-chat/
git commit -m "refactor(channel-chat): route through AgentClient instead of raw httpx

Chat channel server emits transport bootstrap at startup and dispatches A2A
traffic via vystak.transport.AgentClient. The generate_code route table is
now {short_name: {canonical, address}} to match the agent-side bootstrap."
```

---

### Task 16: Update `vystak-channel-slack` to use `AgentClient`

**Files:**
- Modify: `packages/python/vystak-channel-slack/src/vystak_channel_slack/plugin.py`
- Modify: `packages/python/vystak-channel-slack/src/vystak_channel_slack/server_template.py`
- Modify: tests

Same shape as Task 15. Follow the same steps, applied to the slack channel package.

- [ ] **Step 1: Identify the httpx dispatch in slack's `server_template.py`**

Grep for `httpx` and `_forward_to_agent` in `packages/python/vystak-channel-slack/src/vystak_channel_slack/`.

- [ ] **Step 2: Replace with AgentClient**

Emit the transport bootstrap block + `_default_client()` usage, mirroring Task 15 step 2.

- [ ] **Step 3: Update `plugin.py.generate_code` signature**

Same change as Task 15 step 3 — `resolved_routes: dict[str, dict[str, str]]`.

- [ ] **Step 4: Update slack tests**

```bash
uv run pytest packages/python/vystak-channel-slack/tests/ -v
```

Iterate until green.

- [ ] **Step 5: Run full suite**

```bash
just lint-python && just test-python
```

- [ ] **Step 6: Commit**

```bash
git add packages/python/vystak-channel-slack/
git commit -m "refactor(channel-slack): route through AgentClient instead of raw httpx

Same change shape as channel-chat: emit transport bootstrap, dispatch via
AgentClient, resolved_routes carries {canonical, address} per short name."
```

---

### Task 17: Docker provider wires `TransportPlugin` (realigned)

**Realigned scope (2026-04-19):** The current DockerProvider operates per-agent (`set_agent(agent)` + `apply(plan)`) and per-channel (`apply_channel(plan, channel, resolved_routes)`). There is no top-level Workspace iteration inside the provider. The CLI command (`apply.py`) is the orchestrator. So Task 17 splits between provider, plugins, and CLI.

**Files:**
- Modify: `packages/python/vystak-transport-http/src/vystak_transport_http/plugin.py` — add `resolve_address_for(agent, platform)` helper
- Create: `packages/python/vystak-provider-docker/src/vystak_provider_docker/transport_wiring.py` — small utility that builds the peer-route map + picks a TransportPlugin from an agent's transport type
- Modify: `packages/python/vystak-provider-docker/src/vystak_provider_docker/provider.py` — accept `peer_routes` kwarg through `apply()` + `apply_channel()`; thread into container env; flip channel `resolved_routes` shape
- Modify: `packages/python/vystak-provider-docker/src/vystak_provider_docker/nodes/agent.py` — merge `VYSTAK_TRANSPORT_TYPE` + `VYSTAK_ROUTES_JSON` into the agent container env
- Modify: `packages/python/vystak-channel-chat/src/vystak_channel_chat/plugin.py` and `vystak-channel-slack/src/vystak_channel_slack/plugin.py` — flip `generate_code` signature to `resolved_routes: dict[str, dict[str, str]]`; update `routes.json` emission accordingly
- Modify: `packages/python/vystak-cli/src/vystak_cli/commands/apply.py` — compute peer routes once upfront using the richer shape; pass to `provider.apply(plan, peer_routes=...)` and to `provider.apply_channel(plan, channel, resolved_routes=...)`
- Tests in each affected package.

**Guiding invariants:**
- Canonical names are known from the workspace alone. Wire addresses on Docker are deterministic (`http://{slug(name)}-{slug(ns)}:{port}/a2a`). So peer routes can be computed once, upfront, before any container deploys — no two-phase deploy needed.
- The **per-agent `VYSTAK_ROUTES_JSON`** a container sees is `{peer_short_name: {canonical, address}}` for **all other agents in the workspace** (we're not restricting by channel routes — the agent can call any declared peer). Keeping this simple for v1.
- Channels use a **restricted** route map — only the agents referenced by `channel.routes[*].agent`. The channel plugin's `resolved_routes` parameter takes the richer shape.

---

- [ ] **Step 1: Add `resolve_address_for` to `HttpTransportPlugin`**

Edit `packages/python/vystak-transport-http/src/vystak_transport_http/plugin.py`:

```python
"""HttpTransportPlugin — registers the HTTP transport with providers."""

from __future__ import annotations

from vystak.providers.base import GeneratedCode, TransportPlugin
from vystak.schema import Platform, Transport
from vystak.schema.agent import Agent
from vystak.transport.naming import slug


class HttpTransportPlugin(TransportPlugin):
    type = "http"

    def build_provision_nodes(self, transport: Transport, platform: Platform):
        return []

    def generate_env_contract(
        self, transport: Transport, context: dict
    ) -> dict[str, str]:
        return {"VYSTAK_TRANSPORT_TYPE": "http"}

    def generate_listener_code(self, transport: Transport) -> GeneratedCode | None:
        return None

    def resolve_address_for(
        self, agent: Agent, platform: Platform
    ) -> str:
        """Docker-style DNS URL for an agent. Azure provider will override via its own plugin or kwarg."""
        ns = slug(platform.namespace or "default")
        port = agent.port or 8000
        return f"http://{slug(agent.name)}-{ns}:{port}/a2a"
```

Update the package's test file (`packages/python/vystak-transport-http/tests/test_http_plugin.py`) to add a test for `resolve_address_for`:

```python
def test_resolve_address_for():
    from vystak.schema import Platform, Provider
    from vystak.schema.agent import Agent
    from vystak.schema.model import Model
    p = HttpTransportPlugin()
    provider = Provider(name="docker", type="docker")
    platform = Platform(name="main", type="docker", provider=provider, namespace="prod")
    agent = Agent(
        name="time-agent",
        model=Model(name="m", provider=Provider(name="anthropic", type="anthropic", api_key_env="K")),
        platform=platform,
    )
    url = p.resolve_address_for(agent, platform)
    assert url == "http://time-agent-prod:8000/a2a"
```

- [ ] **Step 2: Create `transport_wiring.py` in the Docker provider**

Create `packages/python/vystak-provider-docker/src/vystak_provider_docker/transport_wiring.py`:

```python
"""Transport wiring for Docker deployments.

Maps an agent's transport type -> TransportPlugin instance, and provides a
helper to compute the VYSTAK_ROUTES_JSON payload for a given agent.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from vystak_transport_http import HttpTransportPlugin

if TYPE_CHECKING:
    from vystak.providers.base import TransportPlugin
    from vystak.schema.agent import Agent

_TRANSPORT_PLUGINS: dict[str, type["TransportPlugin"]] = {
    "http": HttpTransportPlugin,
}


def get_transport_plugin(transport_type: str) -> "TransportPlugin":
    try:
        return _TRANSPORT_PLUGINS[transport_type]()
    except KeyError:
        raise KeyError(
            f"No TransportPlugin registered for type {transport_type!r}; "
            f"known: {sorted(_TRANSPORT_PLUGINS)}"
        ) from None


def build_peer_routes(subject: "Agent", peers: list["Agent"]) -> dict[str, dict[str, str]]:
    """Return {peer_short_name: {canonical, address}} for every peer agent.

    `subject` is the agent whose container is being configured; its own entry
    is excluded from the map. `peers` is the full agents list from the CLI.
    """
    transport = subject.platform.transport
    plugin = get_transport_plugin(transport.type)
    routes: dict[str, dict[str, str]] = {}
    for peer in peers:
        if peer.name == subject.name:
            continue
        if peer.platform is None:
            continue
        routes[peer.name] = {
            "canonical": peer.canonical_name,
            "address": plugin.resolve_address_for(peer, peer.platform),
        }
    return routes


def build_routes_json(subject: "Agent", peers: list["Agent"]) -> str:
    return json.dumps(build_peer_routes(subject, peers))
```

Create `packages/python/vystak-provider-docker/tests/test_transport_wiring.py`:

```python
"""Tests for peer-route wiring."""

import json

from vystak.schema import Platform, Provider, Transport
from vystak.schema.agent import Agent
from vystak.schema.model import Model
from vystak_provider_docker.transport_wiring import (
    build_peer_routes,
    build_routes_json,
    get_transport_plugin,
)


def _agent(name: str, namespace: str = "default") -> Agent:
    provider = Provider(name="docker", type="docker")
    platform = Platform(
        name="main", type="docker", provider=provider, namespace=namespace,
        transport=Transport(name="default-http", type="http"),
    )
    return Agent(
        name=name,
        model=Model(name="m", provider=Provider(name="anthropic", type="anthropic", api_key_env="K")),
        platform=platform,
    )


def test_get_transport_plugin_http():
    p = get_transport_plugin("http")
    assert p.type == "http"


def test_build_peer_routes_excludes_self():
    a = _agent("assistant")
    b = _agent("weather")
    c = _agent("time")
    routes = build_peer_routes(a, [a, b, c])
    assert set(routes.keys()) == {"weather", "time"}
    assert routes["weather"]["canonical"] == "weather.agents.default"
    assert routes["weather"]["address"] == "http://weather-default:8000/a2a"


def test_build_routes_json_is_valid_json():
    a = _agent("assistant")
    b = _agent("weather")
    payload = build_routes_json(a, [a, b])
    parsed = json.loads(payload)
    assert parsed["weather"]["canonical"] == "weather.agents.default"
```

- [ ] **Step 3: Thread peer routes into `DockerAgentNode`**

Inspect `packages/python/vystak-provider-docker/src/vystak_provider_docker/nodes/agent.py` (or wherever `DockerAgentNode` lives — find with `grep -rn "class DockerAgentNode" packages/python/vystak-provider-docker/`).

Locate where the container's `environment` dict is built. Add two new env vars: `VYSTAK_TRANSPORT_TYPE` (from `agent.platform.transport.type`) and `VYSTAK_ROUTES_JSON` (from a `peer_routes_json: str` attribute on the node).

Add `peer_routes_json: str = "{}"` as a keyword-only constructor parameter on `DockerAgentNode` with a default empty-dict JSON string. Then in the environment-building block:

```python
environment = {
    **existing_env,
    "VYSTAK_TRANSPORT_TYPE": self._agent.platform.transport.type,
    "VYSTAK_ROUTES_JSON": self._peer_routes_json,
}
```

Store the kwarg on `self._peer_routes_json` in `__init__`.

- [ ] **Step 4: Update `DockerProvider.apply()` to accept `peer_routes`**

In `packages/python/vystak-provider-docker/src/vystak_provider_docker/provider.py`:

```python
def apply(self, plan: DeployPlan, peer_routes: str | None = None) -> DeployResult:
    ...
    agent_node = DockerAgentNode(
        self._client,
        self._agent,
        self._generated_code,
        plan,
        peer_routes_json=peer_routes or "{}",
    )
    ...
```

`peer_routes` is a JSON-encoded string. Callers (the CLI) use `build_routes_json(agent, peers)` to build it.

- [ ] **Step 5: Update `DockerProvider.apply_channel()` for richer route shape**

Update the signature:

```python
def apply_channel(
    self,
    plan: DeployPlan,
    channel: Channel,
    resolved_routes: dict[str, dict[str, str]],
) -> DeployResult:
```

The existing body calls `plugin.generate_code(channel, resolved_routes)` — that still works; the plugin signatures in Tasks 15/16 currently declare `dict[str, str]`. Update them in Step 6 below.

- [ ] **Step 6: Flip channel plugin signatures**

In `packages/python/vystak-channel-chat/src/vystak_channel_chat/plugin.py` and `vystak-channel-slack/src/vystak_channel_slack/plugin.py`, change:

```python
def generate_code(self, channel: Channel, resolved_routes: dict[str, dict[str, str]]) -> GeneratedCode:
    routes_json = json.dumps(resolved_routes, indent=2)
    return GeneratedCode(
        files={
            "server.py": SERVER_PY,
            "routes.json": routes_json,
            ...
        },
    )
```

The emitted `routes.json` now contains the richer shape. The server's backward-compat path (from Task 15/16) detects the new shape and uses it directly (short-circuit the legacy shape conversion). Add a check in the server's `_load_routes_raw`:

```python
# If the first value is already a dict with "canonical"+"address", use as-is;
# else convert legacy {short: URL} shape.
if raw and isinstance(next(iter(raw.values())), dict) and "canonical" in next(iter(raw.values())):
    return raw
# legacy path
return {
    short: {"canonical": f"{short}.agents.default", "address": url}
    for short, url in raw.items()
}
```

- [ ] **Step 7: Update CLI `apply.py` to compute peer routes upfront**

In `packages/python/vystak-cli/src/vystak_cli/commands/apply.py`:

Import at top:
```python
from vystak_provider_docker.transport_wiring import build_routes_json
```
(This couples the CLI to `vystak-provider-docker`. Acceptable for v1 — when Task 18 lands, extract into a provider-agnostic helper. For now the CLI already imports from provider packages via `provider_factory`.)

Before the agent deploy loop, compute `all_agents = list(defs.agents)`. Inside the loop where `provider.apply(deploy_plan)` is called:

```python
peer_routes = build_routes_json(agent, all_agents)
result = provider.apply(deploy_plan, peer_routes=peer_routes)
```

For the channel loop, replace the existing `resolved_routes` computation with the richer shape. Use `build_peer_routes(channel_subject, filtered_peers)` — channel doesn't have a "subject" agent, so construct a filtered peer list from `agent_urls` + each agent's `canonical_name`:

```python
from vystak_provider_docker.transport_wiring import get_transport_plugin

# Build a map of {agent_name: Agent} for lookup
agents_by_name = {a["name"]: a["agent"] for a in deployed_agents}

resolved_routes = {}
for rule in channel.routes:
    if rule.agent in agents_by_name:
        peer_agent = agents_by_name[rule.agent]
        plugin = get_transport_plugin(peer_agent.platform.transport.type)
        resolved_routes[rule.agent] = {
            "canonical": peer_agent.canonical_name,
            "address": plugin.resolve_address_for(peer_agent, peer_agent.platform),
        }
```

Then pass `resolved_routes` to `provider.apply_channel(...)` — signature already updated in Step 5.

- [ ] **Step 8: Update docker-provider tests**

```bash
uv run pytest packages/python/vystak-provider-docker/tests/ -v
```

Fix assertions that expected old-shape channel routes or old env shapes. If tests instantiate `DockerAgentNode` directly, add `peer_routes_json="{}"` kwarg to satisfy the new signature.

- [ ] **Step 9: Update channel-plugin tests**

```bash
uv run pytest packages/python/vystak-channel-chat/tests/ packages/python/vystak-channel-slack/tests/ -v
```

The plugin tests pass `resolved_routes` to `generate_code`. Change test fixtures to the new shape `{"foo": {"canonical": "foo.agents.default", "address": "http://foo-default:8000/a2a"}}`.

- [ ] **Step 10: Run full lint + test**

```bash
just lint-python && just test-python
```

All gates green before commit.

- [ ] **Step 11: Commit**

```bash
git add packages/python/vystak-transport-http/ \
        packages/python/vystak-provider-docker/ \
        packages/python/vystak-channel-chat/src/vystak_channel_chat/plugin.py \
        packages/python/vystak-channel-chat/src/vystak_channel_chat/server_template.py \
        packages/python/vystak-channel-chat/tests/ \
        packages/python/vystak-channel-slack/src/vystak_channel_slack/plugin.py \
        packages/python/vystak-channel-slack/src/vystak_channel_slack/server_template.py \
        packages/python/vystak-channel-slack/tests/ \
        packages/python/vystak-cli/src/vystak_cli/commands/apply.py
git commit -m "feat(provider-docker): thread TransportPlugin through agent + channel apply

DockerProvider.apply() now accepts peer_routes (JSON string) and injects
VYSTAK_TRANSPORT_TYPE + VYSTAK_ROUTES_JSON into the agent container env.
apply_channel() signature updated: resolved_routes is now
dict[str, dict[str, str]] carrying {canonical, address} per short name.

HttpTransportPlugin gains resolve_address_for(agent, platform), producing
Docker DNS URLs deterministically from canonical names. Channel plugins
(chat + slack) flip generate_code signatures to match.

CLI (apply command) computes peer routes once upfront from the full agent
list via a new vystak-provider-docker.transport_wiring helper, then
passes the JSON to each provider.apply() call. Peer routes are
computable before any container deploys because wire addresses are
deterministic from the workspace definition.

Existing server templates' backward-compat routes.json fallback still
works — they short-circuit when the new shape is detected."
```

---

### Task 18: Azure provider wires `TransportPlugin` (realigned, minimal scope)

**Realigned scope (2026-04-19):** Azure ACA's container-app ingress FQDN is NOT deterministic before the managed environment exists — the `defaultDomain` includes a random slug Azure assigns on env creation. Unlike Docker where peer URLs are fully predictable from the workspace definition, Azure peer URLs require a post-env lookup. For v1, Task 18 does the minimum: signature parity with Docker (so the CLI can call apply uniformly) and `VYSTAK_TRANSPORT_TYPE` env injection. **`VYSTAK_ROUTES_JSON` is left empty on Azure in v1** — users continue using the existing manual `export WEATHER_AGENT_URL=...` workaround for Azure multi-agent setups. Proper Azure peer-route support is a follow-up (likely a two-phase deploy that picks up env.defaultDomain after first deploy).

**Files:**
- Modify: `packages/python/vystak-provider-azure/src/vystak_provider_azure/provider.py`
- Modify: `packages/python/vystak-provider-azure/src/vystak_provider_azure/nodes/container_app.py` (or wherever `ContainerAppNode` lives — verify with grep)
- Modify: `packages/python/vystak-provider-azure/tests/` — update tests that broke due to signature changes
- Modify: `packages/python/vystak-cli/src/vystak_cli/commands/apply.py` — already passes `peer_routes=None` gracefully via the try/except in Task 17c; only minor adjustment if needed

---

- [ ] **Step 1: Locate and read `ContainerAppNode`**

```bash
grep -rn "class ContainerAppNode" packages/python/vystak-provider-azure/
```

Read the full class; identify where container-app environment variables are built. Currently it's likely inside the `provision()` method where a `Container` or `ContainerApp` CRD spec is constructed.

- [ ] **Step 2: Add `peer_routes_json` kwarg to `ContainerAppNode`**

Add a keyword-only constructor parameter with a safe default:

```python
def __init__(
    self,
    *,
    aca_client,
    docker_client,
    rg_name,
    agent,
    generated_code,
    plan,
    platform_config,
    peer_routes_json: str = "{}",
):
    ...
    self._peer_routes_json = peer_routes_json
```

(If the existing `__init__` is positional, convert to keyword-only with `*,` or add `peer_routes_json` at the end with a default. Match the existing style.)

- [ ] **Step 3: Inject transport env vars into the container-app env**

Inside `provision()` where container `env` list is built, merge two new entries. If the existing code uses Azure SDK's `EnvironmentVar(name=..., value=...)`:

```python
env_vars.append(
    EnvironmentVar(name="VYSTAK_TRANSPORT_TYPE", value=self._agent.platform.transport.type)
)
env_vars.append(
    EnvironmentVar(name="VYSTAK_ROUTES_JSON", value=self._peer_routes_json)
)
```

If the existing code uses plain dicts, match that pattern instead.

- [ ] **Step 4: Thread the kwarg through `AzureProvider.apply()`**

In `provider.py`, update the `apply()` signature:

```python
def apply(self, plan: DeployPlan, peer_routes: str | None = None) -> DeployResult:
```

When constructing `ContainerAppNode(...)` inside, pass:

```python
ContainerAppNode(
    aca_client=aca_client,
    docker_client=docker_client,
    rg_name=rg_name,
    agent=self._agent,
    generated_code=self._generated_code,
    plan=plan,
    platform_config=cfg,
    peer_routes_json=peer_routes or "{}",
)
```

- [ ] **Step 5: Flip `apply_channel()`'s route-shape annotation**

```python
def apply_channel(
    self,
    plan: DeployPlan,
    channel: Channel,
    resolved_routes: dict[str, dict[str, str]],
) -> DeployResult:
```

The existing body calls `plugin.generate_code(channel, resolved_routes)` — the plugin signatures were already flipped in Task 17b. Just update the annotation.

Also verify the Azure channel-app node (`AzureChannelAppNode` or similar) receives the `generated_code` from the plugin correctly. Spot-check `grep -rn "class AzureChannelAppNode\|apply_channel" packages/python/vystak-provider-azure/` to locate and confirm the shape flows correctly.

- [ ] **Step 6: `HttpTransportPlugin.resolve_address_for` returns Docker-style URL — leaves Azure paths empty**

No changes to `HttpTransportPlugin.resolve_address_for`. On Azure, when the CLI attempts to build `peer_routes` for an agent on an Azure platform, it will produce URLs shaped like `http://{slug(name)}-{slug(ns)}:8000/a2a` — which is **wrong for Azure**. But the generated agent server uses `_DEFAULT_CLIENT`'s routes only when `ask_agent(...)` is called; if the user isn't calling peer agents (single-agent deployments) or is manually exporting `TIME_AGENT_URL`-style env vars for multi-agent (the existing workaround), this wrongness is inert.

**Document the limitation**: add a comment in `apply.py`'s agent loop:

```python
# TODO: v1 limitation — build_routes_json produces Docker-style URLs.
# For Azure multi-agent setups, peers still require manual env-var export
# (e.g. TIME_AGENT_URL=https://time-agent-prod.<env-domain>/a2a).
# Proper Azure peer-route support: looks up env.defaultDomain post-deploy
# and does a second-pass container update. Follow-up task.
peer_routes = ...
```

Alternatively, special-case Azure in the CLI: skip `build_routes_json` and pass `peer_routes=None` when the platform provider is Azure. This is cleaner:

```python
peer_routes: str | None = None
if agent.platform is not None and agent.platform.provider.type == "docker":
    try:
        plugin = get_transport_plugin(agent.platform.transport.type)
        peer_routes = build_routes_json(list(defs.agents), plugin, agent.platform)
    except Exception:
        pass
```

(Currently Task 17c's code is provider-agnostic — tighten to `provider.type == "docker"` explicitly so we don't silently ship broken URLs on Azure.)

- [ ] **Step 7: Update azure-provider tests**

```bash
uv run pytest packages/python/vystak-provider-azure/tests/ -v
```

Fix any assertions that break due to:
- `ContainerAppNode` kwarg-only / new param (constructor calls).
- `AzureProvider.apply` / `apply_channel` new signatures.
- Tests that assert against environment-variable lists now including `VYSTAK_TRANSPORT_TYPE` and `VYSTAK_ROUTES_JSON`.

- [ ] **Step 8: Update CLI test if needed**

If Task 17c's CLI test mocks `provider.apply(...)`, verify the mock still matches. If Step 6's Docker-only guard is added, test the Azure skip path.

- [ ] **Step 9: Final gate**

```bash
just lint-python && just test-python
```

All gates green before commit.

- [ ] **Step 10: Commit**

```bash
git add packages/python/vystak-provider-azure/ \
        packages/python/vystak-cli/src/vystak_cli/commands/apply.py
git commit -m "feat(provider-azure): thread TransportPlugin signature parity with Docker

AzureProvider.apply() accepts peer_routes kwarg (Docker parity).
apply_channel() signature flipped to dict[str, dict[str, str]].
ContainerAppNode injects VYSTAK_TRANSPORT_TYPE into every container app
so the generated server's transport bootstrap activates correctly.

Known limitation (documented in apply.py): Azure peer-route URL
population is deferred to a follow-up task because ACA's environment
default_domain is only known post-deploy. For v1, Azure multi-agent
setups continue using the existing manual env-var export workaround
(TIME_AGENT_URL=..., WEATHER_AGENT_URL=...). Docker multi-agent gets
the full peer_routes treatment from Task 17."
```

---

### Task 19: Hash tree integration (realigned)

**Realigned scope (2026-04-19):** The `hash_agent(agent: Agent)` function in `packages/python/vystak/src/vystak/hash/tree.py` is the authoritative hash entry point — no `AgentHashTree.for_workspace` exists. The realignment reads `agent.platform.transport` directly (embedded model) and contributes a new `transport` section to the hash tree.

**Files:**
- Modify: `packages/python/vystak/src/vystak/hash/tree.py` — add `transport` section to `AgentHashTree` + compose it in `hash_agent`
- Create or modify: `packages/python/vystak/tests/hash/test_tree.py` (may exist already — check with `ls`)

**Existing hash tree structure** (for reference):

```python
@dataclass
class AgentHashTree:
    brain: str
    skills: str
    mcp_servers: str
    workspace: str
    resources: str
    secrets: str
    sessions: str
    memory: str
    services: str
    root: str   # combined
```

Add `transport: str` alongside the existing sections, contributing to `root`.

---

- [ ] **Step 1: Write failing tests**

Check if `packages/python/vystak/tests/hash/test_tree.py` exists. If not, create it. If it exists, append to it.

```python
"""Hash-tree tests for transport integration."""

from vystak.hash.tree import AgentHashTree, hash_agent
from vystak.schema import (
    Agent,
    HttpConfig,
    Model,
    NatsConfig,
    Platform,
    Provider,
    Transport,
    TransportConnection,
)


def _agent(transport: Transport | None = None) -> Agent:
    """Build an Agent with an embedded Platform + Transport for hashing tests."""
    platform = Platform(
        name="main",
        type="docker",
        provider=Provider(name="docker", type="docker"),
        transport=transport,  # None triggers the default-http synthesis
    )
    return Agent(
        name="a",
        model=Model(
            name="m",
            provider=Provider(name="anthropic", type="anthropic", api_key_env="K"),
        ),
        platform=platform,
    )


class TestTransportHashing:
    def test_transport_section_present(self):
        tree = hash_agent(_agent())
        assert hasattr(tree, "transport")
        assert isinstance(tree.transport, str)
        assert len(tree.transport) == 64  # sha256 hex

    def test_hash_changes_when_transport_type_changes(self):
        t1 = Transport(name="bus", type="http")
        t2 = Transport(name="bus", type="nats", config=NatsConfig())
        h1 = hash_agent(_agent(t1))
        h2 = hash_agent(_agent(t2))
        assert h1.transport != h2.transport
        assert h1.root != h2.root

    def test_hash_changes_when_config_changes(self):
        t1 = Transport(name="bus", type="nats", config=NatsConfig(jetstream=True))
        t2 = Transport(name="bus", type="nats", config=NatsConfig(jetstream=False))
        h1 = hash_agent(_agent(t1))
        h2 = hash_agent(_agent(t2))
        assert h1.transport != h2.transport
        assert h1.root != h2.root

    def test_hash_unchanged_for_byo_connection(self):
        # Same transport type/config, different BYO connection — portable.
        t1 = Transport(
            name="bus", type="nats", config=NatsConfig(),
            connection=TransportConnection(url_env="DEV_NATS_URL"),
        )
        t2 = Transport(
            name="bus", type="nats", config=NatsConfig(),
            connection=TransportConnection(url_env="PROD_NATS_URL"),
        )
        h1 = hash_agent(_agent(t1))
        h2 = hash_agent(_agent(t2))
        assert h1.transport == h2.transport
        assert h1.root == h2.root

    def test_hash_unchanged_for_transport_name(self):
        # The transport's `name` field is identity for references, not config.
        # Should not affect the agent's hash.
        t1 = Transport(name="bus-alpha", type="http")
        t2 = Transport(name="bus-beta", type="http")
        h1 = hash_agent(_agent(t1))
        h2 = hash_agent(_agent(t2))
        assert h1.transport == h2.transport
        assert h1.root == h2.root

    def test_default_http_synthesis_consistent(self):
        # An agent built with platform.transport=None gets default-http
        # synthesised; hash should match an explicit Transport(name="default-http", type="http").
        h1 = hash_agent(_agent(None))
        h2 = hash_agent(_agent(Transport(name="default-http", type="http")))
        assert h1.transport == h2.transport
        assert h1.root == h2.root

    def test_no_platform_agent_hashes_null_transport(self):
        # Edge case: agent without a platform. Hash must be stable, not error.
        agent = Agent(
            name="a",
            model=Model(
                name="m",
                provider=Provider(name="anthropic", type="anthropic", api_key_env="K"),
            ),
            platform=None,
        )
        tree = hash_agent(agent)
        # Transport section still present; computed as "null" hash.
        assert tree.transport is not None
        assert len(tree.transport) == 64
```

- [ ] **Step 2: Run tests to confirm failures**

```bash
uv run pytest packages/python/vystak/tests/hash/test_tree.py -v
```

Expected: `AttributeError: 'AgentHashTree' object has no attribute 'transport'` — the dataclass doesn't have this field yet.

- [ ] **Step 3: Extend `AgentHashTree` and `hash_agent`**

Edit `packages/python/vystak/src/vystak/hash/tree.py`:

1. Add `transport: str` to the `AgentHashTree` dataclass (alongside existing sections, alphabetical or at the end — match existing order by placing after `services`).

2. Add a helper `_hash_transport` near `_hash_str`:

```python
import json


def _hash_transport(agent: Agent) -> str:
    """Contribute transport identity (type + config) to the agent hash.

    `connection` is excluded — BYO URLs/credentials are portable across
    environments without triggering redeploy. `name` is also excluded —
    it's an identity field for cross-resource references, not config.
    """
    if agent.platform is None or agent.platform.transport is None:
        return _hash_str(None)
    transport = agent.platform.transport
    payload = {
        "type": transport.type,
        "config": transport.config.model_dump() if transport.config else None,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode()
    ).hexdigest()
```

3. In `hash_agent`, compute `transport = _hash_transport(agent)` and include it in the `sections` concat + the returned `AgentHashTree`:

```python
def hash_agent(agent: Agent) -> AgentHashTree:
    brain = hash_model(agent.model)
    skills = _hash_list(agent.skills)
    mcp_servers = _hash_list(agent.mcp_servers)
    workspace = _hash_optional(agent.workspace)
    resources = _hash_list(agent.resources)
    secrets = _hash_list(agent.secrets)
    sessions = _hash_optional(agent.sessions)
    memory = _hash_optional(agent.memory)
    services = _hash_list(agent.services)
    transport = _hash_transport(agent)

    sections = "|".join(
        [
            brain,
            skills,
            mcp_servers,
            workspace,
            resources,
            secrets,
            sessions,
            memory,
            services,
            transport,
        ]
    )
    root = hashlib.sha256(sections.encode()).hexdigest()

    return AgentHashTree(
        brain=brain,
        skills=skills,
        mcp_servers=mcp_servers,
        workspace=workspace,
        resources=resources,
        secrets=secrets,
        sessions=sessions,
        memory=memory,
        services=services,
        transport=transport,
        root=root,
    )
```

- [ ] **Step 4: Run tests — expect pass**

```bash
uv run pytest packages/python/vystak/tests/hash/ -v
```

Expected: all 7 new `TestTransportHashing` tests PASS.

- [ ] **Step 5: Run full gates**

```bash
just lint-python && just test-python
```

Expected: PASS. Note: **existing hash tests will break** because the `root` hash now includes the transport section — any test that pins `root` to a specific hex string needs regeneration. If that happens, run the failing test, capture the new `root` value from the failure output, and update the expected constant. **Do not change the test's semantic assertion** — only the pinned value.

- [ ] **Step 6: Commit**

```bash
git add packages/python/vystak/src/vystak/hash/tree.py \
        packages/python/vystak/tests/hash/
git commit -m "feat(hash): include transport type/config in AgentHashTree

Adds a transport section to the agent hash tree, reading directly from
agent.platform.transport (embedded Transport pattern). Changes to
transport.type or transport.config trigger redeploy; BYO connection
details and the transport's own name are excluded — same agent, different
broker instance or reference name, remains portable."
```

---

### Task 20: `WorkspaceOverride` schema

**Files:**
- Create: `packages/python/vystak/src/vystak/schema/overrides.py`
- Modify: `packages/python/vystak/src/vystak/schema/__init__.py`
- Create: `packages/python/vystak/tests/schema/test_overrides.py`

- [ ] **Step 1: Write failing tests**

Create `packages/python/vystak/tests/schema/test_overrides.py`:

```python
"""Tests for WorkspaceOverride merge semantics."""

from __future__ import annotations

import pytest

from vystak.schema import (
    Agent, Model, NatsConfig, Platform, Provider, Transport,
    TransportConnection, Workspace,
)
from vystak.schema.overrides import (
    PlatformOverride, TransportOverride, WorkspaceOverride,
)


def _ws(transport: Transport | None = None) -> Workspace:
    agent = Agent(
        name="a",
        model=Model(name="m", provider=Provider(type="anthropic", api_key_env="K")),
    )
    platform = Platform(
        name="main", provider="docker",
        transport=transport.name if transport else None,
    )
    return Workspace(
        agents=[agent], platforms=[platform],
        transports=[transport] if transport else [],
    )


class TestWorkspaceOverride:
    def test_override_transport_type(self):
        base = _ws(Transport(name="bus", type="http"))
        override = WorkspaceOverride(
            transports={
                "bus": TransportOverride(
                    type="nats", config=NatsConfig(),
                )
            }
        )
        merged = override.apply(base)
        t = next(t for t in merged.transports if t.name == "bus")
        assert t.type == "nats"
        assert t.config.type == "nats"

    def test_override_swap_platform_transport_ref(self):
        base = _ws(Transport(name="bus", type="http"))
        # Add a second transport to the base workspace.
        base.transports.append(Transport(name="nats-bus", type="nats"))
        # Override flips which transport the platform uses.
        override = WorkspaceOverride(
            platforms={"main": PlatformOverride(transport="nats-bus")}
        )
        merged = override.apply(base)
        assert merged.platforms[0].transport == "nats-bus"

    def test_override_byo_connection(self):
        base = _ws(Transport(name="bus", type="nats", config=NatsConfig()))
        override = WorkspaceOverride(
            transports={
                "bus": TransportOverride(
                    connection=TransportConnection(
                        url_env="PROD_NATS_URL",
                        credentials_secret="prod-nats-creds",
                    ),
                )
            }
        )
        merged = override.apply(base)
        t = next(t for t in merged.transports if t.name == "bus")
        assert t.connection.url_env == "PROD_NATS_URL"
        assert t.connection.credentials_secret == "prod-nats-creds"

    def test_override_unknown_transport_raises(self):
        base = _ws(Transport(name="bus", type="http"))
        override = WorkspaceOverride(
            transports={"nonexistent": TransportOverride(type="nats")}
        )
        with pytest.raises(ValueError, match="nonexistent"):
            override.apply(base)

    def test_override_unknown_platform_raises(self):
        base = _ws(Transport(name="bus", type="http"))
        override = WorkspaceOverride(
            platforms={"nonexistent": PlatformOverride(transport="bus")}
        )
        with pytest.raises(ValueError, match="nonexistent"):
            override.apply(base)

    def test_empty_override_is_noop(self):
        base = _ws(Transport(name="bus", type="http"))
        merged = WorkspaceOverride().apply(base)
        assert merged.transports[0].type == "http"
        assert merged.platforms[0].transport == "bus"

    def test_partial_config_replaces_not_merges(self):
        base = _ws(Transport(
            name="bus", type="nats",
            config=NatsConfig(subject_prefix="old", jetstream=True),
        ))
        override = WorkspaceOverride(
            transports={
                "bus": TransportOverride(
                    config=NatsConfig(subject_prefix="new"),
                )
            }
        )
        merged = override.apply(base)
        t = next(t for t in merged.transports if t.name == "bus")
        # Entire config object replaced — jetstream goes back to default (True).
        assert t.config.subject_prefix == "new"
        assert t.config.jetstream is True
```

- [ ] **Step 2: Run — expect ImportError**

```bash
uv run pytest packages/python/vystak/tests/schema/test_overrides.py -v
```

- [ ] **Step 3: Create `overrides.py`**

Create `packages/python/vystak/src/vystak/schema/overrides.py`:

```python
"""WorkspaceOverride — per-environment overlay for transport + platform config."""

from __future__ import annotations

from copy import deepcopy
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from vystak.schema.transport import (
    TransportConfig,
    TransportConnection,
    TransportType,
)

if TYPE_CHECKING:
    from vystak.schema.workspace import Workspace


class TransportOverride(BaseModel):
    """Fields that may be overridden on a named Transport."""

    type: TransportType | None = None
    config: TransportConfig | None = None
    connection: TransportConnection | None = None


class PlatformOverride(BaseModel):
    """Fields that may be overridden on a named Platform."""

    transport: str | None = None


class WorkspaceOverride(BaseModel):
    """Top-level overlay. Merged into a base Workspace at load time."""

    transports: dict[str, TransportOverride] = Field(default_factory=dict)
    platforms: dict[str, PlatformOverride] = Field(default_factory=dict)

    def apply(self, base: "Workspace") -> "Workspace":
        """Return a new Workspace with overrides applied. Does not mutate
        the base."""
        merged = deepcopy(base)

        known_transports = {t.name for t in merged.transports}
        for name, override in self.transports.items():
            if name not in known_transports:
                raise ValueError(
                    f"WorkspaceOverride references unknown transport "
                    f"{name!r}; known: {sorted(known_transports)}"
                )
            target = next(t for t in merged.transports if t.name == name)
            data = override.model_dump(exclude_unset=True)
            for field, value in data.items():
                # Use setattr so re-validation triggers via Pydantic; for
                # Pydantic v2 BaseModel, setattr on a field works when
                # model_config.validate_assignment is True. To keep this
                # implementation side-effect-free, reconstruct the model.
                setattr(target, field, value)

        known_platforms = {p.name for p in merged.platforms}
        for name, override in self.platforms.items():
            if name not in known_platforms:
                raise ValueError(
                    f"WorkspaceOverride references unknown platform "
                    f"{name!r}; known: {sorted(known_platforms)}"
                )
            target = next(p for p in merged.platforms if p.name == name)
            data = override.model_dump(exclude_unset=True)
            for field, value in data.items():
                setattr(target, field, value)

        # Re-validate the merged workspace so transport refs are still valid.
        from vystak.schema.workspace import Workspace

        return Workspace.model_validate(merged.model_dump())
```

Note: the `setattr` approach assumes `model_config = ConfigDict(validate_assignment=True)` on `Transport`, `Platform`. If that's not set in the base models, add it:

```python
# In Transport class (and Platform):
model_config = ConfigDict(validate_assignment=True)
```

Add this to `transport.py` and `platform.py` if missing.

- [ ] **Step 4: Export from `schema/__init__.py`**

```python
from vystak.schema.overrides import (
    PlatformOverride,
    TransportOverride,
    WorkspaceOverride,
)

__all__ = [
    # ... existing ...
    "PlatformOverride",
    "TransportOverride",
    "WorkspaceOverride",
]
```

- [ ] **Step 5: Run tests + lint**

```bash
uv run pytest packages/python/vystak/tests/schema/test_overrides.py -v
just lint-python && just test-python
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add packages/python/vystak/src/vystak/schema/overrides.py \
        packages/python/vystak/src/vystak/schema/transport.py \
        packages/python/vystak/src/vystak/schema/platform.py \
        packages/python/vystak/src/vystak/schema/__init__.py \
        packages/python/vystak/tests/schema/test_overrides.py
git commit -m "feat(schema): WorkspaceOverride + apply() merge function

Per-environment overlay model. Keyed by resource name; field-level
replacement (no deep-merge). Re-validates the merged workspace so typos
in overlay keys surface at load time."
```

---

### Task 21: CLI overlay loader

**Files:**
- Modify: `packages/python/vystak-cli/src/vystak_cli/loader.py`
- Create: `packages/python/vystak-cli/tests/test_loader_overlay.py`

- [ ] **Step 1: Write failing tests**

Create `packages/python/vystak-cli/tests/test_loader_overlay.py`:

```python
"""Tests for per-environment overlay loading."""

from __future__ import annotations

import textwrap

import pytest

from vystak_cli.loader import load_workspace


def _write(tmp_path, filename: str, content: str) -> None:
    (tmp_path / filename).write_text(textwrap.dedent(content))


def test_no_overlay_returns_base(tmp_path):
    _write(tmp_path, "vystak.py", """
        from vystak.schema import Agent, Model, Platform, Provider, Workspace

        agent = Agent(
            name='a',
            model=Model(name='m', provider=Provider(type='anthropic', api_key_env='K')),
        )
        platform = Platform(name='main', provider='docker')
        workspace = Workspace(agents=[agent], platforms=[platform])
    """)

    ws = load_workspace(tmp_path / "vystak.py")
    assert ws.transports[0].name == "default-http"


def test_python_overlay_applied(tmp_path):
    _write(tmp_path, "vystak.py", """
        from vystak.schema import (
            Agent, Model, Platform, Provider, Transport, Workspace,
        )

        agent = Agent(
            name='a',
            model=Model(name='m', provider=Provider(type='anthropic', api_key_env='K')),
        )
        platform = Platform(name='main', provider='docker', transport='bus')
        t = Transport(name='bus', type='http')
        workspace = Workspace(agents=[agent], platforms=[platform], transports=[t])
    """)

    _write(tmp_path, "vystak.prod.py", """
        from vystak.schema import NatsConfig, WorkspaceOverride, TransportOverride

        override = WorkspaceOverride(
            transports={'bus': TransportOverride(type='nats', config=NatsConfig())},
        )
    """)

    ws = load_workspace(tmp_path / "vystak.py", env="prod")
    assert ws.transports[0].type == "nats"


def test_yaml_overlay_applied(tmp_path):
    _write(tmp_path, "vystak.py", """
        from vystak.schema import (
            Agent, Model, Platform, Provider, Transport, Workspace,
        )

        agent = Agent(
            name='a',
            model=Model(name='m', provider=Provider(type='anthropic', api_key_env='K')),
        )
        platform = Platform(name='main', provider='docker', transport='bus')
        t = Transport(name='bus', type='http')
        workspace = Workspace(agents=[agent], platforms=[platform], transports=[t])
    """)

    _write(tmp_path, "vystak.staging.yaml", """
        overrides:
          transports:
            bus:
              type: nats
              config:
                jetstream: true
                subject_prefix: vystak-staging
    """)

    ws = load_workspace(tmp_path / "vystak.py", env="staging")
    assert ws.transports[0].type == "nats"
    assert ws.transports[0].config.subject_prefix == "vystak-staging"


def test_missing_overlay_file_with_env_raises(tmp_path):
    _write(tmp_path, "vystak.py", """
        from vystak.schema import Agent, Model, Platform, Provider, Workspace
        agent = Agent(
            name='a',
            model=Model(name='m', provider=Provider(type='anthropic', api_key_env='K')),
        )
        workspace = Workspace(agents=[agent], platforms=[Platform(name='main', provider='docker')])
    """)

    with pytest.raises(FileNotFoundError, match="vystak.nonexistent"):
        load_workspace(tmp_path / "vystak.py", env="nonexistent")
```

- [ ] **Step 2: Run — expect failures**

```bash
uv run pytest packages/python/vystak-cli/tests/test_loader_overlay.py -v
```

- [ ] **Step 3: Modify `loader.py` to support overlays**

In `packages/python/vystak-cli/src/vystak_cli/loader.py`, add overlay resolution. Current signature is something like `load_workspace(path: Path) -> Workspace`; change to:

```python
def load_workspace(path: Path, *, env: str | None = None) -> Workspace:
    """Load a workspace. If `env` is set, apply the matching overlay."""
    base = _load_base(path)  # existing logic factored out
    if env is None:
        return Workspace.model_validate(base.model_dump())

    overlay_py = path.parent / f"vystak.{env}.py"
    overlay_yaml = path.parent / f"vystak.{env}.yaml"
    if overlay_py.exists():
        override = _load_python_overlay(overlay_py)
    elif overlay_yaml.exists():
        override = _load_yaml_overlay(overlay_yaml)
    else:
        raise FileNotFoundError(
            f"env={env!r} requested but no vystak.{env}.py or "
            f"vystak.{env}.yaml found next to {path}"
        )

    return override.apply(base)


def _load_python_overlay(path: Path) -> WorkspaceOverride:
    import importlib.util

    spec = importlib.util.spec_from_file_location(f"vystak_overlay_{path.stem}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    override = getattr(module, "override", None)
    if not isinstance(override, WorkspaceOverride):
        raise ValueError(
            f"{path} must export `override: WorkspaceOverride`; got {type(override)}"
        )
    return override


def _load_yaml_overlay(path: Path) -> WorkspaceOverride:
    import yaml

    with path.open() as f:
        raw = yaml.safe_load(f) or {}
    overrides = raw.get("overrides", {})
    return WorkspaceOverride.model_validate(overrides)
```

Add imports at the top:

```python
from vystak.schema.overrides import WorkspaceOverride
```

If there's no existing `_load_base`, factor the existing load logic into it.

- [ ] **Step 4: Run tests**

```bash
uv run pytest packages/python/vystak-cli/tests/test_loader_overlay.py -v
```

Iterate until green.

- [ ] **Step 5: Full test suite**

```bash
just lint-python && just test-python
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add packages/python/vystak-cli/src/vystak_cli/loader.py \
        packages/python/vystak-cli/tests/test_loader_overlay.py
git commit -m "feat(cli): per-environment overlay loader

load_workspace(path, env='prod') loads base vystak.py and, if provided,
applies the matching vystak.<env>.py or vystak.<env>.yaml overlay via
WorkspaceOverride.apply()."
```

---

### Task 22: `--env` / `-e` flag on CLI commands

**Files:**
- Modify: `packages/python/vystak-cli/src/vystak_cli/main.py` (or the module where Click/Typer commands are defined)
- Modify: existing CLI tests

- [ ] **Step 1: Identify the CLI framework in use**

```bash
grep -rn "click\|typer" packages/python/vystak-cli/src/vystak_cli/ | head -5
```

- [ ] **Step 2: Add `--env` / `-e` option to each relevant command**

For each of `plan`, `apply`, `destroy`, `status`, `logs`, add:

```python
@click.option(
    "--env", "-e",
    default=None,
    envvar="VYSTAK_ENV",
    help="Environment name. Applies vystak.<env>.py/.yaml overlay if present.",
)
```

Pass the value through to `load_workspace(path, env=env)`.

Echo the resolved env to the user near the top of each command's output:

```python
if env:
    click.echo(f"Environment: {env}")
else:
    click.echo("Environment: (base)")
```

- [ ] **Step 3: Write CLI-level tests**

Extend the existing CLI tests in `packages/python/vystak-cli/tests/`:

```python
def test_plan_with_env_flag(cli_runner, tmp_path):
    # Sets up a base + overlay; invokes the CLI with --env prod; asserts
    # the merged transport type is used in the plan output.
    ...
```

Use `click.testing.CliRunner`.

- [ ] **Step 4: Run full suite**

```bash
just lint-python && just test-python
```

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-cli/
git commit -m "feat(cli): --env / -e flag on plan, apply, destroy, status, logs

Flag defaults to VYSTAK_ENV env var. Resolved environment name is echoed
at the top of each command's output."
```

---

### Task 23: Migrate `examples/multi-agent/` tools to `ask_agent`

**Files:**
- Modify: `examples/multi-agent/assistant/tools/ask_time_agent.py`
- Modify: `examples/multi-agent/assistant/tools/ask_weather_agent.py`
- Modify: `examples/multi-agent/vystak.py`

- [ ] **Step 1: Replace `ask_time_agent.py` body**

Replace the whole file with:

```python
"""Call the peer time-agent via Vystak's transport abstraction."""

from vystak.transport import ask_agent


async def ask_time_agent(question: str) -> str:
    """Ask the deployed time-agent a question. Returns its reply text."""
    return await ask_agent("time-agent", question)
```

- [ ] **Step 2: Replace `ask_weather_agent.py` body**

Same shape:

```python
"""Call the peer weather-agent via Vystak's transport abstraction."""

from vystak.transport import ask_agent


async def ask_weather_agent(question: str) -> str:
    """Ask the deployed weather-agent a question. Returns its reply text."""
    return await ask_agent("weather-agent", question)
```

- [ ] **Step 3: Update `examples/multi-agent/vystak.py`**

Make the platform explicit about its transport (optional — the default-http synthesis covers it, but explicit is better for an example):

```python
from vystak.schema import (
    Agent, Model, Platform, Provider, Transport, Workspace,
)

# ... existing agent definitions ...

http_transport = Transport(name="default-http", type="http")

platform = Platform(name="main", provider="docker", transport="default-http")

workspace = Workspace(
    agents=[assistant, time_agent, weather_agent],
    platforms=[platform],
    transports=[http_transport],
)
```

- [ ] **Step 4: Verify the example still parses**

```bash
uv run python -c "from vystak_cli.loader import load_workspace; from pathlib import Path; ws = load_workspace(Path('examples/multi-agent/vystak.py')); print(len(ws.agents), 'agents')"
```

Expected: `3 agents`.

- [ ] **Step 5: Run full suite**

```bash
just lint-python && just test-python
```

- [ ] **Step 6: Commit**

```bash
git add examples/multi-agent/
git commit -m "refactor(example,multi-agent): migrate tools to ask_agent()

Replaces hardcoded URLs + httpx with vystak.transport.ask_agent(). Makes
the platform's default-http transport explicit. Demonstrates the new
shape for user-written agent-to-agent tools."
```

---

### Task 24: End-to-end verification — existing Docker example deploys

**Files:** none (verification only)

- [ ] **Step 1: Plan the existing multi-agent example**

```bash
cd /Users/akolodkin/Developer/work/AgentsStack
uv run vystak plan --project examples/multi-agent/vystak.py
```

Expected: output shows 3 agents to create or update; no errors about transport or routes; the synthesized/declared `default-http` transport appears.

- [ ] **Step 2: Apply**

```bash
uv run vystak apply --project examples/multi-agent/vystak.py
```

Expected: containers come up; agents become healthy.

- [ ] **Step 3: Exercise an agent-to-agent call**

Either through the provided chat channel (if configured) or via direct curl to the assistant's `/a2a` endpoint with a question that requires the time or weather agent.

```bash
curl -X POST http://127.0.0.1:8000/a2a -H 'Content-Type: application/json' -d '{
  "jsonrpc": "2.0",
  "id": "1",
  "method": "tasks/send",
  "params": {
    "id": "t1",
    "message": {"role": "user", "parts": [{"text": "what time is it?"}]},
    "metadata": {}
  }
}'
```

Expected: returns a valid A2A response (assistant called time-agent via `ask_agent`, got a reply).

- [ ] **Step 4: Verify env-var shape on a running container**

```bash
docker exec <assistant-container-name> env | grep VYSTAK_
```

Expected:
```
VYSTAK_TRANSPORT_TYPE=http
VYSTAK_ROUTES_JSON={"time-agent": {"canonical": "time-agent.agents.default", "address": "http://time-agent-default:8000/a2a"}, ...}
```

- [ ] **Step 5: Tear down**

```bash
uv run vystak destroy --project examples/multi-agent/vystak.py
```

- [ ] **Step 6: Commit verification note (optional)**

No commit necessary unless the example needed adjustments. If anything was modified in the process, commit with:

```bash
git add examples/multi-agent/
git commit -m "chore(example): tweaks found during end-to-end verification"
```

---

### Task 25: Docs — transport concept + environment overlays

**Files:**
- Create: `website/docs/concepts/transport.md`
- Create: `website/docs/deploying/environments.md`
- Modify: `website/sidebars.js` (if needed to surface new pages)

- [ ] **Step 1: Draft the transport concept page**

Create `website/docs/concepts/transport.md`. Structure (400–600 words):

1. What it is — east-west abstraction, HTTP today, NATS/SB soon.
2. Where it lives — Platform.transport → Transport resource.
3. Canonical addressing — transport resolves.
4. How tools use it — `ask_agent()` example.
5. Replication safety — single note, one paragraph.

- [ ] **Step 2: Draft the environments page**

Create `website/docs/deploying/environments.md`. Structure (300–400 words):

1. Overlay file naming.
2. Python vs YAML shape — one example each.
3. Merge semantics (replacement not deep-merge).
4. CLI — `--env` flag + `VYSTAK_ENV`.
5. What can be overridden in v1 (transport fields + Platform.transport ref).

- [ ] **Step 3: Add to sidebar**

Update `website/sidebars.js` if the generated sidebar needs either page surfaced in a specific order. If auto-generated, no edit needed.

- [ ] **Step 4: Build docs locally**

```bash
just docs-build
```

Expected: build succeeds, no broken-link warnings on the new pages.

- [ ] **Step 5: Commit**

```bash
git add website/docs/concepts/transport.md website/docs/deploying/environments.md website/sidebars.js
git commit -m "docs: transport concept + environment overlays

Two new doc pages: concepts/transport.md explains the abstraction and the
canonical addressing model; deploying/environments.md documents overlay
files + the --env CLI flag."
```

---

### Task 26: Final CI pass + cleanup

- [ ] **Step 1: Full CI parity run**

```bash
just ci
```

Expected: `lint-python` PASS, `test-python` PASS, `typecheck-typescript` PASS, `test-typescript` PASS. `lint-typescript` and `typecheck-python` may still fail with pre-existing errors — verify the failure counts have not increased.

- [ ] **Step 2: If `typecheck-python` regressed**

```bash
uv run pyright packages/python/ 2>&1 | tail -50
```

Fix any errors that this plan introduced (new ones; not pre-existing). Do not fix unrelated pre-existing errors.

- [ ] **Step 3: Check the git log is tidy**

```bash
git log --oneline <plan-a-start-sha>..HEAD
```

Each commit should be a single logical task. No fixup commits; no trailing WIPs.

- [ ] **Step 4: Push + open PR**

(Do not push automatically — confirm with user first.)

Once user approves:

```bash
git push -u origin pivot/channel-architecture
gh pr create --title "feat: transport abstraction + environment overlays (Plan A)" \
  --body "See docs/superpowers/specs/2026-04-19-transport-abstraction-design.md for the design and docs/superpowers/plans/2026-04-19-transport-abstraction-plan-a.md for the implementation plan."
```

Plan A done. Plan B (NATS transport) picks up from here.
