# Transport Abstraction — Plan A (Abstraction + HTTP + Environment Overlays)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Introduce a pluggable `Transport` abstraction for east-west A2A traffic (channel→agent, agent→agent), extract existing HTTP behaviour into a concrete `HttpTransport`, and add per-environment config overlays driven by a `--env` CLI flag. No user-visible wire-protocol change: HTTP remains the default and backward compatibility is maintained.

**Architecture:** New module `vystak.transport` holds the ABC (`Transport`, `A2AHandler`, `AgentClient`, `ask_agent`, naming helpers). Existing `/a2a` handler logic is extracted from the LangChain adapter into a transport-agnostic `A2AHandler` imported from `vystak.transport`. A new `vystak-transport-http` package implements `Transport` using FastAPI + httpx. Channel plugins (`vystak-channel-slack`, `vystak-channel-chat`) stop using `httpx` directly and route through `AgentClient`. A new Pydantic `Transport` resource is added to the schema; `Platform.transport` references it by name. `WorkspaceOverride` + `vystak apply --env <name>` enables per-environment config swaps.

**Tech Stack:** Python 3.11+, Pydantic v2, FastAPI, httpx, sse-starlette, pytest, uv workspace.

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

### Task 2: Platform.transport + Workspace.transports fields

**Files:**
- Modify: `packages/python/vystak/src/vystak/schema/platform.py`
- Modify: `packages/python/vystak/src/vystak/schema/workspace.py`
- Modify: `packages/python/vystak/tests/schema/test_transport_schema.py`

- [ ] **Step 1: Add failing tests**

Append to `packages/python/vystak/tests/schema/test_transport_schema.py`:

```python
from vystak.schema import Agent, Model, Platform, Provider, Workspace


class TestPlatformTransport:
    def _agent(self):
        return Agent(
            name="a",
            model=Model(
                name="m",
                provider=Provider(type="anthropic", api_key_env="K"),
            ),
        )

    def test_platform_transport_optional(self):
        p = Platform(name="p", provider="docker")
        assert p.transport is None

    def test_platform_transport_by_name(self):
        p = Platform(name="p", provider="docker", transport="bus")
        assert p.transport == "bus"


class TestWorkspaceTransports:
    def _agent(self):
        return Agent(
            name="a",
            model=Model(
                name="m",
                provider=Provider(type="anthropic", api_key_env="K"),
            ),
        )

    def test_workspace_default_synthesizes_http(self):
        p = Platform(name="main", provider="docker")
        ws = Workspace(agents=[self._agent()], platforms=[p])
        names = [t.name for t in ws.transports]
        assert "default-http" in names
        default = next(t for t in ws.transports if t.name == "default-http")
        assert default.type == "http"

    def test_workspace_custom_transport_used_as_is(self):
        t = Transport(name="bus", type="nats")
        p = Platform(name="main", provider="docker", transport="bus")
        ws = Workspace(agents=[self._agent()], platforms=[p], transports=[t])
        assert [t.name for t in ws.transports] == ["bus"]
        # Platform still references the user-provided name
        assert ws.platforms[0].transport == "bus"

    def test_workspace_platform_without_transport_gets_default(self):
        p = Platform(name="main", provider="docker")
        ws = Workspace(agents=[self._agent()], platforms=[p])
        # Platform's transport field was filled in with the synthesised default
        assert ws.platforms[0].transport == "default-http"

    def test_workspace_rejects_unknown_transport_ref(self):
        p = Platform(name="main", provider="docker", transport="nonexistent")
        with pytest.raises(ValidationError, match="transport 'nonexistent'"):
            Workspace(agents=[self._agent()], platforms=[p])
```

- [ ] **Step 2: Run tests to see them fail**

```bash
uv run pytest packages/python/vystak/tests/schema/test_transport_schema.py -v
```

