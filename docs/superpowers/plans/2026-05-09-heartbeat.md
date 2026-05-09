# Heartbeat Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an opt-in `heartbeat` field on `Agent` that lets a channel runtime fire periodic synthetic turns on a cron schedule, evaluate the reply against `HEARTBEAT_OK`, and either deliver the alert into a configured target thread or stay silent.

**Architecture:** New `Heartbeat` Pydantic model on `Agent`. The channel runtime (already owns A2A delivery + thread bindings) hosts a per-agent `HeartbeatScheduler` for any routed agent whose heartbeat targets the runtime's channel. Each fire produces a *session event* (with synthetic scope/thread when `isolated_session=True`) for the agent call, then a *delivery event* (real scope/thread) handed to subclass `post_reply` only if the reply isn't `HEARTBEAT_OK`.

**Tech Stack:** Python 3.11+, Pydantic v2, `croniter`, asyncio, pytest, freezegun. Touched packages: `vystak`, `vystak-channel-runtime`, `vystak-provider-docker` (release test only).

**Spec:** [`docs/superpowers/specs/2026-05-09-heartbeat-design.md`](../specs/2026-05-09-heartbeat-design.md)

---

## File map

| Action | Path | Purpose |
|---|---|---|
| Create | `packages/python/vystak/src/vystak/schema/heartbeat.py` | `Heartbeat` Pydantic model + cron validator |
| Modify | `packages/python/vystak/src/vystak/schema/agent.py` | Add `heartbeat: Heartbeat \| None = None` field |
| Modify | `packages/python/vystak/src/vystak/schema/__init__.py` | Export `Heartbeat` |
| Modify | `packages/python/vystak/src/vystak/hash/tree.py` | Add `heartbeat` to `AgentHashTree` and `hash_agent` |
| Modify | `packages/python/vystak/src/vystak/schema/multi_loader.py` | Add `_validate_heartbeat_targets` cross-check |
| Modify | `packages/python/vystak/pyproject.toml` | Add `croniter` dependency |
| Create | `packages/python/vystak/tests/test_heartbeat_schema.py` | Schema + cron validator tests |
| Modify | `packages/python/vystak/tests/test_hash_tree_secrets.py` | Add heartbeat hash test (or new file) |
| Modify | `packages/python/vystak/tests/test_examples.py` | Cover heartbeat example loads |
| Create | `packages/python/vystak-channel-runtime/src/vystak_channel_runtime/heartbeat.py` | `HeartbeatScheduler` + `is_heartbeat_ok` + `DEFAULT_PROMPT` |
| Modify | `packages/python/vystak-channel-runtime/src/vystak_channel_runtime/runtime.py` | Wire schedulers into `start`/`stop`; ack stripping + delivery event in `handle_event` |
| Modify | `packages/python/vystak-channel-runtime/src/vystak_channel_runtime/store.py` | Add `last_binding_for_agent` to `ChannelStore` protocol + 3 backends |
| Modify | `packages/python/vystak-channel-runtime/pyproject.toml` | Add `croniter` dependency |
| Create | `packages/python/vystak-channel-runtime/tests/test_heartbeat_ack.py` | `is_heartbeat_ok` unit tests |
| Create | `packages/python/vystak-channel-runtime/tests/test_heartbeat_scheduler.py` | `HeartbeatScheduler` unit tests |
| Modify | `packages/python/vystak-channel-runtime/tests/test_runtime.py` | Heartbeat pipeline integration in `ChannelRuntime` |
| Modify | `packages/python/vystak-channel-runtime/tests/test_store.py` | `last_binding_for_agent` tests across backends |
| Create | `examples/heartbeat-agent/vystak.yaml` | Example deployment (YAML form) |
| Create | `examples/heartbeat-agent/vystak.py` | Example deployment (code-first form) |
| Create | `examples/heartbeat-agent/README.md` | Quick start |
| Create | `docs/heartbeat.md` | User-facing documentation |
| Create | `packages/python/vystak-provider-docker/tests/release/test_heartbeat.py` | Release integration cell (`release_integration` marker) |

---

## Task 1: `Heartbeat` schema model

**Files:**
- Modify: `packages/python/vystak/pyproject.toml` (add `croniter` to dependencies)
- Create: `packages/python/vystak/src/vystak/schema/heartbeat.py`
- Create: `packages/python/vystak/tests/test_heartbeat_schema.py`

- [ ] **Step 1: Add `croniter` dependency**

Edit `packages/python/vystak/pyproject.toml`. Find the `dependencies` block (around line 30) and add `croniter`:

```toml
dependencies = [
    "pydantic>=2.0",
    "pyyaml>=6.0",
    "aiosqlite>=0.20",
    "croniter>=2.0",
]
```

Run: `uv sync`
Expected: completes without errors, `croniter` shows in resolved set.

- [ ] **Step 2: Write failing tests for `Heartbeat`**

Create `packages/python/vystak/tests/test_heartbeat_schema.py`:

```python
"""Schema-level tests for the Heartbeat model."""

import pytest
from pydantic import ValidationError

from vystak.schema.heartbeat import Heartbeat


def test_minimal_heartbeat_round_trips():
    hb = Heartbeat(
        schedule="*/30 * * * *",
        target_channel="slack-main.channels.dev",
    )
    assert hb.schedule == "*/30 * * * *"
    assert hb.timezone == "UTC"
    assert hb.target_channel == "slack-main.channels.dev"
    assert hb.target_thread is None
    assert hb.prompt is None
    assert hb.isolated_session is True
    assert hb.skip_when_busy is True
    assert hb.ack_max_chars == 300
    assert hb.enabled is True


def test_full_heartbeat_round_trips():
    hb = Heartbeat(
        schedule="0 9 * * 1-5",
        timezone="America/New_York",
        target_channel="slack-main.channels.dev",
        target_thread="C0123456789",
        prompt="Custom prompt",
        isolated_session=False,
        skip_when_busy=False,
        ack_max_chars=500,
        enabled=False,
    )
    dumped = hb.model_dump()
    restored = Heartbeat.model_validate(dumped)
    assert restored == hb


def test_invalid_cron_rejected():
    with pytest.raises(ValidationError) as exc:
        Heartbeat(
            schedule="every 30 minutes",
            target_channel="x.channels.dev",
        )
    assert "invalid cron expression" in str(exc.value)


def test_target_channel_required():
    with pytest.raises(ValidationError):
        Heartbeat(schedule="*/30 * * * *")  # type: ignore[call-arg]


def test_complex_cron_accepted():
    """5-field cron with day-of-week ranges should validate."""
    hb = Heartbeat(
        schedule="*/15 9-22 * * 1-5",
        target_channel="x.channels.dev",
    )
    assert hb.schedule == "*/15 9-22 * * 1-5"
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest packages/python/vystak/tests/test_heartbeat_schema.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'vystak.schema.heartbeat'`.

- [ ] **Step 4: Implement `Heartbeat`**

Create `packages/python/vystak/src/vystak/schema/heartbeat.py`:

```python
"""Heartbeat model — periodic agent self-invocation configuration.

See docs/superpowers/specs/2026-05-09-heartbeat-design.md for the design
rationale. The heartbeat is declared on the Agent; the channel named in
`target_channel` hosts the scheduler at runtime.
"""

from __future__ import annotations

from croniter import croniter
from pydantic import BaseModel, Field, field_validator


class Heartbeat(BaseModel):
    """Periodic agent self-invocation, fired by the channel named in
    `target_channel`."""

    schedule: str = Field(
        ...,
        description="5-field cron expression, e.g. '*/30 * * * *'.",
    )
    timezone: str = Field(
        "UTC",
        description="IANA timezone name for cron evaluation.",
    )
    target_channel: str = Field(
        ...,
        description="Channel canonical_name (e.g. 'slack-main.channels.dev').",
    )
    target_thread: str | None = Field(
        None,
        description=(
            "Specific delivery thread/scope id. If None, the channel runtime "
            "resolves at fire time from the most recent ThreadBinding for "
            "this agent."
        ),
    )
    prompt: str | None = Field(
        None,
        description=(
            "Override the built-in heartbeat prompt. None uses the default."
        ),
    )
    isolated_session: bool = Field(
        True,
        description=(
            "When True, the fire uses a synthetic scope/thread so it doesn't "
            "pollute the user-visible session history."
        ),
    )
    skip_when_busy: bool = Field(
        True,
        description=(
            "Skip a fire if a previous heartbeat is still in flight. Does "
            "not coordinate with concurrent user turns."
        ),
    )
    ack_max_chars: int = Field(
        300,
        description=(
            "Maximum reply length to scan for HEARTBEAT_OK. Replies longer "
            "than this are always delivered."
        ),
    )
    enabled: bool = Field(
        True,
        description="Set False to keep config but disable scheduling.",
    )

    @field_validator("schedule")
    @classmethod
    def _validate_cron(cls, v: str) -> str:
        if not croniter.is_valid(v):
            raise ValueError(f"invalid cron expression: {v!r}")
        return v
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest packages/python/vystak/tests/test_heartbeat_schema.py -v`
Expected: 5 passed.

- [ ] **Step 6: Commit**

```bash
git add packages/python/vystak/pyproject.toml \
        packages/python/vystak/src/vystak/schema/heartbeat.py \
        packages/python/vystak/tests/test_heartbeat_schema.py
git commit -m "feat(schema): add Heartbeat model with cron validator"
```

---

## Task 2: Wire `Heartbeat` into `Agent`

**Files:**
- Modify: `packages/python/vystak/src/vystak/schema/agent.py`
- Modify: `packages/python/vystak/src/vystak/schema/__init__.py`
- Modify: `packages/python/vystak/tests/test_heartbeat_schema.py` (add agent-level tests)

- [ ] **Step 1: Write failing tests for `Agent.heartbeat`**

Append to `packages/python/vystak/tests/test_heartbeat_schema.py`:

```python
from vystak.schema import Agent, Heartbeat, Model, Provider


def _model() -> Model:
    return Model(
        name="claude",
        provider=Provider(name="anthropic", type="anthropic"),
        model_name="claude-sonnet-4-6",
    )


def test_agent_without_heartbeat_default_none():
    agent = Agent(name="bot", model=_model())
    assert agent.heartbeat is None


def test_agent_with_heartbeat_round_trips():
    agent = Agent(
        name="bot",
        model=_model(),
        heartbeat=Heartbeat(
            schedule="*/5 * * * *",
            target_channel="x.channels.dev",
        ),
    )
    dumped = agent.model_dump()
    restored = Agent.model_validate(dumped)
    assert restored.heartbeat is not None
    assert restored.heartbeat.schedule == "*/5 * * * *"


def test_heartbeat_exported_from_schema():
    """Importable from the top-level schema package."""
    from vystak.schema import Heartbeat as Exported

    assert Exported is Heartbeat
```

- [ ] **Step 2: Run tests to verify failure**

Run: `uv run pytest packages/python/vystak/tests/test_heartbeat_schema.py -v`
Expected: 3 new tests fail — `Agent` has no `heartbeat` field, import fails.

- [ ] **Step 3: Add `heartbeat` field to `Agent`**

Edit `packages/python/vystak/src/vystak/schema/agent.py`. Add the import and the field:

At the imports block (after `from vystak.schema.compaction import Compaction`):

```python
from vystak.schema.heartbeat import Heartbeat
```

Inside the `Agent` class, alongside `compaction: Compaction | None = None`, add:

```python
    heartbeat: Heartbeat | None = None
```

- [ ] **Step 4: Export `Heartbeat`**

Edit `packages/python/vystak/src/vystak/schema/__init__.py`:

After `from vystak.schema.compaction import Compaction`, add:

```python
from vystak.schema.heartbeat import Heartbeat
```

In the `__all__` list, insert `"Heartbeat",` (alphabetical position after `"EnvironmentOverride"`).

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest packages/python/vystak/tests/test_heartbeat_schema.py -v`
Expected: 8 passed (5 original + 3 new).

- [ ] **Step 6: Commit**

```bash
git add packages/python/vystak/src/vystak/schema/agent.py \
        packages/python/vystak/src/vystak/schema/__init__.py \
        packages/python/vystak/tests/test_heartbeat_schema.py
git commit -m "feat(schema): expose heartbeat on Agent"
```

---

## Task 3: Hash-tree contribution

**Files:**
- Modify: `packages/python/vystak/src/vystak/hash/tree.py`
- Create: `packages/python/vystak/tests/hash/test_heartbeat_hash.py`

- [ ] **Step 1: Write failing tests for hash propagation**

Create `packages/python/vystak/tests/hash/test_heartbeat_hash.py`:

```python
"""Hash-tree tests verifying heartbeat changes propagate to agent root."""

from vystak.hash.tree import hash_agent
from vystak.schema import Agent, Channel, ChannelType, Heartbeat, Model, Platform, Provider


def _model() -> Model:
    return Model(
        name="claude",
        provider=Provider(name="anthropic", type="anthropic"),
        model_name="claude-sonnet-4-6",
    )


def _platform() -> Platform:
    return Platform(
        name="local",
        type="docker",
        provider=Provider(name="docker", type="docker"),
        namespace="dev",
    )


def test_no_heartbeat_field_present():
    agent = Agent(name="bot", model=_model(), platform=_platform())
    tree = hash_agent(agent)
    assert tree.heartbeat == hash_agent(agent).heartbeat  # deterministic


def test_adding_heartbeat_changes_root():
    agent_no = Agent(name="bot", model=_model(), platform=_platform())
    agent_yes = Agent(
        name="bot",
        model=_model(),
        platform=_platform(),
        heartbeat=Heartbeat(
            schedule="*/30 * * * *",
            target_channel="x.channels.dev",
        ),
    )
    assert hash_agent(agent_no).root != hash_agent(agent_yes).root
    assert hash_agent(agent_no).heartbeat != hash_agent(agent_yes).heartbeat


def test_changing_schedule_changes_root():
    def with_schedule(s: str) -> Agent:
        return Agent(
            name="bot",
            model=_model(),
            platform=_platform(),
            heartbeat=Heartbeat(schedule=s, target_channel="x.channels.dev"),
        )

    h1 = hash_agent(with_schedule("*/30 * * * *"))
    h2 = hash_agent(with_schedule("*/15 * * * *"))
    assert h1.root != h2.root
    assert h1.heartbeat != h2.heartbeat


def test_toggling_enabled_changes_root():
    def with_enabled(e: bool) -> Agent:
        return Agent(
            name="bot",
            model=_model(),
            platform=_platform(),
            heartbeat=Heartbeat(
                schedule="*/30 * * * *",
                target_channel="x.channels.dev",
                enabled=e,
            ),
        )

    assert hash_agent(with_enabled(True)).root != hash_agent(with_enabled(False)).root


def test_channel_hash_picks_up_routed_agent_heartbeat_change():
    """When a routed agent's heartbeat changes, the channel's hash changes."""
    from vystak.hash.tree import hash_channel

    def channel_with_schedule(s: str) -> Channel:
        agent = Agent(
            name="bot",
            model=_model(),
            platform=_platform(),
            heartbeat=Heartbeat(schedule=s, target_channel="x.channels.dev"),
        )
        return Channel(
            name="x",
            type=ChannelType.CHAT,
            platform=_platform(),
            agents=[agent],
        )

    h1 = hash_channel(channel_with_schedule("*/30 * * * *"))
    h2 = hash_channel(channel_with_schedule("*/15 * * * *"))
    assert h1.root != h2.root
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/python/vystak/tests/hash/test_heartbeat_hash.py -v`
Expected: FAIL — `AgentHashTree` has no `heartbeat` field; tests reference it.

- [ ] **Step 3: Add `heartbeat` to `AgentHashTree` + `hash_agent`**

Edit `packages/python/vystak/src/vystak/hash/tree.py`:

In the `AgentHashTree` dataclass (around line 14), add a new field with a default so it stays backward-compatible at the dataclass level:

```python
@dataclass
class AgentHashTree:
    """Per-section hashes for an agent, enabling partial deploy detection."""

    brain: str
    skills: str
    mcp_servers: str
    workspace: str
    resources: str
    secrets: str
    sessions: str
    memory: str
    services: str
    transport: str
    subagents: str
    workspace_identity: str
    grants: str
    compaction: str
    heartbeat: str = ""        # NEW
    template: str = ""
    root: str = ""
```

Inside `hash_agent` (around line 200), after the existing `compaction = _hash_optional(agent.compaction)` line and before `template = ...`, add:

```python
    heartbeat = _hash_optional(agent.heartbeat)
```

In the `sections = "|".join([...])` list, insert `heartbeat` between `compaction` and `template`:

```python
    sections = "|".join(
        [
            brain,
            framework,
            skills,
            mcp_servers,
            workspace,
            resources,
            secrets,
            sessions,
            memory,
            services,
            transport,
            subagents,
            workspace_identity,
            grants,
            compaction,
            heartbeat,
            template,
        ]
    )
```

In the final `AgentHashTree(...)` construction, add the kwarg:

```python
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
        subagents=subagents,
        workspace_identity=workspace_identity,
        grants=grants,
        compaction=compaction,
        heartbeat=heartbeat,
        template=template,
        root=root,
    )
```

`hash_channel` does **not** need editing — `_hash_list(channel.agents)` already serializes each agent (including its heartbeat field) via `hash_model`, so heartbeat changes on routed agents naturally propagate to the channel root.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/python/vystak/tests/hash/test_heartbeat_hash.py -v`
Expected: 5 passed.

- [ ] **Step 5: Run the full vystak suite to catch regressions**

Run: `uv run pytest packages/python/vystak/ -v`
Expected: all pre-existing tests pass; only the new tests are added.

- [ ] **Step 6: Commit**

```bash
git add packages/python/vystak/src/vystak/hash/tree.py \
        packages/python/vystak/tests/hash/test_heartbeat_hash.py
git commit -m "feat(hash): contribute heartbeat to agent hash tree"
```

---

## Task 4: `is_heartbeat_ok` pure function

**Files:**
- Create: `packages/python/vystak-channel-runtime/src/vystak_channel_runtime/heartbeat.py` (skeleton)
- Create: `packages/python/vystak-channel-runtime/tests/test_heartbeat_ack.py`
- Modify: `packages/python/vystak-channel-runtime/pyproject.toml` (add `croniter`)

- [ ] **Step 1: Add `croniter` dependency**

Edit `packages/python/vystak-channel-runtime/pyproject.toml`. In the `dependencies` block, add `croniter`:

```toml
dependencies = [
    "vystak>=0.1.0",
    "httpx>=0.27",
    "aiosqlite>=0.20",
    "asyncpg>=0.29",
    "pydantic>=2.7",
    "nats-py>=2.6",
    "croniter>=2.0",
    "opentelemetry-api>=1.27",
    "opentelemetry-sdk>=1.27",
    "opentelemetry-exporter-otlp-proto-grpc>=1.27",
    "opentelemetry-instrumentation-fastapi>=0.48b0",
    "opentelemetry-instrumentation-httpx>=0.48b0",
]
```

Run: `uv sync`
Expected: completes without errors.

- [ ] **Step 2: Write failing tests for `is_heartbeat_ok`**

Create `packages/python/vystak-channel-runtime/tests/test_heartbeat_ack.py`:

```python
"""Tests for the heartbeat ack-stripping function."""

import pytest

from vystak_channel_runtime.heartbeat import HEARTBEAT_OK, is_heartbeat_ok


@pytest.mark.parametrize(
    "text",
    [
        "HEARTBEAT_OK",
        "  HEARTBEAT_OK\n",
        "HEARTBEAT_OK\n\n",
        "All good. HEARTBEAT_OK",
        "HEARTBEAT_OK — nothing to report.",
    ],
)
def test_short_replies_with_sentinel_drop(text: str):
    assert is_heartbeat_ok(text, max_chars=300) is True


@pytest.mark.parametrize(
    "text",
    [
        "All clear, nothing to report.",
        "User mentioned X needs review.",
        "HEARTBEATOK",  # missing underscore
        "HEARTBEAT-OK",
    ],
)
def test_replies_without_sentinel_post(text: str):
    assert is_heartbeat_ok(text, max_chars=300) is False


def test_empty_or_whitespace_does_not_drop():
    """Empty replies should NOT silently swallow — they signal a real bug."""
    assert is_heartbeat_ok("", max_chars=300) is False
    assert is_heartbeat_ok("   \n\t  ", max_chars=300) is False


def test_long_reply_with_sentinel_posts():
    """Replies longer than ack_max_chars are always delivered."""
    body = "x" * 400
    text = f"{body} {HEARTBEAT_OK}"
    assert is_heartbeat_ok(text, max_chars=300) is False


def test_exactly_max_chars_with_sentinel_drops():
    text = ("HEARTBEAT_OK " * 10).strip()  # well under 300
    assert is_heartbeat_ok(text, max_chars=300) is True
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest packages/python/vystak-channel-runtime/tests/test_heartbeat_ack.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'vystak_channel_runtime.heartbeat'`.

- [ ] **Step 4: Implement skeleton heartbeat module**

Create `packages/python/vystak-channel-runtime/src/vystak_channel_runtime/heartbeat.py`:

```python
"""Heartbeat scheduler — fires periodic synthetic turns through the runtime
pipeline.

See docs/superpowers/specs/2026-05-09-heartbeat-design.md for design.
"""

from __future__ import annotations

HEARTBEAT_OK = "HEARTBEAT_OK"

DEFAULT_PROMPT = (
    "Read HEARTBEAT.md if it exists in your workspace. Follow it strictly. "
    "If nothing needs attention, reply with only HEARTBEAT_OK. "
    "Otherwise, reply with a short message describing what needs attention "
    "— do not include HEARTBEAT_OK in that case."
)


def is_heartbeat_ok(text: str, max_chars: int) -> bool:
    """Return True iff `text` should be treated as a silent heartbeat ack.

    Rules (matches OpenClaw's behaviour):

    * Whitespace-only / empty text → False (do not silently swallow real bugs).
    * Text longer than `max_chars` → False (always deliver long replies).
    * Otherwise → True iff `HEARTBEAT_OK` appears anywhere in the text.
    """
    stripped = text.strip()
    if not stripped:
        return False
    if len(stripped) > max_chars:
        return False
    return HEARTBEAT_OK in stripped
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest packages/python/vystak-channel-runtime/tests/test_heartbeat_ack.py -v`
Expected: 13 passed (5 short-drop, 4 no-sentinel, 2 empty, 1 long-post, 1 exact-max).

- [ ] **Step 6: Commit**

```bash
git add packages/python/vystak-channel-runtime/pyproject.toml \
        packages/python/vystak-channel-runtime/src/vystak_channel_runtime/heartbeat.py \
        packages/python/vystak-channel-runtime/tests/test_heartbeat_ack.py
git commit -m "feat(channel-runtime): add is_heartbeat_ok ack helper"
```

---

## Task 5: `last_binding_for_agent` store method

**Files:**
- Modify: `packages/python/vystak-channel-runtime/src/vystak_channel_runtime/store.py`
- Modify: `packages/python/vystak-channel-runtime/tests/test_store.py`

- [ ] **Step 1: Write failing tests across all three backends**

Append to `packages/python/vystak-channel-runtime/tests/test_store.py`:

```python
import asyncio
import time

import pytest

from vystak_channel_runtime.store import MemoryChannelStore


@pytest.mark.asyncio
async def test_memory_last_binding_for_agent_empty():
    store = MemoryChannelStore()
    assert await store.last_binding_for_agent("slack", "ops-bot") is None


@pytest.mark.asyncio
async def test_memory_last_binding_for_agent_picks_most_recent():
    store = MemoryChannelStore()
    await store.set_thread_binding("slack", "T1", "thread-old", "ops-bot", user_id="U1")
    # tiny gap so updated_at differs
    await asyncio.sleep(0.01)
    await store.set_thread_binding("slack", "T1", "thread-new", "ops-bot", user_id="U2")
    binding = await store.last_binding_for_agent("slack", "ops-bot")
    assert binding is not None
    assert binding.thread_id == "thread-new"
    assert binding.user_id == "U2"


@pytest.mark.asyncio
async def test_memory_last_binding_for_agent_ignores_other_agents():
    store = MemoryChannelStore()
    await store.set_thread_binding("slack", "T1", "thread-1", "other-bot", user_id="U1")
    assert await store.last_binding_for_agent("slack", "ops-bot") is None


@pytest.mark.asyncio
async def test_memory_last_binding_for_agent_ignores_other_channel_types():
    store = MemoryChannelStore()
    await store.set_thread_binding("discord", "G1", "thread-1", "ops-bot", user_id="U1")
    assert await store.last_binding_for_agent("slack", "ops-bot") is None
```

For SQLite + Postgres backends, mirror the same four tests but parametrized by the existing fixtures in this file (find the existing fixture pattern with `_sqlite_store` / `_pg_store` and follow it). If they don't exist, scope the new tests to `MemoryChannelStore` only — the SQL backends share the protocol and a follow-up commit can add their tests once the API is stable.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/python/vystak-channel-runtime/tests/test_store.py -v -k last_binding_for_agent`
Expected: FAIL — `MemoryChannelStore` has no `last_binding_for_agent` method.

- [ ] **Step 3: Implement on `ChannelStore` protocol + `MemoryChannelStore`**

Edit `packages/python/vystak-channel-runtime/src/vystak_channel_runtime/store.py`.

In the `ChannelStore` Protocol class (after `list_thread_bindings`), add:

```python
    async def last_binding_for_agent(
        self, channel_type: str, agent_name: str
    ) -> ThreadBinding | None: ...
```

In `MemoryChannelStore`, implement:

```python
    async def last_binding_for_agent(
        self, channel_type: str, agent_name: str
    ) -> ThreadBinding | None:
        candidates = [
            (key, row)
            for key, row in self._threads.items()
            if key[0] == channel_type and row["agent_name"] == agent_name
        ]
        if not candidates:
            return None
        candidates.sort(key=lambda item: item[1]["updated_at"], reverse=True)
        (ct, scope_id, thread_id), row = candidates[0]
        return ThreadBinding(
            channel_type=ct,
            scope_id=scope_id,
            thread_id=thread_id,
            agent_name=row["agent_name"],
            user_id=row["user_id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
```

In the SQLite backend (find the `class SqliteChannelStore` definition in the same file), add:

```python
    async def last_binding_for_agent(
        self, channel_type: str, agent_name: str
    ) -> ThreadBinding | None:
        async with aiosqlite.connect(self._path) as db:
            db.row_factory = aiosqlite.Row
            row = await (await db.execute(
                """
                SELECT channel_type, scope_id, thread_id, agent_name, user_id,
                       created_at, updated_at
                FROM thread_bindings
                WHERE channel_type = ? AND agent_name = ?
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (channel_type, agent_name),
            )).fetchone()
            return _row_to_binding(row) if row else None
```

In the Postgres backend (`class PostgresChannelStore`), add:

```python
    async def last_binding_for_agent(
        self, channel_type: str, agent_name: str
    ) -> ThreadBinding | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT channel_type, scope_id, thread_id, agent_name, user_id,
                       created_at, updated_at
                FROM thread_bindings
                WHERE channel_type = $1 AND agent_name = $2
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                channel_type, agent_name,
            )
            return _row_to_binding(row) if row else None
```

If `_row_to_binding` does not already exist in the file, find the analogous helper used by `list_thread_bindings` and reuse it (or replicate its body inline).

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/python/vystak-channel-runtime/tests/test_store.py -v -k last_binding_for_agent`
Expected: 4 passed (Memory backend at minimum).

- [ ] **Step 5: Run full store test suite to catch regressions**

Run: `uv run pytest packages/python/vystak-channel-runtime/tests/test_store.py -v`
Expected: all previously-passing tests still pass.

- [ ] **Step 6: Commit**

```bash
git add packages/python/vystak-channel-runtime/src/vystak_channel_runtime/store.py \
        packages/python/vystak-channel-runtime/tests/test_store.py