Expected: new tests FAIL with AttributeError or ValidationError (field doesn't exist yet).

- [ ] **Step 3: Add `transport` field to `Platform`**

In `packages/python/vystak/src/vystak/schema/platform.py`, add a new field alongside the existing fields. Locate the `class Platform(BaseModel):` declaration and add:

```python
    transport: str | None = None
```

Position it after `provider` and before any `services` or `channels` fields to preserve logical grouping. Place above any existing `model_config`.

- [ ] **Step 4: Add `transports` list + synthesize/validate in `Workspace`**

Open `packages/python/vystak/src/vystak/schema/workspace.py`. Add import:

```python
from vystak.schema.transport import Transport
```

In the `class Workspace(BaseModel):` body, add the new field next to `agents`, `channels`, `services`:

```python
    transports: list[Transport] = Field(default_factory=list)
```

Then add a model validator that runs *after* base validation. Import `model_validator` if not already imported. Add:

```python
    @model_validator(mode="after")
    def _synthesize_and_validate_transports(self) -> "Workspace":
        # Synthesize a default HTTP transport if none declared.
        if not self.transports:
            self.transports = [Transport(name="default-http", type="http")]

        transport_names = {t.name for t in self.transports}

        # Default any platform without an explicit transport to the first one.
        # If multiple transports exist and a platform has no transport set,
        # require the user to be explicit.
        default_name = (
            "default-http"
            if "default-http" in transport_names and len(transport_names) == 1
            else None
        )

        for platform in self.platforms:
            if platform.transport is None:
                if default_name is None:
                    raise ValueError(
                        f"platform '{platform.name}' has no transport set and "
                        f"multiple transports are declared ({sorted(transport_names)}); "
                        f"set Platform.transport explicitly"
                    )
                platform.transport = default_name
            elif platform.transport not in transport_names:
                raise ValueError(
                    f"platform '{platform.name}' references transport "
                    f"'{platform.transport}' which is not declared in "
                    f"Workspace.transports (have: {sorted(transport_names)})"
                )
        return self
```

- [ ] **Step 5: Run tests and verify they pass**

```bash
uv run pytest packages/python/vystak/tests/schema/test_transport_schema.py -v
```

Expected: all tests PASS (old + new).

- [ ] **Step 6: Run full test suite to check for regressions**

```bash
just test-python && just lint-python
```

Expected: PASS. If pre-existing `Workspace` tests break because they now get a default-http transport, inspect the failing test — it probably asserts `len(ws.transports) == 0`, which should be updated to acknowledge the synthesized default. Fix only the assertion; do not change test intent.

- [ ] **Step 7: Commit**

```bash
git add packages/python/vystak/src/vystak/schema/platform.py \
        packages/python/vystak/src/vystak/schema/workspace.py \
        packages/python/vystak/tests/schema/test_transport_schema.py
git commit -m "feat(schema): wire Transport into Platform and Workspace

Adds Platform.transport (name ref) and Workspace.transports (list). If no
transport is declared, Workspace synthesises a 'default-http' transport
and assigns it to every platform. Referencing an unknown transport fails
validation."
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

### Task 17: Docker provider wires `TransportPlugin`

**Files:**
- Modify: `packages/python/vystak-provider-docker/src/vystak_provider_docker/provider.py`
- Modify: provider tests

- [ ] **Step 1: Add a transport-plugin registry to the provider**

In `provider.py`, at module scope, add:

```python
from vystak_transport_http import HttpTransportPlugin

_TRANSPORT_PLUGINS: dict[str, type] = {
    "http": HttpTransportPlugin,
}
```

Plan B adds `"nats"` to this dict.

- [ ] **Step 2: Resolve `transport_plugin` in `apply()`**

Find the method in `DockerProvider` that iterates the workspace's agents, channels, and services to build the `ProvisionGraph`. Before building agent and channel nodes, resolve the transport:

```python
transport = next(
    t for t in workspace.transports
    if t.name == platform.transport
)
plugin_cls = _TRANSPORT_PLUGINS[transport.type]
transport_plugin = plugin_cls()

# Broker provisioning nodes (empty list for http):
for node in transport_plugin.build_provision_nodes(transport, platform):
    graph.add(node)

# Env contract for agents/channels:
transport_env = transport_plugin.generate_env_contract(transport, context={})
```

- [ ] **Step 3: Thread `transport_env` into agent and channel container envs**

Every agent and channel container node must receive `transport_env` merged into its `environment` map. Also inject `VYSTAK_ROUTES_JSON` (computed from the workspace's agents + transport's resolve_address for the channel's allowed peers).

Concretely, after constructing each agent / channel container node's environment dict, merge:

```python
environment = {
    **transport_env,
    "VYSTAK_ROUTES_JSON": _build_routes_json(workspace, transport),
    # ... existing keys ...
}
```

Add a `_build_routes_json` helper on the provider (or in a new `docker_provider/routes.py`) that loops through agents and produces:

```python
{
    agent.name: {
        "canonical": agent.canonical_name,
        "address": transport_plugin_impl.resolve_address_for(agent, platform),
    }
    for agent in workspace.agents
}
```

Where `resolve_address_for` lives on the transport plugin and returns the Docker DNS URL for HTTP (`http://{slug(name)}-{slug(ns)}:8000/a2a`). For clean separation, add an **optional** method to `HttpTransportPlugin`:

```python
def resolve_address_for(self, agent: Agent, platform: Platform) -> str:
    from vystak.transport.naming import slug
    ns = slug(agent.namespace or "default")
    return f"http://{slug(agent.name)}-{ns}:{agent.port or 8000}/a2a"
```

- [ ] **Step 4: Update docker-provider tests**

```bash
grep -rn "environment" packages/python/vystak-provider-docker/tests/ | head -30
uv run pytest packages/python/vystak-provider-docker/tests/ -v
```

Expect failures around environment shapes; update assertions to expect `VYSTAK_TRANSPORT_TYPE=http` and a well-formed `VYSTAK_ROUTES_JSON` in each agent container's env.

- [ ] **Step 5: Run full suite**

```bash
just lint-python && just test-python
```

- [ ] **Step 6: Commit**

```bash
git add packages/python/vystak-provider-docker/
git commit -m "feat(provider-docker): wire TransportPlugin through apply()

DockerProvider now resolves the platform's transport to a TransportPlugin,
adds any provision nodes the plugin requires, and injects VYSTAK_TRANSPORT_*
env vars + VYSTAK_ROUTES_JSON (canonical-name-keyed) into every agent and
channel container. HTTP path preserves current Docker DNS behaviour."
```

---

### Task 18: Azure provider wires `TransportPlugin`

**Files:**
- Modify: `packages/python/vystak-provider-azure/src/vystak_provider_azure/provider.py`
- Modify: provider tests

Follow the exact same pattern as Task 17:

- [ ] **Step 1: Same transport-plugin registry.**
- [ ] **Step 2: Resolve `transport_plugin` in `apply()`.**
- [ ] **Step 3: Merge `transport_env` into every container app's environment; inject `VYSTAK_ROUTES_JSON`.**
- [ ] **Step 4: For HTTP, emit the ACA FQDN pattern for each agent's address: `https://{slug(name)}-{slug(ns)}.{region}.azurecontainerapps.io/a2a`.** Add this to `HttpTransportPlugin.resolve_address_for` — or better, accept the FQDN from the `ContainerAppNode`'s output and look it up post-provision. For this plan, add a `platform_region` kwarg to `resolve_address_for` and derive from `platform.region` on Azure.
- [ ] **Step 5: Run azure-provider tests.**
- [ ] **Step 6: Commit.**

```bash
git add packages/python/vystak-provider-azure/
git commit -m "feat(provider-azure): wire TransportPlugin through apply()

Azure provider adopts the same TransportPlugin resolution as the Docker
provider. For HTTP transport, container app FQDNs are emitted into the
VYSTAK_ROUTES_JSON address map using existing ACA naming conventions."
```

---

### Task 19: Hash tree integration

**Files:**
- Modify: `packages/python/vystak/src/vystak/hash/tree.py`
- Modify: `packages/python/vystak/tests/hash/test_tree.py`

- [ ] **Step 1: Write failing tests for hash sensitivity**

Add to (or create) `packages/python/vystak/tests/hash/test_tree.py`:

```python
from vystak.hash.tree import AgentHashTree
from vystak.schema import (
    Agent, Model, Provider, Platform, Transport, NatsConfig, Workspace,
)


def _ws(transport: Transport | None = None) -> Workspace:
    agent = Agent(
        name="a",
        model=Model(name="m", provider=Provider(type="anthropic", api_key_env="K")),
    )
    platform = Platform(name="main", provider="docker", transport=transport.name if transport else None)
    transports = [transport] if transport else []
    return Workspace(agents=[agent], platforms=[platform], transports=transports)


def test_hash_changes_when_transport_type_changes():
    ws1 = _ws(Transport(name="bus", type="http"))
    ws2 = _ws(Transport(name="bus", type="nats", config=NatsConfig()))
    h1 = AgentHashTree.for_workspace(ws1).hash_for(ws1.agents[0])
    h2 = AgentHashTree.for_workspace(ws2).hash_for(ws2.agents[0])
    assert h1 != h2


def test_hash_unchanged_for_byo_connection():
    ws1 = _ws(Transport(name="bus", type="nats", config=NatsConfig()))
    # Same transport, different BYO connection — should not trigger re-deploy.
    t2 = Transport(
        name="bus", type="nats", config=NatsConfig(),
        connection={"url_env": "OTHER_URL"},
    )
    ws2 = _ws(t2)
    h1 = AgentHashTree.for_workspace(ws1).hash_for(ws1.agents[0])
    h2 = AgentHashTree.for_workspace(ws2).hash_for(ws2.agents[0])
    assert h1 == h2


def test_default_http_platform_without_transport_consistent():
    # Two platforms identical but one omits transport — after synthesis,
    # hash should match.
    ws1 = _ws()  # no transport declared, synthesises default-http
    ws2 = _ws(Transport(name="default-http", type="http"))
    h1 = AgentHashTree.for_workspace(ws1).hash_for(ws1.agents[0])
    h2 = AgentHashTree.for_workspace(ws2).hash_for(ws2.agents[0])
    assert h1 == h2
```

- [ ] **Step 2: Run — expect failures**

```bash
uv run pytest packages/python/vystak/tests/hash/ -v
```

Expected: `test_hash_changes_when_transport_type_changes` FAILS because transport doesn't contribute to the hash yet.

- [ ] **Step 3: Extend `AgentHashTree.for_workspace`**

Open `packages/python/vystak/src/vystak/hash/tree.py`. Find where agent hashing composes inputs. Add transport contribution:

```python
# For each agent:
platform = _platform_for_agent(workspace, agent)
transport = next(t for t in workspace.transports if t.name == platform.transport)
transport_hash_input = {
    "type": transport.type,
    "config": (transport.config.model_dump() if transport.config else None),
    # Deliberately exclude `connection` — BYO endpoint changes are portable.
}
```

Merge `transport_hash_input` into the existing hash-input dict for the agent. Use `json.dumps(..., sort_keys=True)` to get deterministic ordering.

- [ ] **Step 4: Run tests**

```bash
uv run pytest packages/python/vystak/tests/hash/ -v
```

Expected: PASS.

- [ ] **Step 5: Run full suite**

```bash
just lint-python && just test-python
```

Expected: PASS. (Some existing hash-sensitivity tests may also be affected; update only their comparison constants, not their semantics.)

- [ ] **Step 6: Commit**

```bash
git add packages/python/vystak/src/vystak/hash/tree.py \
        packages/python/vystak/tests/hash/
git commit -m "feat(hash): include transport type/config in AgentHashTree

Switching a platform's transport type or broker-specific config triggers
re-deploy. BYO connection URL/credentials are excluded from the hash —
same agent, different broker instance, should be portable."
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