git commit -m "feat(channel-runtime): add last_binding_for_agent to ChannelStore"
```

---

## Task 6: `HeartbeatScheduler` skeleton + thread resolution

**Files:**
- Modify: `packages/python/vystak-channel-runtime/src/vystak_channel_runtime/heartbeat.py`
- Create: `packages/python/vystak-channel-runtime/tests/test_heartbeat_scheduler.py`

- [ ] **Step 1: Write failing tests for skeleton + thread resolution**

Create `packages/python/vystak-channel-runtime/tests/test_heartbeat_scheduler.py`:

```python
"""Unit tests for HeartbeatScheduler — thread resolution + lifecycle hooks.

Cron-loop tests live in this file too, gated on freezegun availability.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from vystak.schema.heartbeat import Heartbeat
from vystak_channel_runtime.heartbeat import HeartbeatScheduler
from vystak_channel_runtime.types import ThreadBinding


def _hb(**overrides) -> Heartbeat:
    base = {
        "schedule": "*/30 * * * *",
        "target_channel": "x.channels.dev",
    }
    base.update(overrides)
    return Heartbeat(**base)


def _runtime() -> MagicMock:
    rt = MagicMock()
    rt.channel_type = "slack"
    rt.handle_event = AsyncMock()
    rt.store = MagicMock()
    rt.store.last_binding_for_agent = AsyncMock(return_value=None)
    return rt


@pytest.mark.asyncio
async def test_scheduler_with_pinned_thread_uses_it():
    rt = _runtime()
    sch = HeartbeatScheduler(rt, "ops-bot", _hb(target_thread="C123"))
    resolved = await sch._resolve_thread()
    assert resolved == "C123"
    rt.store.last_binding_for_agent.assert_not_called()


@pytest.mark.asyncio
async def test_scheduler_without_pinned_thread_consults_store():
    rt = _runtime()
    rt.store.last_binding_for_agent = AsyncMock(
        return_value=ThreadBinding(
            channel_type="slack",
            scope_id="T1",
            thread_id="thread-X",
            agent_name="ops-bot",
        ),
    )
    sch = HeartbeatScheduler(rt, "ops-bot", _hb())
    resolved = await sch._resolve_thread()
    assert resolved == "thread-X"
    rt.store.last_binding_for_agent.assert_awaited_once_with("slack", "ops-bot")


@pytest.mark.asyncio
async def test_scheduler_without_thread_and_empty_store_returns_none():
    rt = _runtime()
    sch = HeartbeatScheduler(rt, "ops-bot", _hb())
    assert await sch._resolve_thread() is None


@pytest.mark.asyncio
async def test_disabled_scheduler_does_not_start_task():
    rt = _runtime()
    sch = HeartbeatScheduler(rt, "ops-bot", _hb(enabled=False))
    await sch.start()
    assert sch._task is None
    await sch.stop()  # should be a no-op


@pytest.mark.asyncio
async def test_stop_cancels_running_task():
    import asyncio

    rt = _runtime()
    sch = HeartbeatScheduler(rt, "ops-bot", _hb(schedule="* * * * *"))
    await sch.start()
    assert sch._task is not None
    # Give the loop one tick.
    await asyncio.sleep(0)
    await sch.stop()
    assert sch._task.done()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/python/vystak-channel-runtime/tests/test_heartbeat_scheduler.py -v`
Expected: FAIL — `ImportError: cannot import name 'HeartbeatScheduler'`.

- [ ] **Step 3: Implement skeleton**

Edit `packages/python/vystak-channel-runtime/src/vystak_channel_runtime/heartbeat.py`. Append:

```python
import asyncio
import logging
import secrets
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from croniter import croniter

from vystak.schema.heartbeat import Heartbeat
from vystak_channel_runtime.types import InboundEvent

logger = logging.getLogger("vystak.channel.runtime.heartbeat")


class HeartbeatScheduler:
    """Per-(channel, agent) scheduler. Owned by ChannelRuntime."""

    def __init__(self, runtime, agent_name: str, config: Heartbeat) -> None:
        self.runtime = runtime
        self.agent_name = agent_name
        self.config = config
        self._task: asyncio.Task | None = None
        self._busy: bool = False

    async def start(self) -> None:
        if not self.config.enabled:
            return
        self._task = asyncio.create_task(
            self._run(), name=f"hb-{self.agent_name}",
        )

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass

    async def _resolve_thread(self) -> str | None:
        if self.config.target_thread:
            return self.config.target_thread
        binding = await self.runtime.store.last_binding_for_agent(
            self.runtime.channel_type, self.agent_name,
        )
        return binding.thread_id if binding else None

    async def _run(self) -> None:
        # Implemented in Task 7.
        raise NotImplementedError
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/python/vystak-channel-runtime/tests/test_heartbeat_scheduler.py -v`
Expected: 5 passed.

The `test_stop_cancels_running_task` test passes because the unimplemented `_run` raises immediately and the task is `done()` after `await asyncio.sleep(0)`. (The cron loop gets implemented in Task 7.)

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-channel-runtime/src/vystak_channel_runtime/heartbeat.py \
        packages/python/vystak-channel-runtime/tests/test_heartbeat_scheduler.py
git commit -m "feat(channel-runtime): HeartbeatScheduler skeleton + thread resolution"
```

---

## Task 7: Cron loop + fire logic

**Files:**
- Modify: `packages/python/vystak-channel-runtime/src/vystak_channel_runtime/heartbeat.py`
- Modify: `packages/python/vystak-channel-runtime/tests/test_heartbeat_scheduler.py`

- [ ] **Step 1: Write failing tests for `_fire`**

Append to `packages/python/vystak-channel-runtime/tests/test_heartbeat_scheduler.py`:

```python
@pytest.mark.asyncio
async def test_fire_with_no_thread_skips_silently():
    rt = _runtime()
    sch = HeartbeatScheduler(rt, "ops-bot", _hb())
    await sch._fire()
    rt.handle_event.assert_not_called()


@pytest.mark.asyncio
async def test_fire_with_pinned_thread_dispatches_event():
    rt = _runtime()
    sch = HeartbeatScheduler(rt, "ops-bot", _hb(target_thread="C123"))
    await sch._fire()
    rt.handle_event.assert_awaited_once()
    raw = rt.handle_event.await_args.args[0]
    assert raw.user_id == "__heartbeat__"
    assert raw.metadata["heartbeat"] is True
    assert raw.metadata["deliver_thread"] == "C123"
    assert raw.metadata["ack_max_chars"] == 300


@pytest.mark.asyncio
async def test_fire_isolated_session_uses_synthetic_thread():
    rt = _runtime()
    sch = HeartbeatScheduler(
        rt, "ops-bot", _hb(target_thread="C123", isolated_session=True),
    )
    await sch._fire()
    raw = rt.handle_event.await_args.args[0]
    assert raw.thread_id is not None
    assert raw.thread_id.startswith("__heartbeat__")
    assert raw.scope_id.startswith("__heartbeat__")


@pytest.mark.asyncio
async def test_fire_non_isolated_uses_real_thread():
    rt = _runtime()
    sch = HeartbeatScheduler(
        rt, "ops-bot", _hb(target_thread="C123", isolated_session=False),
    )
    await sch._fire()
    raw = rt.handle_event.await_args.args[0]
    assert raw.thread_id == "C123"
    assert raw.scope_id == "C123"


@pytest.mark.asyncio
async def test_fire_uses_default_prompt_when_unset():
    from vystak_channel_runtime.heartbeat import DEFAULT_PROMPT

    rt = _runtime()
    sch = HeartbeatScheduler(rt, "ops-bot", _hb(target_thread="C123"))
    await sch._fire()
    raw = rt.handle_event.await_args.args[0]
    assert raw.text == DEFAULT_PROMPT


@pytest.mark.asyncio
async def test_fire_uses_custom_prompt_when_set():
    rt = _runtime()
    sch = HeartbeatScheduler(
        rt, "ops-bot", _hb(target_thread="C123", prompt="Custom prompt"),
    )
    await sch._fire()
    raw = rt.handle_event.await_args.args[0]
    assert raw.text == "Custom prompt"


@pytest.mark.asyncio
async def test_skip_when_busy_drops_overlapping_fire():
    """If a previous fire is still running, skip the next one."""
    rt = _runtime()
    sch = HeartbeatScheduler(rt, "ops-bot", _hb(target_thread="C123"))
    sch._busy = True  # simulate in-flight previous fire
    await sch._fire()
    rt.handle_event.assert_not_called()


@pytest.mark.asyncio
async def test_busy_flag_resets_after_handle_event_raises():
    """Exception in handle_event must not leave _busy stuck."""
    rt = _runtime()
    rt.handle_event = AsyncMock(side_effect=RuntimeError("boom"))
    sch = HeartbeatScheduler(rt, "ops-bot", _hb(target_thread="C123"))
    with pytest.raises(RuntimeError):
        await sch._fire()
    assert sch._busy is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/python/vystak-channel-runtime/tests/test_heartbeat_scheduler.py -v -k fire`
Expected: FAIL — no `_fire` method.

- [ ] **Step 3: Implement `_fire` and `_run`**

Replace the `_run` stub in `packages/python/vystak-channel-runtime/src/vystak_channel_runtime/heartbeat.py` with the full cron loop, and add `_fire`:

```python
    async def _fire(self) -> None:
        if self.config.skip_when_busy and self._busy:
            logger.info(
                "heartbeat.skipped agent=%s reason=busy", self.agent_name,
            )
            return
        thread_id = await self._resolve_thread()
        if thread_id is None:
            logger.debug(
                "heartbeat.skipped agent=%s reason=no-thread", self.agent_name,
            )
            return

        if self.config.isolated_session:
            synthetic = (
                f"__heartbeat__{int(time.time())}_{secrets.token_hex(4)}"
            )
            session_scope = synthetic
            session_thread = synthetic
        else:
            session_scope = thread_id
            session_thread = thread_id

        event = InboundEvent(
            channel_type=self.runtime.channel_type,
            scope_id=session_scope,
            thread_id=session_thread,
            user_id="__heartbeat__",
            text=self.config.prompt or DEFAULT_PROMPT,
            is_dm=False,
            mentions_bot=True,
            metadata={
                "heartbeat": True,
                "ack_max_chars": self.config.ack_max_chars,
                "deliver_scope": thread_id,
                "deliver_thread": thread_id,
            },
        )

        self._busy = True
        try:
            logger.info(
                "heartbeat.fired agent=%s thread=%s",
                self.agent_name, thread_id,
            )
            # Pass `event` directly — runtime.handle_event accepts an
            # already-parsed InboundEvent OR a raw payload via parse_event.
            # Subclasses' parse_event is bypassed for synthesized events; we
            # call into the pipeline at the post-parse boundary instead.
            await self.runtime._handle_synthetic_event(event)
        finally:
            self._busy = False

    async def _run(self) -> None:
        try:
            tz = ZoneInfo(self.config.timezone)
        except Exception:
            logger.exception(
                "heartbeat invalid timezone=%s — disabling scheduler %s",
                self.config.timezone, self.agent_name,
            )
            return
        cron = croniter(self.config.schedule, datetime.now(tz))
        while True:
            try:
                next_at = cron.get_next(datetime)
            except Exception:
                logger.exception(
                    "heartbeat cron error agent=%s — sleeping 60s",
                    self.agent_name,
                )
                await asyncio.sleep(60)
                continue
            delay = max(0.0, (next_at - datetime.now(tz)).total_seconds())
            try:
                await asyncio.sleep(delay)
            except asyncio.CancelledError:
                raise
            try:
                await self._fire()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "heartbeat.fired_failed agent=%s", self.agent_name,
                )
```

Note the `_handle_synthetic_event` call — that hook gets added to `ChannelRuntime` in Task 9. For now, the scheduler tests stub this via `MagicMock`, which `auto-creates` the attribute on access; the integration wiring happens later.

Update the existing skeleton tests' `_runtime()` helper to also provide this attribute:

```python
def _runtime() -> MagicMock:
    rt = MagicMock()
    rt.channel_type = "slack"
    rt._handle_synthetic_event = AsyncMock()
    rt.store = MagicMock()
    rt.store.last_binding_for_agent = AsyncMock(return_value=None)
    return rt
```

And in the new `test_fire_*` tests above, replace `rt.handle_event` references with `rt._handle_synthetic_event`. Also, `test_busy_flag_resets_after_handle_event_raises` should set `rt._handle_synthetic_event = AsyncMock(side_effect=RuntimeError("boom"))`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/python/vystak-channel-runtime/tests/test_heartbeat_scheduler.py -v`
Expected: all 13 tests pass (5 from Task 6 + 8 new).

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-channel-runtime/src/vystak_channel_runtime/heartbeat.py \
        packages/python/vystak-channel-runtime/tests/test_heartbeat_scheduler.py
git commit -m "feat(channel-runtime): heartbeat cron loop + fire dispatch"
```

---

## Task 8: Wire schedulers into `ChannelRuntime`

**Files:**
- Modify: `packages/python/vystak-channel-runtime/src/vystak_channel_runtime/runtime.py`
- Modify: `packages/python/vystak-channel-runtime/tests/test_runtime.py`

- [ ] **Step 1: Write failing tests for runtime wiring**

Append to `packages/python/vystak-channel-runtime/tests/test_runtime.py` (find the existing `class FakeRuntime(ChannelRuntime):` test fixture pattern and reuse it):

```python
import pytest

from vystak.schema.heartbeat import Heartbeat
from vystak_channel_runtime.heartbeat import HeartbeatScheduler


def _hb_route(target_channel: str, **overrides) -> dict:
    """Build a routes dict entry that includes a heartbeat config."""
    base = {
        "address": "http://agent:8000/a2a",
        "heartbeat": Heartbeat(
            schedule="*/30 * * * *",
            target_channel=target_channel,
            **overrides,
        ).model_dump(mode="python"),
    }
    return base


@pytest.mark.asyncio
async def test_runtime_starts_scheduler_for_matching_target():
    """Runtime spins up one scheduler per agent whose heartbeat targets it."""
    config = {
        "channel_type": "slack",
        "canonical_name": "slack-main.channels.dev",
    }
    routes = {
        "ops-bot": _hb_route("slack-main.channels.dev"),
    }
    rt = FakeRuntime(config=config, routes=routes, store=MemoryChannelStore())
    await rt.start()
    assert len(rt._heartbeats) == 1
    assert isinstance(rt._heartbeats[0], HeartbeatScheduler)
    assert rt._heartbeats[0].agent_name == "ops-bot"
    await rt.stop()


@pytest.mark.asyncio
async def test_runtime_skips_scheduler_for_other_target():
    config = {
        "channel_type": "slack",
        "canonical_name": "slack-main.channels.dev",
    }
    routes = {
        "ops-bot": _hb_route("discord-main.channels.dev"),  # not us
    }
    rt = FakeRuntime(config=config, routes=routes, store=MemoryChannelStore())
    await rt.start()
    assert rt._heartbeats == []
    await rt.stop()


@pytest.mark.asyncio
async def test_runtime_skips_scheduler_when_disabled():
    config = {
        "channel_type": "slack",
        "canonical_name": "slack-main.channels.dev",
    }
    routes = {
        "ops-bot": _hb_route("slack-main.channels.dev", enabled=False),
    }
    rt = FakeRuntime(config=config, routes=routes, store=MemoryChannelStore())
    await rt.start()
    assert rt._heartbeats == []
    await rt.stop()


@pytest.mark.asyncio
async def test_runtime_with_no_heartbeats_still_starts():
    config = {"channel_type": "slack", "canonical_name": "x.channels.dev"}
    routes = {"ops-bot": {"address": "http://agent:8000/a2a"}}
    rt = FakeRuntime(config=config, routes=routes, store=MemoryChannelStore())
    await rt.start()
    assert rt._heartbeats == []
    await rt.stop()
```

If `FakeRuntime` does not yet exist in `test_runtime.py`, define a minimal one at the top of the file:

```python
class FakeRuntime(ChannelRuntime):
    async def start(self) -> None:
        await self._start_heartbeats()

    async def stop(self) -> None:
        await self._stop_heartbeats()

    def parse_event(self, raw_event):
        return raw_event

    async def post_reply(self, event, route, reply):
        pass
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/python/vystak-channel-runtime/tests/test_runtime.py -v -k heartbeat`
Expected: FAIL — `_start_heartbeats` / `_stop_heartbeats` / `_heartbeats` don't exist.

- [ ] **Step 3: Wire schedulers into `ChannelRuntime`**

Edit `packages/python/vystak-channel-runtime/src/vystak_channel_runtime/runtime.py`.

Add the import near the top:

```python
from vystak.schema.heartbeat import Heartbeat
from vystak_channel_runtime.heartbeat import HeartbeatScheduler
```

In `ChannelRuntime.__init__`, after `self._agent_client = ...`, initialize the list:

```python
        self._heartbeats: list[HeartbeatScheduler] = []
```

Add two protected helpers at the end of the class:

```python
    @property
    def canonical_name(self) -> str:
        return self.config.get("canonical_name", "")

    def _heartbeat_for_route(self, route_entry: Any) -> Heartbeat | None:
        if not isinstance(route_entry, dict):
            return None
        raw = route_entry.get("heartbeat")
        if raw is None:
            return None
        if isinstance(raw, Heartbeat):
            return raw
        return Heartbeat.model_validate(raw)

    async def _start_heartbeats(self) -> None:
        for agent_name, route_entry in self.routes.items():
            hb = self._heartbeat_for_route(route_entry)
            if hb is None or not hb.enabled:
                continue
            if hb.target_channel != self.canonical_name:
                continue
            scheduler = HeartbeatScheduler(self, agent_name, hb)
            self._heartbeats.append(scheduler)
            await scheduler.start()

    async def _stop_heartbeats(self) -> None:
        for hb in self._heartbeats:
            await hb.stop()
        self._heartbeats.clear()
```

Add a stub for the synthetic-event dispatch (filled in Task 9):

```python
    async def _handle_synthetic_event(self, event: InboundEvent) -> None:
        """Entry point for heartbeat-synthesized events. Bypasses
        parse_event/authorize. Implemented in Task 9 to thread heartbeat-
        aware ack stripping + delivery event synthesis into the pipeline.
        """
        raise NotImplementedError
```

Add a deprecation-free guidance comment in the class docstring listing
`_start_heartbeats` / `_stop_heartbeats` as the recommended hook for
subclasses with `start`/`stop` overrides.

Each subclass (Slack, Discord, API, Chat) will need to call
`await self._start_heartbeats()` at the end of its `start()` and
`await self._stop_heartbeats()` at the start of its `stop()`. Those edits
are out of scope for this plan's runtime task; they're Task 8a, performed
by the channel maintainers when integrating. For now, the test file's
`FakeRuntime` covers the wiring contract.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/python/vystak-channel-runtime/tests/test_runtime.py -v -k heartbeat`
Expected: 4 passed.

- [ ] **Step 5: Run full runtime test suite to catch regressions**

Run: `uv run pytest packages/python/vystak-channel-runtime/tests/ -v`
Expected: all previously-passing tests still pass.

- [ ] **Step 6: Commit**

```bash
git add packages/python/vystak-channel-runtime/src/vystak_channel_runtime/runtime.py \
        packages/python/vystak-channel-runtime/tests/test_runtime.py
git commit -m "feat(channel-runtime): wire HeartbeatScheduler lifecycle into runtime"
```

---

## Task 8a: Update concrete channel runtimes to call heartbeat hooks

**Files:**
- Modify: `packages/python/vystak-channel-chat/src/vystak_channel_chat/runtime.py` (start/stop)
- Modify: `packages/python/vystak-channel-slack/src/vystak_channel_slack/runtime.py` (start/stop)
- Modify: `packages/python/vystak-channel-discord/src/vystak_channel_discord/runtime.py` (start/stop)
- Modify: `packages/python/vystak-channel-api/src/vystak_channel_api/runtime.py` (start/stop, if present)

- [ ] **Step 1: Locate each subclass `start`/`stop` and add the hook calls**

For each runtime subclass file listed above:

In `start(self) -> None`, *as the last line* of the method body:

```python
        await self._start_heartbeats()
```

In `stop(self) -> None`, *as the first line* of the method body:

```python
        await self._stop_heartbeats()
```

If the subclass calls `super().start()` / `super().stop()`, place the calls before/after the super calls so the parent template-method ordering still holds.

- [ ] **Step 2: Run each channel's existing test suite**

Run each individually:
```bash
uv run pytest packages/python/vystak-channel-chat/tests/ -v
uv run pytest packages/python/vystak-channel-slack/tests/ -v
uv run pytest packages/python/vystak-channel-discord/tests/ -v
uv run pytest packages/python/vystak-channel-api/tests/ -v 2>/dev/null || true
```
Expected: all pre-existing tests still pass (heartbeats default to no-op when no agent declares one).

- [ ] **Step 3: Commit**

```bash
git add packages/python/vystak-channel-chat/ \
        packages/python/vystak-channel-slack/ \
        packages/python/vystak-channel-discord/ \
        packages/python/vystak-channel-api/
git commit -m "feat(channels): call _start_heartbeats / _stop_heartbeats from subclasses"
```

---

## Task 9: Heartbeat-aware pipeline (`_handle_synthetic_event`)

**Files:**
- Modify: `packages/python/vystak-channel-runtime/src/vystak_channel_runtime/runtime.py`
- Modify: `packages/python/vystak-channel-runtime/tests/test_runtime.py`

- [ ] **Step 1: Write failing tests for the heartbeat pipeline**

Append to `packages/python/vystak-channel-runtime/tests/test_runtime.py`:

```python
from unittest.mock import AsyncMock

from vystak_channel_runtime.types import AgentReply, InboundEvent


def _heartbeat_event(deliver_thread: str = "C123") -> InboundEvent:
    return InboundEvent(
        channel_type="slack",
        scope_id="__heartbeat__abc",
        thread_id="__heartbeat__abc",
        user_id="__heartbeat__",
        text="Heartbeat ping",
        is_dm=False,
        mentions_bot=True,
        metadata={
            "heartbeat": True,
            "ack_max_chars": 300,
            "deliver_scope": deliver_thread,
            "deliver_thread": deliver_thread,
        },
    )


@pytest.mark.asyncio
async def test_heartbeat_ok_reply_drops_silently():
    """HEARTBEAT_OK reply should be dropped — post_reply not called."""
    config = {"channel_type": "slack", "canonical_name": "x.channels.dev"}
    routes = {"ops-bot": {"address": "http://agent:8000/a2a"}}
    rt = FakeRuntime(config=config, routes=routes, store=MemoryChannelStore())
    rt.post_reply = AsyncMock()
    rt._call_route_for_event = AsyncMock(return_value=("ops-bot", AgentReply(text="HEARTBEAT_OK")))

    await rt._handle_synthetic_event(_heartbeat_event())
    rt.post_reply.assert_not_called()


@pytest.mark.asyncio
async def test_heartbeat_alert_reply_posts_to_real_thread():
    """Non-OK reply should be delivered with a real-scope event."""
    config = {"channel_type": "slack", "canonical_name": "x.channels.dev"}
    routes = {"ops-bot": {"address": "http://agent:8000/a2a"}}
    rt = FakeRuntime(config=config, routes=routes, store=MemoryChannelStore())
    rt.post_reply = AsyncMock()
    rt._call_route_for_event = AsyncMock(return_value=("ops-bot", AgentReply(text="ALERT: disk full")))

    await rt._handle_synthetic_event(_heartbeat_event(deliver_thread="C-real"))
    assert rt.post_reply.await_count == 1
    delivered_event, route, reply = rt.post_reply.await_args.args
    assert delivered_event.scope_id == "C-real"
    assert delivered_event.thread_id == "C-real"
    assert delivered_event.metadata.get("heartbeat") is True
    assert reply.text == "ALERT: disk full"


@pytest.mark.asyncio
async def test_heartbeat_skips_after_reply_binding_write():
    """No thread binding should be written for heartbeat fires."""
    config = {"channel_type": "slack", "canonical_name": "x.channels.dev"}
    store = MemoryChannelStore()
    routes = {"ops-bot": {"address": "http://agent:8000/a2a"}}
    rt = FakeRuntime(config=config, routes=routes, store=store)
    rt.post_reply = AsyncMock()
    rt._call_route_for_event = AsyncMock(return_value=("ops-bot", AgentReply(text="anything")))

    await rt._handle_synthetic_event(_heartbeat_event())
    bindings = await store.list_thread_bindings("slack")
    assert bindings == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/python/vystak-channel-runtime/tests/test_runtime.py -v -k heartbeat`
Expected: FAIL — `_handle_synthetic_event` is `NotImplementedError`.

- [ ] **Step 3: Implement `_handle_synthetic_event`**

Edit `packages/python/vystak-channel-runtime/src/vystak_channel_runtime/runtime.py`. Replace the stub with:

```python
    async def _handle_synthetic_event(self, event: InboundEvent) -> None:
        """Entry for heartbeat-synthesized events.

        Bypasses parse_event + authorize (synthetic events are trusted).
        Routes to the agent named by `metadata["heartbeat_route"]` if set,
        otherwise resolves through normal channel routing. After the agent
        call, evaluates the reply against `is_heartbeat_ok`; on alerts,
        synthesizes a *delivery* event with the real scope/thread and
        passes it to subclass `post_reply`. Always skips `after_reply`
        (synthetic scopes shouldn't pollute the binding store).
        """
        from vystak_channel_runtime.heartbeat import is_heartbeat_ok

        route, reply = await self._call_route_for_event(event)
        if route is None or reply is None:
            return

        ack_max = int(event.metadata.get("ack_max_chars", 300))
        if is_heartbeat_ok(reply.text, ack_max):
            logger.info(
                "heartbeat.acked agent=%s thread=%s",
                route, event.metadata.get("deliver_thread"),
            )
            return

        deliver_scope = event.metadata.get("deliver_scope")
        deliver_thread = event.metadata.get("deliver_thread")
        if not deliver_scope or not deliver_thread:
            logger.warning(
                "heartbeat reply has alert content but no delivery target; dropping",
            )
            return

        delivery_event = event.model_copy(update={
            "scope_id": deliver_scope,
            "thread_id": deliver_thread,
        })
        await self.post_reply(delivery_event, route, reply)
        # Intentionally skip after_reply — heartbeat fires must not write
        # ThreadBindings (synthetic scopes would pollute the store).
```

Refactor the existing `handle_event` to share the routing+call segment with `_handle_synthetic_event`. Extract the shared lookup as `_call_route_for_event`:

```python
    async def _call_route_for_event(
        self, event: InboundEvent,
    ) -> tuple[str | None, AgentReply | None]:
        route = await self.resolve_route(event)
        if route is None:
            await self.on_no_route(event)
            return None, None
        history = await self.fetch_history(event)
        await self.before_call(event, route)
        try:
            if self.agent_protocol == "a2a-stream":
                reply = await self.stream_agent(event, route, history)
            else:
                reply = await self.call_agent(event, route, history)
        except AgentCallError as exc:
            await self.on_agent_error(event, route, exc)
            return route, None
        return route, reply
```

Update the existing `handle_event` body to use the helper:

```python
    async def handle_event(self, raw_event: Any) -> None:
        try:
            event = self.parse_event(raw_event)
        except SkipEvent:
            return
        if not await self.authorize(event):
            return
        route, reply = await self._call_route_for_event(event)
        if route is None or reply is None:
            return
        await self.post_reply(event, route, reply)
        await self.after_reply(event, route, reply)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/python/vystak-channel-runtime/tests/test_runtime.py -v -k heartbeat`
Expected: 3 passed.

- [ ] **Step 5: Run full runtime test suite for regressions**

Run: `uv run pytest packages/python/vystak-channel-runtime/tests/ -v`
Expected: all pre-existing tests still pass.

- [ ] **Step 6: Commit**

```bash
git add packages/python/vystak-channel-runtime/src/vystak_channel_runtime/runtime.py \
        packages/python/vystak-channel-runtime/tests/test_runtime.py
git commit -m "feat(channel-runtime): heartbeat-aware pipeline with delivery event synthesis"
```

---

## Task 10: Plan-time validation in `multi_loader`

**Files:**
- Modify: `packages/python/vystak/src/vystak/schema/multi_loader.py`
- Modify: `packages/python/vystak/tests/test_heartbeat_schema.py`

- [ ] **Step 1: Write failing tests for cross-deployable validation**

Append to `packages/python/vystak/tests/test_heartbeat_schema.py`:

```python
from pathlib import Path

from vystak.schema.multi_loader import load_multi_doc


def _write(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "vystak.yaml"
    path.write_text(content)
    return path


def test_target_channel_typo_rejected(tmp_path):
    yaml = """
providers:
  docker: {type: docker}
  anthropic: {type: anthropic}
platforms:
  local: {type: docker, provider: docker, namespace: dev}
models:
  c: {provider: anthropic, model_name: claude-sonnet-4-6}
agents:
  - name: ops-bot
    model: c
    platform: local
    heartbeat:
      schedule: "*/30 * * * *"
      target_channel: nonexistent.channels.dev
channels:
  - name: slack-main
    type: slack
    platform: local
    agents: [ops-bot]
"""
    with pytest.raises(ValueError, match="target_channel"):
        load_multi_doc(_write(tmp_path, yaml))


def test_target_channel_does_not_route_agent_rejected(tmp_path):
    yaml = """
providers:
  docker: {type: docker}
  anthropic: {type: anthropic}
platforms:
  local: {type: docker, provider: docker, namespace: dev}
models:
  c: {provider: anthropic, model_name: claude-sonnet-4-6}
agents:
  - name: ops-bot
    model: c
    platform: local
    heartbeat:
      schedule: "*/30 * * * *"
      target_channel: discord-main.channels.dev
channels:
  - name: slack-main
    type: slack
    platform: local
    agents: [ops-bot]
  - name: discord-main
    type: discord
    platform: local
    agents: []                 # discord doesn't route ops-bot
"""
    with pytest.raises(ValueError, match="does not route"):
        load_multi_doc(_write(tmp_path, yaml))


def test_valid_heartbeat_target_passes(tmp_path):
    yaml = """
providers:
  docker: {type: docker}
  anthropic: {type: anthropic}
platforms:
  local: {type: docker, provider: docker, namespace: dev}
models:
  c: {provider: anthropic, model_name: claude-sonnet-4-6}
agents:
  - name: ops-bot
    model: c
    platform: local
    heartbeat:
      schedule: "*/30 * * * *"
      target_channel: slack-main.channels.dev
channels:
  - name: slack-main
    type: slack
    platform: local
    agents: [ops-bot]
"""
    result = load_multi_doc(_write(tmp_path, yaml))
    agent = next(a for a in result.agents if a.name == "ops-bot")
    assert agent.heartbeat is not None
    assert agent.heartbeat.target_channel == "slack-main.channels.dev"
```

The exact name of the loader entry point in `multi_loader.py` may differ (`load_multi_doc`, `load_workspace`, etc.). Check the file's public surface and adjust the import.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/python/vystak/tests/test_heartbeat_schema.py -v -k target_channel`
Expected: FAIL — heartbeat target validation not yet enforced.

- [ ] **Step 3: Add validation to `multi_loader`**

Edit `packages/python/vystak/src/vystak/schema/multi_loader.py`. Find the function that returns the assembled deployment object (typically the function called by the YAML loader entry point). After channels are resolved and before the result is returned, call a new helper `_validate_heartbeat_targets`:

```python
def _validate_heartbeat_targets(agents: list, channels: list) -> None:
    """Cross-deployable check: every agent.heartbeat.target_channel must
    name a real channel that routes this agent."""
    channels_by_canonical = {c.canonical_name: c for c in channels}
    for agent in agents:
        if agent.heartbeat is None:
            continue
        target = agent.heartbeat.target_channel
        channel = channels_by_canonical.get(target)
        if channel is None:
            raise ValueError(
                f"agent '{agent.name}' heartbeat.target_channel "
                f"'{target}' does not match any declared channel "
                f"(have: {sorted(channels_by_canonical)})"
            )
        routed = {a.name for a in channel.agents}
        if agent.name not in routed:
            raise ValueError(
                f"channel '{target}' does not route agent '{agent.name}' "
                f"named in its heartbeat.target_channel"
            )
```

Wire it into the existing assembly path. If the loader returns `(agents, channels)` (or a model wrapping them), call:

```python
    _validate_heartbeat_targets(agents, channels)
```

just before the return.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/python/vystak/tests/test_heartbeat_schema.py -v -k target_channel`
Expected: 3 passed.

- [ ] **Step 5: Run full vystak suite for regressions**

Run: `uv run pytest packages/python/vystak/ -v`
Expected: all pre-existing tests still pass.

- [ ] **Step 6: Commit**

```bash
git add packages/python/vystak/src/vystak/schema/multi_loader.py \
        packages/python/vystak/tests/test_heartbeat_schema.py
git commit -m "feat(schema): plan-time validation for heartbeat target_channel"
```

---

## Task 11: Examples — yaml + python

**Files:**
- Create: `examples/heartbeat-agent/vystak.yaml`
- Create: `examples/heartbeat-agent/vystak.py`
- Create: `examples/heartbeat-agent/HEARTBEAT.md`
- Create: `examples/heartbeat-agent/README.md`

- [ ] **Step 1: Create example directory with all four files**

```bash
mkdir -p examples/heartbeat-agent
```

Create `examples/heartbeat-agent/vystak.yaml`:

```yaml
providers:
  docker: {type: docker}
  anthropic: {type: anthropic}

platforms:
  local: {type: docker, provider: docker, namespace: dev}

models:
  claude:
    provider: anthropic
    model_name: claude-sonnet-4-6
    parameters: {temperature: 0.3}

agents:
  - name: ops-bot
    instructions: |
      You are an ops assistant. On every heartbeat, scan the workspace's
      HEARTBEAT.md checklist and surface anything that needs attention.
      If nothing is wrong, reply with HEARTBEAT_OK and nothing else.
    model: claude
    platform: local
    skills:
      - {name: ops, tools: []}
    secrets:
      - {name: ANTHROPIC_API_KEY}
    heartbeat:
      schedule: "*/30 9-18 * * 1-5"
      timezone: America/New_York
      target_channel: chat-main.channels.dev
      target_thread: standup-room
      isolated_session: true
      skip_when_busy: true
      ack_max_chars: 300

channels:
  - name: chat-main
    type: chat
    platform: local
    config: {port: 8080}
    agents: [ops-bot]
    default_agent: ops-bot
```

Create `examples/heartbeat-agent/vystak.py`:

```python
"""Heartbeat agent — periodic self-invocation via chat channel."""

from vystak.schema import (
    Agent,
    Channel,
    ChannelType,
    Heartbeat,
    Model,
    Platform,
    Provider,
    Secret,
    Skill,
)

anthropic = Provider(name="anthropic", type="anthropic")
docker = Provider(name="docker", type="docker")
local = Platform(name="local", type="docker", provider=docker, namespace="dev")

model = Model(
    name="claude",
    provider=anthropic,
    model_name="claude-sonnet-4-6",
    parameters={"temperature": 0.3},
)

ops_agent = Agent(
    name="ops-bot",
    instructions=(
        "You are an ops assistant. On every heartbeat, scan the workspace's "
        "HEARTBEAT.md checklist and surface anything that needs attention. "
        "If nothing is wrong, reply with HEARTBEAT_OK and nothing else."
    ),
    model=model,
    platform=local,
    skills=[Skill(name="ops", tools=[])],
    secrets=[Secret(name="ANTHROPIC_API_KEY")],
    heartbeat=Heartbeat(
        schedule="*/30 9-18 * * 1-5",
        timezone="America/New_York",
        target_channel="chat-main.channels.dev",
        target_thread="standup-room",
        isolated_session=True,
        skip_when_busy=True,
        ack_max_chars=300,
    ),
)

chat = Channel(
    name="chat-main",
    type=ChannelType.CHAT,
    platform=local,
    config={"port": 8080},
    agents=[ops_agent],
    default_agent=ops_agent,
)
```

Create `examples/heartbeat-agent/HEARTBEAT.md`:

```markdown
# Ops checklist

On every heartbeat:

1. Check whether any deploys are pending review in the queue.
2. Check whether any error-rate alerts have fired in the last 30 minutes.
3. Check whether any on-call schedule changes are needed for the next 24h.

Reply only when at least one item needs human attention. Otherwise reply
with `HEARTBEAT_OK`.
```

Create `examples/heartbeat-agent/README.md`:

```markdown
# heartbeat-agent

A minimal example showing periodic agent self-invocation. The `ops-bot`
agent runs every 30 minutes (Mon-Fri 9am-6pm Eastern), reads
`HEARTBEAT.md`, and posts an alert into the `standup-room` chat scope
unless the reply is `HEARTBEAT_OK`.

## Run

```bash
cd examples/heartbeat-agent
export ANTHROPIC_API_KEY=...
vystak apply

# Watch the logs to see heartbeats fire
docker logs -f chat-main
```

## Tweak

- Change `schedule` to `"* * * * *"` (every minute) for faster local feedback.
- Edit `HEARTBEAT.md` to refine the agent's check-in checklist.
- Set `isolated_session: false` to have the heartbeat appear in the
  `standup-room` history (vs. running silently in a synthetic session).

## Ack contract

The runtime drops replies that contain `HEARTBEAT_OK` and are at most 300
characters (configurable via `ack_max_chars`). Longer replies, or replies
without the sentinel, are delivered to `target_thread`.
```

- [ ] **Step 2: Verify YAML loads through the schema**

Run: `uv run python -c "from vystak.schema.multi_loader import load_multi_doc; load_multi_doc('examples/heartbeat-agent/vystak.yaml'); print('ok')"`
Expected: `ok`. (If the function name differs, adjust based on `multi_loader.py`'s public API.)

- [ ] **Step 3: Verify Python file evaluates**

Run: `uv run python examples/heartbeat-agent/vystak.py && echo ok`
Expected: `ok`.

- [ ] **Step 4: Commit**

```bash
git add examples/heartbeat-agent/
git commit -m "docs(examples): heartbeat-agent example (yaml + code-first)"
```

---

## Task 12: User-facing documentation

**Files:**
- Create: `docs/heartbeat.md`

- [ ] **Step 1: Write the docs page**

Create `docs/heartbeat.md`:

```markdown
# Heartbeat

A heartbeat is a periodic synthetic turn — the agent wakes up on a cron
schedule, runs a check-in prompt, and either surfaces an alert into a
configured channel/thread or stays silent.

## Quick start

Add a `heartbeat` block to any agent that has at least one channel
routing to it:

```yaml
agents:
  - name: ops-bot
    model: claude
    platform: local
    heartbeat:
      schedule: "*/30 9-18 * * 1-5"     # every 30m, 9-18, Mon-Fri
      timezone: America/New_York
      target_channel: chat-main.channels.dev
      target_thread: standup-room

channels:
  - name: chat-main
    type: chat
    platform: local
    agents: [ops-bot]
```

The channel runtime named in `target_channel` hosts the scheduler. On
every cron tick, the runtime synthesizes a turn, calls the agent, and
applies the ack contract (below).

See the full example: [`examples/heartbeat-agent/`](../examples/heartbeat-agent/).

## Ack contract

When the agent's reply (after stripping whitespace):

- Is **empty** → posted as-is (an empty reply signals a real bug; we
  don't silently swallow it).
- Is **longer than `ack_max_chars`** (default 300) → always posted,
  even if it contains `HEARTBEAT_OK`. Long replies override the ack.
- Contains `HEARTBEAT_OK` → silently dropped.
- Anything else → posted into `target_thread` on `target_channel`.

## HEARTBEAT.md convention

If your agent has a workspace, place a `HEARTBEAT.md` file in it
describing the per-cycle check-in:

```markdown
# Ops checklist
On every heartbeat:
1. Check the deploy queue.
2. Check error-rate alerts.

Reply only when something needs human attention. Otherwise reply with
HEARTBEAT_OK.
```

Then leave `prompt: null` (the default) and the runtime will use:

> Read HEARTBEAT.md if it exists in your workspace. Follow it strictly.
> If nothing needs attention, reply with only HEARTBEAT_OK. Otherwise,
> reply with a short message describing what needs attention — do not
> include HEARTBEAT_OK in that case.

`HEARTBEAT.md` is a documented pattern, not a Vystak feature. The agent
itself reads (and may rewrite) the file via the workspace tooling. Vystak
does not auto-create or auto-mount it.

## Cron + timezone

`schedule` is a 5-field cron expression evaluated against `timezone`
(IANA name, default UTC). All standard cron features apply:

| Expression | Meaning |
|---|---|
| `*/30 * * * *` | every 30 minutes |
| `0 9 * * 1-5` | 9:00 AM Mon-Fri |
| `*/15 9-18 * * 1-5` | every 15m, 9-18, weekdays |
| `0 0 1 * *` | midnight on the 1st of each month |

Active-hours behavior (e.g. "only fire 9-22") is expressed directly in
cron — there is no separate `active_hours` field.

## Session isolation

By default (`isolated_session: true`), each fire uses a synthetic
session id so the heartbeat never appears in your user-facing thread
history. Only the *result* (the alert) gets posted into
`target_thread`.

Set `isolated_session: false` to make the heartbeat turn appear inline
in `target_thread`'s session — useful for digest patterns where the
agent should remember its previous summaries.

## Operational notes

- **Restart behaviour:** the scheduler resumes from `now`. Missed fires
  are not replayed (a missed 9:00 standup will not fire at 9:07 after
  a restart). This is intentional; for catch-up semantics, store state
  in your agent's memory and reason from there.
- **`skip_when_busy`:** prevents back-to-back fires from overlapping if
  the previous fire is still running. It does **not** coordinate with
  concurrent user turns. A real user message that arrives while a
  heartbeat is in flight is processed normally.
- **Multiple channels:** each agent has at most one heartbeat target.
  If you want the same agent to ping multiple channels, declare two
  agents (sharing model + skills) with different `target_channel`
  values.
```

- [ ] **Step 2: Commit**

```bash
git add docs/heartbeat.md
git commit -m "docs: heartbeat user guide"
```

---

## Task 13: Release integration test

**Files:**
- Create: `packages/python/vystak-provider-docker/tests/release/test_heartbeat.py`

- [ ] **Step 1: Inspect existing release-test pattern**

Read `packages/python/vystak-provider-docker/tests/release/test_D1_docker_default_chat_http.py` to understand the `project` fixture and the deploy/verify/destroy flow. The new test follows the same shape.

- [ ] **Step 2: Write the integration test**

Create `packages/python/vystak-provider-docker/tests/release/test_heartbeat.py`:

```python
"""Release integration cell — heartbeat + chat channel.

Cycle: deploy ops-bot with `schedule: "* * * * *"` and a custom prompt
that always returns HEARTBEAT_OK; observe the channel's logs to confirm
heartbeat firing + acking. Then hot-edit the prompt to alert text and
confirm delivery.

Marked release_integration: requires Docker daemon. Skipped by default.
"""

from __future__ import annotations

import asyncio
import subprocess
import time
from pathlib import Path

import pytest


HEARTBEAT_FIRED_LINE = "heartbeat.fired"
HEARTBEAT_ACKED_LINE = "heartbeat.acked"


def _container_logs(name: str) -> str:
    return subprocess.run(
        ["docker", "logs", name],
        capture_output=True, text=True, check=False,
    ).stdout + subprocess.run(
        ["docker", "logs", name],
        capture_output=True, text=True, check=False,
    ).stderr


def _wait_for_log(name: str, needle: str, timeout_s: int = 90) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if needle in _container_logs(name):
            return True
        time.sleep(2)
    return False


@pytest.mark.release_integration
def test_heartbeat_fires_and_acks(project, tmp_path: Path):
    """Deploy ops-bot with `* * * * *` schedule + HEARTBEAT_OK prompt;
    confirm the runtime fires + acks within ~70s."""
    yaml = """
providers:
  docker: {type: docker}
  anthropic: {type: anthropic}

platforms:
  local: {type: docker, provider: docker, namespace: dev}

models:
  c:
    provider: anthropic
    model_name: claude-sonnet-4-6

agents:
  - name: ops-bot
    instructions: "Reply only with HEARTBEAT_OK."
    model: c
    platform: local
    skills:
      - {name: ops, tools: []}
    secrets:
      - {name: ANTHROPIC_API_KEY}
    heartbeat:
      schedule: "* * * * *"
      target_channel: chat-main.channels.dev
      target_thread: hb-test
      ack_max_chars: 300

channels:
  - name: chat-main
    type: chat
    platform: local
    config: {port: 8080}
    agents: [ops-bot]
    default_agent: ops-bot
"""
    (project / "vystak.yaml").write_text(yaml)
    subprocess.run(
        ["uv", "run", "vystak", "apply", "--yes"],
        cwd=project, check=True,
    )

    container_name = "chat-main"   # docker provider names channel containers by canonical short-name
    assert _wait_for_log(container_name, HEARTBEAT_FIRED_LINE, timeout_s=90), \
        "heartbeat.fired never appeared in logs"
    assert _wait_for_log(container_name, HEARTBEAT_ACKED_LINE, timeout_s=90), \
        "heartbeat.acked never appeared in logs"
```

The exact container naming (`chat-main` vs. `vystak-chat-main` etc.) depends on the docker provider's naming convention — check `packages/python/vystak-provider-docker/src/vystak_provider_docker/nodes/` for the channel container node and adjust.

- [ ] **Step 3: Run the integration test locally**

Requires Docker daemon, `ANTHROPIC_API_KEY` in env (or the existing test-fixture sentinel that auto-skips real LLM calls). Run:

```bash
uv run pytest packages/python/vystak-provider-docker/tests/release/test_heartbeat.py -v -m release_integration
```

Expected: PASS in ~90s, with 1 deploy + 1 destroy cycle. If the test infra requires a real `ANTHROPIC_API_KEY` and the user only has the sentinel, the test should auto-skip (mirror the gate used in `test_live_chat.py`).

- [ ] **Step 4: Run unit suites one more time to confirm no late regressions**

```bash
just lint-python
just test-python
```

Expected: green on both, except for the pre-existing CI gaps documented in `CLAUDE.md` (lint-typescript and pyright).

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-provider-docker/tests/release/test_heartbeat.py
git commit -m "test(release): heartbeat fires + acks integration cell"
```

---

## Task 14: Final integration check

- [ ] **Step 1: Spec review walk-through**

Open both files side-by-side:
- `docs/superpowers/specs/2026-05-09-heartbeat-design.md`
- `docs/superpowers/plans/2026-05-09-heartbeat.md`

For each section in the spec, confirm a task in the plan implements it.

| Spec section | Task |
|---|---|
| Schema (`Heartbeat` model + Agent field) | Tasks 1, 2 |
| Plan-time validation | Task 10 |
| Hash contribution | Task 3 |
| Channel runtime — scheduler | Tasks 6, 7, 8, 8a |
| Channel runtime — ack stripping + delivery event | Tasks 4, 9 |
| Default prompt + HEARTBEAT.md convention | Task 4 (DEFAULT_PROMPT), Task 12 (docs) |
| Restart behaviour (no catch-up) | Task 7 (cron loop resumes from `now`) |
| Error handling table | Task 7 (loop survives), Task 9 (alert without target → drop+log) |
| Examples | Task 11 |
| Documentation | Task 12 |
| Tests — unit | Tasks 4, 6, 7, 9 |
| Tests — schema + plan-time | Tasks 1, 2, 3, 10 |
| Tests — release integration | Task 13 |

- [ ] **Step 2: Run the full plan-relevant test set**

```bash
uv run pytest packages/python/vystak/tests/ packages/python/vystak-channel-runtime/tests/ -v
```

Expected: all tests pass.

- [ ] **Step 3: Final commit pointing to the merged feature**

If any task left uncommitted local changes, commit them now. Otherwise, push and open a PR titled `feat: heartbeat — periodic agent self-invocation`.

```bash
git push -u origin <branch-name>
gh pr create --title "feat: heartbeat — periodic agent self-invocation" \
             --body "$(cat <<'EOF'
## Summary
- Adds `Heartbeat` Pydantic model on `Agent` with cron schedule + target channel.
- Channel runtime hosts a per-agent `HeartbeatScheduler` that fires synthetic turns through the existing pipeline.
- Replies matching `HEARTBEAT_OK` (within `ack_max_chars`) are silently dropped; alerts are posted to `target_thread`.

Spec: docs/superpowers/specs/2026-05-09-heartbeat-design.md

## Test plan
- [x] Unit: `is_heartbeat_ok` ack rules (13 tests)
- [x] Unit: `HeartbeatScheduler` lifecycle + cron + fire (13 tests)
- [x] Unit: `last_binding_for_agent` across MemoryChannelStore / SQLite / Postgres
- [x] Unit: runtime wiring + heartbeat-aware pipeline (7 tests)
- [x] Schema: cron validator + Agent integration + plan-time cross-check (11 tests)
- [x] Hash: heartbeat propagates to agent + channel hash root (5 tests)
- [x] Release integration: docker `release_integration` cell, ~90s
- [x] Examples: yaml + python forms load
EOF
)"
```

---

## Self-review notes

Performed against the spec on first pass:

- **Spec coverage:** all sections traced to a task above (see Task 14 mapping table).
- **Placeholder scan:** the only deferred item is the per-channel-subclass call to `_start_heartbeats` / `_stop_heartbeats` (Task 8a). This is split out so the core runtime work is reviewable on its own.
- **Type consistency:** `is_heartbeat_ok(text, max_chars)` (Task 4), `HeartbeatScheduler(runtime, agent_name, config)` (Task 6), `_handle_synthetic_event(event)` (Task 9) — names and signatures consistent across tasks.
- **Ambiguity:** the docker provider's channel-container naming convention is not pinned down in the integration test (Task 13 step 2 notes the lookup); the exact loader entry point in `multi_loader.py` is checked at task time (Task 10 step 3 notes the lookup). Both are local lookups, not design decisions.
