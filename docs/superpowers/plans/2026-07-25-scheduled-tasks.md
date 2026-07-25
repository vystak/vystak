# Scheduled Tasks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generalize heartbeat into scheduled tasks: declarative per-agent schedules (cron / one-shot / interval) plus runtime creation via REST, CLI, and an agent tool, persisted in a store that survives restarts.

**Architecture:** The `vystak-heartbeat` container becomes the platform scheduler: one persistent `ScheduleStore` (SQLite on a volume, Postgres optional), one fire loop, and a small FastAPI surface. `heartbeat:` compiles to a `ScheduledTask` carrying the ack contract. Declarative tasks reconcile into the store at container startup (every `vystak apply` rebuilds the container); runtime tasks survive.

**Tech Stack:** Python 3.11, Pydantic v2, croniter, aiosqlite, asyncpg, FastAPI/uvicorn, Click, Docker SDK.

**Spec:** `docs/superpowers/specs/2026-07-25-scheduled-tasks-design.md`

## Global Constraints

- Python 3.11+; run everything with `uv run`.
- Lint gate: `just lint-python` must stay green. `just test-python` must stay green.
- `test_heartbeat_v2.py` (release) behavior contract must not change: ack suppression, HEARTBEAT.md default prompt, delivery semantics.
- Container images install the emitted `REQUIREMENTS` string in `server_template.py`, NOT pyproject — any new runtime dep for the scheduler container must land in `vystak_heartbeat/server_template.py::REQUIREMENTS` in the same commit that imports it.
- The `# noqa: F401` side-effect imports listed in CLAUDE.md must not be removed.
- Datetimes are stored as UTC ISO-8601 strings; `ScheduledTask.timezone` is IANA, applied at fire-time computation only.
- One-shot grace window: 24 hours (`GRACE_WINDOW_S = 86400`).
- Scheduler API port: 8081 in-container; published to host at `127.0.0.1:9797` (CLI access). Agents use `http://vystak-heartbeat:8081`.
- This is a public repo: no real credentials anywhere; test fixtures use `fake-*`/`test-*` values.

---

### Task 1: `ScheduledTask` schema model + `Agent.schedules`

**Files:**
- Create: `packages/python/vystak/src/vystak/schema/schedule.py`
- Modify: `packages/python/vystak/src/vystak/schema/agent.py` (add `schedules` field + validator)
- Modify: `packages/python/vystak/src/vystak/schema/__init__.py` (export `ScheduledTask`)
- Test: `packages/python/vystak/tests/test_schedule_schema.py`

**Interfaces:**
- Consumes: `vystak.schema.heartbeat.Heartbeat` (existing), croniter.
- Produces: `ScheduledTask` Pydantic model (fields below), `parse_every(s: str) -> timedelta`, and `Agent.schedules: list[ScheduledTask]`. Later tasks import `from vystak.schema.schedule import ScheduledTask, parse_every`.

- [ ] **Step 1: Write the failing tests**

```python
# packages/python/vystak/tests/test_schedule_schema.py
from datetime import timedelta

import pytest
from pydantic import ValidationError

from vystak.schema.schedule import ScheduledTask, parse_every


def _mk(**kw):
    base = {"name": "t1", "cron": "0 9 * * 1"}
    base.update(kw)
    return ScheduledTask.model_validate(base)


class TestShapeValidation:
    def test_cron_ok(self):
        t = _mk()
        assert t.cron == "0 9 * * 1" and t.at is None and t.every is None

    def test_at_ok(self):
        t = ScheduledTask(name="r", at="2026-08-01T09:00:00+00:00")
        assert t.at is not None

    def test_every_ok(self):
        t = ScheduledTask(name="p", every="20m")
        assert t.every == "20m"

    def test_no_shape_rejected(self):
        with pytest.raises(ValidationError, match="exactly one"):
            ScheduledTask(name="x")

    def test_two_shapes_rejected(self):
        with pytest.raises(ValidationError, match="exactly one"):
            ScheduledTask(name="x", cron="* * * * *", every="5m")

    def test_bad_cron_rejected(self):
        with pytest.raises(ValidationError):
            ScheduledTask(name="x", cron="not a cron")

    def test_bad_every_rejected(self):
        with pytest.raises(ValidationError):
            ScheduledTask(name="x", every="fortnightly")

    def test_bad_timezone_rejected(self):
        with pytest.raises(ValidationError):
            ScheduledTask(name="x", cron="* * * * *", timezone="Mars/Olympus")


class TestParseEvery:
    @pytest.mark.parametrize("s,td", [
        ("30s", timedelta(seconds=30)),
        ("20m", timedelta(minutes=20)),
        ("2h", timedelta(hours=2)),
        ("1d", timedelta(days=1)),
    ])
    def test_units(self, s, td):
        assert parse_every(s) == td

    def test_rejects_zero(self):
        with pytest.raises(ValueError):
            parse_every("0m")


class TestDefaults:
    def test_defaults(self):
        t = _mk()
        assert t.timezone == "UTC"
        assert t.target_channel is None and t.target_thread is None
        assert t.isolated_session is True and t.skip_when_busy is True
        assert t.ack_max_chars is None and t.model is None and t.enabled is True


class TestAgentSchedules:
    def _agent(self, schedules):
        from vystak.schema import Agent, Model
        return Agent(
            name="a", framework="langchain-python",
            default_model=Model(name="m", provider="anthropic",
                                model="claude-sonnet-5"),
            schedules=schedules,
        )

    def test_agent_accepts_schedules(self):
        a = self._agent([{"name": "digest", "cron": "0 9 * * 1"}])
        assert a.schedules[0].name == "digest"

    def test_duplicate_names_rejected(self):
        with pytest.raises(ValidationError, match="duplicate schedule name"):
            self._agent([{"name": "d", "cron": "* * * * *"},
                         {"name": "d", "every": "5m"}])

    def test_reserved_heartbeat_name_rejected(self):
        with pytest.raises(ValidationError, match="reserved"):
            self._agent([{"name": "heartbeat", "cron": "* * * * *"}])
```

Note: check `packages/python/vystak/tests/` for an existing Agent fixture helper first; if `Model` requires different fields, mirror the existing fixtures.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/python/vystak/tests/test_schedule_schema.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'vystak.schema.schedule'`

- [ ] **Step 3: Implement the model**

```python
# packages/python/vystak/src/vystak/schema/schedule.py
"""ScheduledTask model — declarative + runtime-creatable agent schedules.

See docs/superpowers/specs/2026-07-25-scheduled-tasks-design.md.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Self
from zoneinfo import ZoneInfo

from croniter import croniter
from pydantic import BaseModel, Field, field_validator, model_validator

_EVERY_RE = re.compile(r"^(\d+)([smhd])$")
_UNIT = {"s": "seconds", "m": "minutes", "h": "hours", "d": "days"}


def parse_every(s: str) -> timedelta:
    """Parse a duration string like '30s', '20m', '2h', '1d'."""
    m = _EVERY_RE.match(s)
    if m is None:
        raise ValueError(f"invalid duration {s!r}; use e.g. '30s', '20m', '2h', '1d'")
    n = int(m.group(1))
    if n <= 0:
        raise ValueError(f"duration must be positive, got {s!r}")
    return timedelta(**{_UNIT[m.group(2)]: n})


class ScheduledTask(BaseModel):
    """A schedule that fires a prompt at an agent.

    Exactly one of `cron`, `at`, `every` must be set.
    """

    name: str = Field(..., description="Unique per agent; reconciliation identity.")
    cron: str | None = Field(None, description="5-field cron expression.")
    at: datetime | None = Field(
        None, description="One-shot fire time (ISO-8601). Auto-completes after firing."
    )
    every: str | None = Field(
        None, description="Interval duration: '30s', '20m', '2h', '1d'."
    )
    timezone: str = Field("UTC", description="IANA timezone for cron/naive-at.")
    prompt: str | None = Field(None, description="Prompt sent to the agent on fire.")
    target_channel: str | None = Field(
        None, description="Channel canonical_name for result delivery. None → log only."
    )
    target_thread: str | None = None
    isolated_session: bool = True
    skip_when_busy: bool = True
    ack_max_chars: int | None = Field(
        None,
        ge=1,
        description="When set, replies containing HEARTBEAT_OK within this "
        "length are suppressed (heartbeat ack contract).",
    )
    model: str | None = Field(None, description="Model name from the agent's pool.")
    enabled: bool = True

    @field_validator("cron")
    @classmethod
    def _validate_cron(cls, v: str | None) -> str | None:
        if v is not None:
            if len(v.split()) != 5 or not croniter.is_valid(v):
                raise ValueError(f"invalid 5-field cron expression: {v!r}")
        return v

    @field_validator("every")
    @classmethod
    def _validate_every(cls, v: str | None) -> str | None:
        if v is not None:
            parse_every(v)
        return v

    @field_validator("timezone")
    @classmethod
    def _validate_tz(cls, v: str) -> str:
        try:
            ZoneInfo(v)
        except Exception as e:
            raise ValueError(f"invalid IANA timezone {v!r}") from e
        return v

    @model_validator(mode="after")
    def _exactly_one_shape(self) -> Self:
        shapes = [s for s in (self.cron, self.at, self.every) if s is not None]
        if len(shapes) != 1:
            raise ValueError(
                "exactly one of cron | at | every must be set "
                f"(got {len(shapes)} on schedule '{self.name}')"
            )
        return self
```

Add to `Agent` (`packages/python/vystak/src/vystak/schema/agent.py`), next to the `heartbeat` field:

```python
from vystak.schema.schedule import ScheduledTask
...
    heartbeat: Heartbeat | None = None
    schedules: list[ScheduledTask] = []

    @model_validator(mode="after")
    def _validate_schedules(self) -> Self:
        seen: set[str] = set()
        for s in self.schedules:
            if s.name == "heartbeat":
                raise ValueError(
                    f"Agent '{self.name}': schedule name 'heartbeat' is reserved "
                    f"for the compiled heartbeat task."
                )
            if s.name in seen:
                raise ValueError(
                    f"Agent '{self.name}' has duplicate schedule name '{s.name}'."
                )
            seen.add(s.name)
        return self
```

Export in `packages/python/vystak/src/vystak/schema/__init__.py` following the existing export pattern (`ScheduledTask`, `parse_every`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/python/vystak/tests/test_schedule_schema.py -v`
Expected: PASS (all)

- [ ] **Step 5: Run the full vystak package tests + lint**

Run: `uv run pytest packages/python/vystak/tests/ -q && just lint-python`
Expected: PASS / clean

- [ ] **Step 6: Commit**

```bash
git add packages/python/vystak/src/vystak/schema/ packages/python/vystak/tests/test_schedule_schema.py
git commit -m "feat(schema): ScheduledTask model + Agent.schedules"
```

---

### Task 2: Heartbeat → ScheduledTask compilation

**Files:**
- Modify: `packages/python/vystak/src/vystak/schema/schedule.py` (add `from_heartbeat`)
- Test: `packages/python/vystak/tests/test_schedule_schema.py` (extend)

**Interfaces:**
- Consumes: `Heartbeat` (existing), `ScheduledTask` (Task 1).
- Produces: `from_heartbeat(hb: Heartbeat) -> ScheduledTask` — module-level function in `vystak.schema.schedule`. The scheduler service (Task 7) and plugin (Task 8) call it.

- [ ] **Step 1: Write the failing tests**

Append to `test_schedule_schema.py`:

```python
class TestFromHeartbeat:
    def test_compiles(self):
        from vystak.schema.heartbeat import Heartbeat
        from vystak.schema.schedule import from_heartbeat

        hb = Heartbeat(schedule="*/30 * * * *", timezone="America/New_York",
                       target_channel="chat-main.channels.dev",
                       target_thread="room-1", prompt=None,
                       isolated_session=False, skip_when_busy=False,
                       ack_max_chars=250, model="fast")
        t = from_heartbeat(hb)
        assert t.name == "heartbeat"
        assert t.cron == "*/30 * * * *" and t.at is None and t.every is None
        assert t.timezone == "America/New_York"
        assert t.target_channel == "chat-main.channels.dev"
        assert t.target_thread == "room-1"
        assert t.prompt is None          # None → scheduler falls back to DEFAULT_PROMPT
        assert t.isolated_session is False and t.skip_when_busy is False
        assert t.ack_max_chars == 250 and t.model == "fast"
        assert t.enabled is True

    def test_disabled_carries(self):
        from vystak.schema.heartbeat import Heartbeat
        from vystak.schema.schedule import from_heartbeat

        hb = Heartbeat(schedule="* * * * *", target_channel="c.channels.d",
                       enabled=False)
        assert from_heartbeat(hb).enabled is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/python/vystak/tests/test_schedule_schema.py::TestFromHeartbeat -v`
Expected: FAIL — `ImportError: cannot import name 'from_heartbeat'`

- [ ] **Step 3: Implement**

Append to `vystak/schema/schedule.py`:

```python
def from_heartbeat(hb) -> ScheduledTask:
    """Compile a Heartbeat declaration into its equivalent ScheduledTask.

    The task keeps `prompt=None` when the heartbeat has no prompt; the
    scheduler substitutes DEFAULT_PROMPT at fire time only for the task
    named 'heartbeat' (preserving HEARTBEAT.md semantics).
    """
    return ScheduledTask(
        name="heartbeat",
        cron=hb.schedule,
        timezone=hb.timezone,
        prompt=hb.prompt,
        target_channel=hb.target_channel,
        target_thread=hb.target_thread,
        isolated_session=hb.isolated_session,
        skip_when_busy=hb.skip_when_busy,
        ack_max_chars=hb.ack_max_chars,
        model=hb.model,
        enabled=hb.enabled,
    )
```

(Type the parameter as the actual `Heartbeat` import if no circular-import issue; both live in `vystak.schema`.)

- [ ] **Step 4: Run tests, then commit**

Run: `uv run pytest packages/python/vystak/tests/test_schedule_schema.py -v`
Expected: PASS

```bash
git add packages/python/vystak/src/vystak/schema/schedule.py packages/python/vystak/tests/test_schedule_schema.py
git commit -m "feat(schema): compile Heartbeat to ScheduledTask"
```

---

### Task 3: Hash-tree contribution for `schedules`

**Files:**
- Modify: `packages/python/vystak/src/vystak/hash/tree.py` (mirror the `heartbeat` field: line 35 dataclass field, ~line 274 hashing, ~294/315 wiring)
- Test: extend the existing hash tests (find them: `uv run pytest packages/python/vystak/ -k hash --collect-only -q`)

**Interfaces:**
- Consumes: `agent.schedules` (Task 1).
- Produces: `AgentHashTree` gains a `schedules: str` leaf; changing a declarative schedule changes the agent hash. Runtime tasks never touch this (they are not in the Agent model).

- [ ] **Step 1: Write the failing test** (in the existing hash test file, following its fixture style)

```python
def test_schedules_affect_hash(make_agent):
    a1 = make_agent()
    a2 = make_agent()
    a2.schedules = [ScheduledTask(name="digest", cron="0 9 * * 1")]
    assert AgentHashTree.from_agent(a1).root != AgentHashTree.from_agent(a2).root

def test_schedule_field_change_changes_hash(make_agent):
    a1 = make_agent(); a1.schedules = [ScheduledTask(name="d", cron="0 9 * * 1")]
    a2 = make_agent(); a2.schedules = [ScheduledTask(name="d", cron="0 10 * * 1")]
    assert AgentHashTree.from_agent(a1).root != AgentHashTree.from_agent(a2).root
```

Adapt names (`from_agent`, `.root`, fixture) to the real API in `tree.py` — read the heartbeat test for the exact call shape and copy it.

- [ ] **Step 2: Run to verify failure** (hash unchanged → assertion fails)

- [ ] **Step 3: Implement** — in `tree.py`, add a `schedules: str` field beside `heartbeat: str`, compute `schedules_hash = _hash_json([t.model_dump(mode="json") for t in agent.schedules])` (use the module's existing canonical-JSON hashing helper — same one heartbeat uses via `_hash_optional`), and thread it through the same three sites as `heartbeat`.

- [ ] **Step 4: Run the hash tests + full vystak tests**

Run: `uv run pytest packages/python/vystak/ -k "hash" -v && uv run pytest packages/python/vystak/tests/ -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak/src/vystak/hash/ packages/python/vystak/tests/
git commit -m "feat(hash): declarative schedules contribute to agent hash"
```

---

### Task 4: multi_loader cross-validation for schedules

**Files:**
- Modify: `packages/python/vystak/src/vystak/schema/multi_loader.py` (generalize `_validate_heartbeat_targets`, line 29)
- Test: the existing multi_loader test file (find via `grep -rl "_validate_heartbeat\|heartbeat" packages/python/vystak/tests/`)

**Interfaces:**
- Consumes: `Agent.schedules`.
- Produces: load-time errors — a schedule's non-null `target_channel` must name a declared channel that routes to the agent; a schedule's non-null `model` must be in the agent's pool. (Same rules heartbeat enforces; `target_channel=None` is allowed for schedules, unlike heartbeat.)

- [ ] **Step 1: Write failing tests** in the multi_loader test file, copying the existing heartbeat-target test cases and switching `heartbeat:` for `schedules:` — one test for unknown channel, one for channel not routing to the agent, one for unknown model name, one asserting `target_channel: null` loads fine.

- [ ] **Step 2: Run to verify failures** (loader currently ignores schedules → "expected error not raised").

- [ ] **Step 3: Implement** — inside `_validate_heartbeat_targets` (rename to `_validate_schedule_targets`, keep one call site at ~line 301), after the heartbeat block add:

```python
    for agent in agents:
        pool = {agent.default_model.name} | {m.name for m in agent.models}
        for t in agent.schedules:
            if t.target_channel is not None:
                # identical channel-exists + routes-to-agent checks as heartbeat,
                # with error strings citing f"schedules[{t.name}].target_channel"
                ...
            if t.model is not None and t.model not in pool:
                raise ValueError(
                    f"agent '{agent.name}' schedules[{t.name}].model "
                    f"'{t.model}' not in agent's model pool {sorted(pool)}"
                )
```

Copy the exact channel-lookup logic from the heartbeat branch above it (lines 36–51) rather than inventing a new one.

- [ ] **Step 4: Run multi_loader tests + commit**

Run: `uv run pytest packages/python/vystak/tests/ -k "multi" -v`
Expected: PASS

```bash
git add packages/python/vystak/src/vystak/schema/multi_loader.py packages/python/vystak/tests/
git commit -m "feat(loader): validate schedule target_channel and model refs"
```

---

### Task 5: `ScheduleStore` — SQLite backend with reconciliation

**Files:**
- Create: `packages/python/vystak-heartbeat/src/vystak_heartbeat/schedule_store.py`
- Test: `packages/python/vystak-heartbeat/tests/test_schedule_store.py`

**Interfaces:**
- Consumes: `ScheduledTask` (Task 1).
- Produces (used by Tasks 6–9):

```python
class NameCollisionError(Exception): ...

@dataclass
class StoredTask:
    id: str                    # uuid4 hex
    agent_canonical: str
    source: str                # "declarative" | "runtime"
    status: str                # "active" | "completed" | "missed" | "cancelled"
    task: ScheduledTask        # the declarative payload
    created_by: str            # "definition" | "cli" | "agent:<canonical>"
    next_fire_at: datetime | None   # aware UTC
    last_fire_at: datetime | None
    last_result: str | None

class SqliteScheduleStore:
    def __init__(self, path: str) -> None: ...
    async def connect(self) -> None            # creates schema, runs migrations
    async def close(self) -> None
    async def reconcile_declarative(self, agent_canonical: str,
                                    tasks: list[ScheduledTask]) -> None
    async def create_runtime(self, agent_canonical: str, task: ScheduledTask,
                             created_by: str) -> StoredTask   # raises NameCollisionError
    async def list(self, *, agent: str | None = None, source: str | None = None,
                   status: str | None = None) -> list[StoredTask]
    async def get(self, task_id: str) -> StoredTask | None
    async def update_runtime(self, task_id: str, patch: dict) -> StoredTask
        # raises KeyError if missing, PermissionError if source == "declarative"
    async def cancel_runtime(self, task_id: str) -> None      # same error contract
    async def set_next_fire(self, task_id: str, when: datetime | None) -> None
    async def record_fire(self, task_id: str, fired_at: datetime,
                          result: str, *, completed: bool = False) -> None
    async def mark_missed(self, task_id: str) -> None
    async def due(self, now: datetime) -> list[StoredTask]    # active+enabled, next_fire_at <= now
    async def min_next_fire(self) -> datetime | None
```

- [ ] **Step 1: Write the failing tests**

```python
# packages/python/vystak-heartbeat/tests/test_schedule_store.py
from datetime import datetime, timedelta, timezone

import pytest
from vystak.schema.schedule import ScheduledTask

from vystak_heartbeat.schedule_store import (
    NameCollisionError,
    SqliteScheduleStore,
)

AGENT = "a.agents.default"
NOW = datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
async def store(tmp_path):
    s = SqliteScheduleStore(str(tmp_path / "sched.db"))
    await s.connect()
    yield s
    await s.close()


def _cron(name="digest"):
    return ScheduledTask(name=name, cron="0 9 * * 1")


class TestRuntimeCrud:
    async def test_create_list_get(self, store):
        rec = await store.create_runtime(AGENT, _cron("r1"), created_by="cli")
        assert rec.source == "runtime" and rec.status == "active"
        assert (await store.get(rec.id)).task.name == "r1"
        assert [r.id for r in await store.list(agent=AGENT)] == [rec.id]

    async def test_name_collision_within_agent(self, store):
        await store.create_runtime(AGENT, _cron("x"), created_by="cli")
        with pytest.raises(NameCollisionError):
            await store.create_runtime(AGENT, _cron("x"), created_by="cli")

    async def test_cancel(self, store):
        rec = await store.create_runtime(AGENT, _cron(), created_by="cli")
        await store.cancel_runtime(rec.id)
        assert (await store.get(rec.id)).status == "cancelled"

    async def test_update_declarative_forbidden(self, store):
        await store.reconcile_declarative(AGENT, [_cron("d")])
        [rec] = await store.list(agent=AGENT, source="declarative")
        with pytest.raises(PermissionError):
            await store.update_runtime(rec.id, {"enabled": False})
        with pytest.raises(PermissionError):
            await store.cancel_runtime(rec.id)


class TestReconcile:
    async def test_upsert_and_prune(self, store):
        await store.reconcile_declarative(AGENT, [_cron("keep"), _cron("drop")])
        await store.reconcile_declarative(AGENT, [_cron("keep"),
                                                  _cron("new")])
        names = {r.task.name for r in await store.list(agent=AGENT)}
        assert names == {"keep", "new"}

    async def test_runtime_tasks_survive_reconcile(self, store):
        await store.create_runtime(AGENT, _cron("mine"), created_by="agent:" + AGENT)
        await store.reconcile_declarative(AGENT, [])
        assert {r.task.name for r in await store.list(agent=AGENT)} == {"mine"}

    async def test_runtime_collides_with_declarative(self, store):
        await store.reconcile_declarative(AGENT, [_cron("d")])
        with pytest.raises(NameCollisionError):
            await store.create_runtime(AGENT, _cron("d"), created_by="cli")

    async def test_reconcile_updates_changed_payload(self, store):
        await store.reconcile_declarative(AGENT, [_cron("d")])
        changed = ScheduledTask(name="d", cron="0 10 * * 1")
        await store.reconcile_declarative(AGENT, [changed])
        [rec] = await store.list(agent=AGENT)
        assert rec.task.cron == "0 10 * * 1"


class TestFireBookkeeping:
    async def test_due_and_next_fire(self, store):
        rec = await store.create_runtime(AGENT, _cron(), created_by="cli")
        await store.set_next_fire(rec.id, NOW - timedelta(minutes=1))
        assert [r.id for r in await store.due(NOW)] == [rec.id]
        assert await store.min_next_fire() == NOW - timedelta(minutes=1)

    async def test_disabled_not_due(self, store):
        rec = await store.create_runtime(
            AGENT, ScheduledTask(name="off", cron="* * * * *", enabled=False),
            created_by="cli")
        await store.set_next_fire(rec.id, NOW - timedelta(minutes=1))
        assert await store.due(NOW) == []

    async def test_record_fire_completes_oneshot(self, store):
        rec = await store.create_runtime(
            AGENT, ScheduledTask(name="once", at=NOW), created_by="cli")
        await store.record_fire(rec.id, NOW, "done", completed=True)
        got = await store.get(rec.id)
        assert got.status == "completed" and got.last_result == "done"

    async def test_persistence_across_reconnect(self, store, tmp_path):
        rec = await store.create_runtime(AGENT, _cron("p"), created_by="cli")
        await store.close()
        s2 = SqliteScheduleStore(str(tmp_path / "sched.db"))
        await s2.connect()
        assert (await s2.get(rec.id)).task.name == "p"
        await s2.close()
```

Check `packages/python/vystak-heartbeat/tests/` / root `pyproject.toml` for the asyncio test mode (`asyncio_mode = "auto"` or `@pytest.mark.asyncio`) and match it.

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest packages/python/vystak-heartbeat/tests/test_schedule_store.py -v`
Expected: FAIL — `ModuleNotFoundError ... schedule_store`

- [ ] **Step 3: Implement `schedule_store.py`**

Follow `vystak_channel_panel/store.py` for the migration pattern (a `SCHEMA_VERSION` int + `_migrate()` bringing older DBs forward; version stored in a `settings` table). Core DDL:

```sql
CREATE TABLE IF NOT EXISTS scheduled_tasks (
    id TEXT PRIMARY KEY,
    agent_canonical TEXT NOT NULL,
    name TEXT NOT NULL,
    source TEXT NOT NULL CHECK (source IN ('declarative','runtime')),
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active','completed','missed','cancelled')),
    payload TEXT NOT NULL,            -- ScheduledTask.model_dump_json()
    created_by TEXT NOT NULL,
    next_fire_at TEXT,                -- UTC ISO-8601
    last_fire_at TEXT,
    last_result TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (agent_canonical, name)
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
```

Implementation notes (all enforced by the tests above):
- Store the whole `ScheduledTask` as a JSON `payload` column — no per-field columns to migrate when the model grows. `StoredTask.task = ScheduledTask.model_validate_json(row["payload"])`.
- `UNIQUE (agent_canonical, name)` backs `NameCollisionError`: catch `aiosqlite.IntegrityError` in `create_runtime` and re-raise. The uniqueness constraint spans sources, which also enforces "runtime may not collide with declarative".
- `reconcile_declarative`: in one transaction — `DELETE FROM scheduled_tasks WHERE agent_canonical=? AND source='declarative' AND name NOT IN (…)`, then upsert each task by `(agent_canonical, name)` with `ON CONFLICT DO UPDATE SET payload=excluded.payload, status='active'` (a changed declarative resets to active; `next_fire_at` is cleared to NULL so the scheduler recomputes).
- `update_runtime` applies `patch` onto the parsed `ScheduledTask` via `task.model_copy(update=patch)` re-validated with `ScheduledTask.model_validate(...)`, then writes payload back and clears `next_fire_at` if any shape field changed.
- `due()` filters `status='active' AND next_fire_at IS NOT NULL AND next_fire_at <= ?` and additionally `json_extract(payload,'$.enabled') = 1` (or filter in Python after parse — simpler, do that).
- Async connection handling: copy the `_ensure()`/lock pattern from `session_store.py::SqliteStore`.

- [ ] **Step 4: Run the store tests**

Run: `uv run pytest packages/python/vystak-heartbeat/tests/test_schedule_store.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-heartbeat/
git commit -m "feat(scheduler): persistent ScheduleStore (sqlite) with reconciliation"
```

---

### Task 6: Fire-time computation + missed-fire policy

**Files:**
- Create: `packages/python/vystak-heartbeat/src/vystak_heartbeat/firing.py`
- Test: `packages/python/vystak-heartbeat/tests/test_firing.py`

**Interfaces:**
- Consumes: `ScheduledTask`, `parse_every` (Task 1).
- Produces (used by Task 7):

```python
GRACE_WINDOW_S = 86400

def compute_next_fire(task: ScheduledTask, now: datetime) -> datetime | None:
    """Next fire time (aware UTC) for a task with no pending next_fire_at.
    cron → croniter next in task.timezone; every → now + interval;
    at → the timestamp itself (past-ness is judged by classify_startup)."""

def classify_startup(task: ScheduledTask, stored_next: datetime | None,
                     now: datetime) -> tuple[str, datetime | None]:
    """Restart policy. Returns (action, next_fire_at) where action is:
    'schedule'  — set next_fire_at to the returned datetime
    'fire-now'  — one-shot missed within GRACE_WINDOW_S: fire immediately
    'missed'    — one-shot older than grace: mark status missed
    """
```

- [ ] **Step 1: Write the failing tests**

```python
# packages/python/vystak-heartbeat/tests/test_firing.py
from datetime import datetime, timedelta, timezone

from vystak.schema.schedule import ScheduledTask

from vystak_heartbeat.firing import classify_startup, compute_next_fire

UTC = timezone.utc
NOW = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)   # a Saturday


class TestComputeNextFire:
    def test_cron_respects_timezone(self):
        t = ScheduledTask(name="d", cron="0 9 * * 1", timezone="America/New_York")
        nxt = compute_next_fire(t, NOW)
        # Monday 2026-07-27 09:00 EDT == 13:00 UTC
        assert nxt == datetime(2026, 7, 27, 13, 0, tzinfo=UTC)

    def test_every_adds_interval(self):
        t = ScheduledTask(name="p", every="20m")
        assert compute_next_fire(t, NOW) == NOW + timedelta(minutes=20)

    def test_at_returns_timestamp(self):
        when = NOW + timedelta(hours=3)
        t = ScheduledTask(name="o", at=when)
        assert compute_next_fire(t, NOW) == when

    def test_naive_at_localized_via_timezone_field(self):
        t = ScheduledTask(name="o", at=datetime(2026, 7, 27, 9, 0),
                          timezone="America/New_York")
        assert compute_next_fire(t, NOW) == datetime(2026, 7, 27, 13, 0, tzinfo=UTC)


class TestClassifyStartup:
    def test_recurring_skips_missed(self):
        t = ScheduledTask(name="d", cron="0 9 * * 1")
        action, nxt = classify_startup(t, NOW - timedelta(days=3), NOW)
        assert action == "schedule" and nxt > NOW

    def test_oneshot_future_scheduled(self):
        t = ScheduledTask(name="o", at=NOW + timedelta(hours=1))
        assert classify_startup(t, None, NOW) == ("schedule", NOW + timedelta(hours=1))

    def test_oneshot_missed_within_grace_fires_now(self):
        t = ScheduledTask(name="o", at=NOW - timedelta(hours=2))
        assert classify_startup(t, NOW - timedelta(hours=2), NOW)[0] == "fire-now"

    def test_oneshot_older_than_grace_marked_missed(self):
        t = ScheduledTask(name="o", at=NOW - timedelta(days=2))
        assert classify_startup(t, NOW - timedelta(days=2), NOW)[0] == "missed"

    def test_interval_recomputes_from_now(self):
        t = ScheduledTask(name="p", every="1h")
        action, nxt = classify_startup(t, NOW - timedelta(hours=5), NOW)
        assert action == "schedule" and nxt == NOW + timedelta(hours=1)
```

- [ ] **Step 2: Run to verify failure** — `ModuleNotFoundError ... firing`

- [ ] **Step 3: Implement `firing.py`**

```python
"""Next-fire computation and restart (missed-fire) policy."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from croniter import croniter
from vystak.schema.schedule import ScheduledTask, parse_every

GRACE_WINDOW_S = 86400


def _as_utc(dt: datetime, tz_name: str) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo(tz_name))
    return dt.astimezone(timezone.utc)


def compute_next_fire(task: ScheduledTask, now: datetime) -> datetime | None:
    if task.cron is not None:
        tz = ZoneInfo(task.timezone)
        nxt = croniter(task.cron, now.astimezone(tz)).get_next(datetime)
        return nxt.astimezone(timezone.utc)
    if task.every is not None:
        return now + parse_every(task.every)
    if task.at is not None:
        return _as_utc(task.at, task.timezone)
    return None


def classify_startup(
    task: ScheduledTask, stored_next: datetime | None, now: datetime
) -> tuple[str, datetime | None]:
    if task.at is not None:
        when = _as_utc(task.at, task.timezone)
        if when > now:
            return ("schedule", when)
        if (now - when).total_seconds() <= GRACE_WINDOW_S:
            return ("fire-now", None)
        return ("missed", None)
    # Recurring: never replay — always recompute strictly from now.
    return ("schedule", compute_next_fire(task, now))
```

- [ ] **Step 4: Run tests, lint, commit**

Run: `uv run pytest packages/python/vystak-heartbeat/tests/test_firing.py -v && just lint-python`
Expected: PASS / clean

```bash
git add packages/python/vystak-heartbeat/
git commit -m "feat(scheduler): next-fire computation and missed-fire policy"
```

---

### Task 7: Unified `TaskScheduler` loop (replaces per-heartbeat loops)

**Files:**
- Create: `packages/python/vystak-heartbeat/src/vystak_heartbeat/task_scheduler.py`
- Delete: `packages/python/vystak-heartbeat/src/vystak_heartbeat/scheduler.py` (superseded; delete its test too and port the fire-semantics cases)
- Test: `packages/python/vystak-heartbeat/tests/test_task_scheduler.py`
- Modify: `packages/python/vystak-heartbeat/tests/test_scheduler.py` → delete (cases ported)

**Interfaces:**
- Consumes: `SqliteScheduleStore` (Task 5), `firing` (Task 6), `HeartbeatSessionStore` (existing), `is_heartbeat_ok`/`DEFAULT_PROMPT` (existing, `vystak_channel_runtime.heartbeat`), Transport duck-type `send_task(AgentRef, A2AMessage, metadata=, timeout=)`, delivery duck-type `deliver(channel_canonical, DeliveryRequest)`.
- Produces:

```python
class TaskScheduler:
    def __init__(self, *, store, transport, delivery, sessions,
                 agent_names: dict[str, str]) -> None
        # agent_names: canonical → short name (for log/delivery metadata)
    def wake(self) -> None                 # API writes call this
    async def startup_reconcile_next_fires(self) -> None
    async def start(self) -> None
    async def stop(self) -> None
```

- [ ] **Step 1: Write the failing tests**

Port the fire-semantics tests from the old `test_scheduler.py` (AsyncMock `transport.send_task` / `delivery.deliver`) onto the new class. Minimum set:

```python
# packages/python/vystak-heartbeat/tests/test_task_scheduler.py
# (fixtures: sqlite store in tmp_path; transport = AsyncMock whose send_task
#  returns SimpleNamespace(text="pong", metadata={}); delivery = AsyncMock)

class TestFireSemantics:
    async def test_fires_due_task_and_delivers(self, sched, store, transport, delivery):
        rec = await store.create_runtime(AGENT, ScheduledTask(
            name="r", cron="* * * * *", prompt="go",
            target_channel="chat.channels.dev", target_thread="t1"), created_by="cli")
        await store.set_next_fire(rec.id, past())
        await sched._fire_due(now())
        transport.send_task.assert_awaited_once()
        delivery.deliver.assert_awaited_once()
        assert (await store.get(rec.id)).last_fire_at is not None

    async def test_no_target_channel_no_delivery(self, ...):
        # task without target_channel: send_task called, deliver NOT called

    async def test_ack_suppresses_delivery(self, ...):
        # ack_max_chars=300, reply "HEARTBEAT_OK" → deliver NOT called

    async def test_heartbeat_task_uses_default_prompt(self, ...):
        # task named "heartbeat", prompt None → sent text == DEFAULT_PROMPT

    async def test_oneshot_completes_after_fire(self, ...):
        # at-task fired → status "completed", next_fire_at None

    async def test_recurring_reschedules_after_fire(self, ...):
        # cron task fired → next_fire_at recomputed > now

    async def test_skip_when_busy(self, ...):
        # mark task busy (scheduler._busy set), fire → send_task not called

    async def test_isolated_session_synthetic_id(self, ...):
        # isolated_session=True → metadata["session_id"].startswith("__scheduled__")

class TestStartupReconcile:
    async def test_oneshot_within_grace_fires_on_startup(self, ...):
    async def test_oneshot_beyond_grace_marked_missed(self, ...):
    async def test_recurring_recomputed_from_now(self, ...):
```

Write every `...` body out in full in the actual test file — the shapes above define the assertions; the fixture pattern comes from the deleted `test_scheduler.py` (AsyncMock transport/delivery, `SimpleNamespace` replies).

- [ ] **Step 2: Run to verify failure** — `ModuleNotFoundError ... task_scheduler`

- [ ] **Step 3: Implement `task_scheduler.py`**

Structure (transplanting `HeartbeatScheduler._fire/_call_agent/_deliver` logic — keep those method bodies nearly verbatim, they are release-tested behavior):

```python
class TaskScheduler:
    POLL_CAP_S = 60.0        # never sleep longer than this without checking store

    def __init__(self, *, store, transport, delivery, sessions, agent_names):
        self._store, self._transport = store, transport
        self._delivery, self._sessions = delivery, sessions
        self._agent_names = agent_names
        self._busy: set[str] = set()          # StoredTask.id currently firing
        self._wake = asyncio.Event()
        self._task: asyncio.Task | None = None

    def wake(self): self._wake.set()

    async def startup_reconcile_next_fires(self):
        now = datetime.now(timezone.utc)
        for rec in await self._store.list(status="active"):
            action, nxt = classify_startup(rec.task, rec.next_fire_at, now)
            if action == "schedule":
                await self._store.set_next_fire(rec.id, nxt)
            elif action == "fire-now":
                await self._store.set_next_fire(rec.id, now)   # picked up first loop pass
            else:
                await self._store.mark_missed(rec.id)

    async def _fire_due(self, now):
        for rec in await self._store.due(now):
            if rec.task.skip_when_busy and rec.id in self._busy:
                continue
            asyncio.create_task(self._fire_one(rec))
            # advance next_fire immediately so a slow fire can't double-trigger
            if rec.task.at is not None:
                await self._store.set_next_fire(rec.id, None)
            else:
                await self._store.set_next_fire(
                    rec.id, compute_next_fire(rec.task, now))

    async def _fire_one(self, rec):
        self._busy.add(rec.id)
        try:
            prompt = rec.task.prompt or (
                DEFAULT_PROMPT if rec.task.name == "heartbeat" else None)
            if prompt is None:
                prompt = f"Scheduled task '{rec.task.name}' fired."
            session_id = (f"__scheduled__{int(time.time())}_{secrets.token_hex(4)}"
                          if rec.task.isolated_session
                          else (rec.task.target_thread or rec.task.name))
            reply = await self._transport.send_task(
                AgentRef(canonical_name=rec.agent_canonical),
                A2AMessage.from_text(prompt, correlation_id=session_id),
                metadata={"scheduled_task": rec.task.name,
                          "model_override": rec.task.model,
                          "session_id": session_id},
                timeout=120)
            text = reply.text or ""
            suppressed = (rec.task.ack_max_chars is not None
                          and is_heartbeat_ok(text, rec.task.ack_max_chars))
            if not suppressed and rec.task.target_channel and rec.task.target_thread:
                await self._delivery.deliver(rec.task.target_channel,
                    DeliveryRequest(thread_id=rec.task.target_thread, text=text,
                        metadata={"scheduled_task": rec.task.name,
                                  "agent": self._agent_names.get(rec.agent_canonical,
                                                                 rec.agent_canonical),
                                  "fired_at": datetime.now(timezone.utc).isoformat()}))
            await self._store.record_fire(rec.id, datetime.now(timezone.utc),
                                          text[:1000],
                                          completed=rec.task.at is not None)
        except Exception:
            logger.exception("fire failed task=%s agent=%s",
                             rec.task.name, rec.agent_canonical)
        finally:
            self._busy.discard(rec.id)

    async def _run(self):
        while True:
            now = datetime.now(timezone.utc)
            await self._fire_due(now)
            nxt = await self._store.min_next_fire()
            delay = self.POLL_CAP_S if nxt is None else min(
                self.POLL_CAP_S, max(0.0, (nxt - now).total_seconds()))
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=delay)
                self._wake.clear()
            except TimeoutError:
                pass
```

Add `start`/`stop` mirroring the old class. Also preserve the per-session model-stickiness behavior (`sessions.get_model`/`set_model` around `model_override`) — copy it verbatim from `HeartbeatScheduler._fire` lines 81–93 into `_fire_one`; it is release-tested.

- [ ] **Step 4: Run scheduler tests + package tests**

Run: `uv run pytest packages/python/vystak-heartbeat/tests/ -v`
Expected: PASS (old `test_scheduler.py` deleted, cases live in `test_task_scheduler.py`)

- [ ] **Step 5: Commit**

```bash
git add -A packages/python/vystak-heartbeat/
git commit -m "feat(scheduler): unified store-driven TaskScheduler loop"
```

---

### Task 8: REST API + plugin/bundle + container entrypoint

**Files:**
- Create: `packages/python/vystak-heartbeat/src/vystak_heartbeat/api.py`
- Modify: `packages/python/vystak-heartbeat/src/vystak_heartbeat/__main__.py` (reconcile → scheduler + uvicorn)
- Modify: `packages/python/vystak-heartbeat/src/vystak_heartbeat/plugin.py` (routes gain `schedules`; service_config gains `store` + full `channel_addresses`)
- Modify: `packages/python/vystak-heartbeat/src/vystak_heartbeat/server_template.py` (REQUIREMENTS += `fastapi>=0.110`, `uvicorn>=0.29`; Dockerfile CMD unchanged — uvicorn runs in-process)
- Test: `packages/python/vystak-heartbeat/tests/test_api.py`, extend `tests/test_plugin.py`

**Interfaces:**
- Consumes: `SqliteScheduleStore`, `TaskScheduler.wake()`, `ScheduledTask`, `from_heartbeat`.
- Produces: `build_api(store, scheduler) -> FastAPI` with routes exactly:
  - `GET /healthz` → `{"status": "ok"}`
  - `GET /tasks?agent=&source=&status=` → `{"tasks": [TaskOut...]}`
  - `POST /tasks` body `TaskIn {agent: str, **ScheduledTask fields}` → 201 `TaskOut`; 409 on `NameCollisionError`
  - `GET /tasks/{id}` → `TaskOut` | 404
  - `PATCH /tasks/{id}` body: partial ScheduledTask fields → `TaskOut`; 409 `{"detail": "declarative task — change the YAML definition and re-apply"}`; 404
  - `DELETE /tasks/{id}` → 204; same 409/404 contract
  - `TaskOut = {id, agent, name, source, status, created_by, next_fire_at, last_fire_at, last_result, task: {…ScheduledTask…}}`

- [ ] **Step 1: Write failing API tests** using `fastapi.testclient.TestClient` (or httpx `ASGITransport` if the repo's other API tests use that — check `vystak-channel-panel` tests and match): create → list → get → patch enable=false → delete; declarative 409 on PATCH/DELETE; POST name collision 409; POST with two shape fields → 422; verify `scheduler.wake` called after each mutation (pass a `MagicMock()` scheduler).

- [ ] **Step 2: Run to verify failure** — `ModuleNotFoundError ... api`

- [ ] **Step 3: Implement `api.py`**

```python
"""Scheduler REST API — internal platform network + 127.0.0.1 host publish."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel

from vystak.schema.schedule import ScheduledTask

from vystak_heartbeat.schedule_store import NameCollisionError


class TaskIn(ScheduledTask):
    agent: str          # agent canonical_name
    created_by: str = "api"


def _out(rec) -> dict:
    return {
        "id": rec.id, "agent": rec.agent_canonical, "name": rec.task.name,
        "source": rec.source, "status": rec.status, "created_by": rec.created_by,
        "next_fire_at": rec.next_fire_at.isoformat() if rec.next_fire_at else None,
        "last_fire_at": rec.last_fire_at.isoformat() if rec.last_fire_at else None,
        "last_result": rec.last_result,
        "task": rec.task.model_dump(mode="json"),
    }


def build_api(store, scheduler) -> FastAPI:
    app = FastAPI(title="vystak-scheduler")

    @app.get("/healthz")
    async def healthz():
        return {"status": "ok"}

    @app.get("/tasks")
    async def list_tasks(agent: str | None = None, source: str | None = None,
                         status: str | None = None):
        recs = await store.list(agent=agent, source=source, status=status)
        return {"tasks": [_out(r) for r in recs]}

    @app.post("/tasks", status_code=201)
    async def create_task(body: TaskIn):
        task = ScheduledTask.model_validate(
            body.model_dump(exclude={"agent", "created_by"}))
        try:
            rec = await store.create_runtime(body.agent, task,
                                             created_by=body.created_by)
        except NameCollisionError as e:
            raise HTTPException(409, str(e)) from e
        scheduler.wake()
        return _out(rec)

    @app.get("/tasks/{task_id}")
    async def get_task(task_id: str):
        rec = await store.get(task_id)
        if rec is None:
            raise HTTPException(404, "task not found")
        return _out(rec)

    @app.patch("/tasks/{task_id}")
    async def patch_task(task_id: str, patch: dict):
        try:
            rec = await store.update_runtime(task_id, patch)
        except KeyError:
            raise HTTPException(404, "task not found") from None
        except PermissionError:
            raise HTTPException(
                409, "declarative task — change the YAML definition and re-apply"
            ) from None
        scheduler.wake()
        return _out(rec)

    @app.delete("/tasks/{task_id}", status_code=204)
    async def delete_task(task_id: str):
        try:
            await store.cancel_runtime(task_id)
        except KeyError:
            raise HTTPException(404, "task not found") from None
        except PermissionError:
            raise HTTPException(
                409, "declarative task — change the YAML definition and re-apply"
            ) from None
        scheduler.wake()
        return Response(status_code=204)

    return app
```

(If `startup_reconcile_next_fires` needs to run for new tasks: it doesn't — `create_runtime` leaves `next_fire_at` NULL and the loop computes it on the first wake pass. Ensure `TaskScheduler._fire_due` also assigns `next_fire_at` for active rows where it is NULL: add that to `_run` before `_fire_due` — `for rec in await store.list(status="active"): if rec.next_fire_at is None: await store.set_next_fire(rec.id, compute_next_fire(rec.task, now))`. Cover with one API-integration test: POST then run one loop pass, next_fire_at populated.)

- [ ] **Step 4: Rewrite `__main__.py`**

Keep `_build_transport/_build_delivery/_build_session_store` as-is. Replace the scheduler block:

```python
    store = SqliteScheduleStore(cfg.get("store", {}).get("path", "/data/scheduler.db"))
    await store.connect()

    agent_names: dict[str, str] = {}
    for agent_name, route in routes.items():
        agent_names[route["canonical"]] = agent_name
        declared: list[ScheduledTask] = []
        if "heartbeat" in route:
            hb = Heartbeat.model_validate(route["heartbeat"])
            declared.append(from_heartbeat(hb))
        for raw in route.get("schedules", []):
            declared.append(ScheduledTask.model_validate(raw))
        await store.reconcile_declarative(route["canonical"], declared)

    scheduler = TaskScheduler(store=store, transport=transport,
                              delivery=delivery, sessions=sessions,
                              agent_names=agent_names)
    await scheduler.startup_reconcile_next_fires()
    await scheduler.start()

    import uvicorn
    from vystak_heartbeat.api import build_api
    server = uvicorn.Server(uvicorn.Config(
        build_api(store, scheduler), host="0.0.0.0", port=8081, log_level="warning"))
    api_task = asyncio.create_task(server.serve())
    # existing signal wait…, then: server.should_exit = True; await api_task;
    # await scheduler.stop(); await store.close()
```

Note: disabled heartbeats (`hb.enabled is False`) are still reconciled in (the task carries `enabled=False`) — the store filter keeps them from firing, and they stay visible in `GET /tasks`.

- [ ] **Step 5: Update `plugin.py` + `server_template.py`**

In `build_bundle`: accept `agents_with_schedules: list[Any]` instead of `agents_with_heartbeat` (rename the parameter; include any agent with `heartbeat` OR non-empty `schedules`); per route add `"schedules": [t.model_dump(mode="json") for t in agent.schedules]`; make `"delivery"` optional (only when heartbeat present); add every channel to `service_config["channel_addresses"] = channel_addresses` so runtime tasks can deliver to any channel — and in `__main__`, build `channel_routes` from that map instead of only heartbeat-target routes. Add `"store": {"type": "sqlite", "path": "/data/scheduler.db"}` to `service_config`. REQUIREMENTS gains:

```
fastapi>=0.110
uvicorn>=0.29
```

Extend `tests/test_plugin.py`: bundle for an agent with `schedules` and no `heartbeat` produces a route with `schedules` and no `delivery`; `service_config.json` contains `store` and `channel_addresses`; REQUIREMENTS contains `fastapi` and `uvicorn`.

- [ ] **Step 6: Run all vystak-heartbeat tests + lint, commit**

Run: `uv run pytest packages/python/vystak-heartbeat/tests/ -v && just lint-python`
Expected: PASS / clean

```bash
git add packages/python/vystak-heartbeat/
git commit -m "feat(scheduler): REST API, bundle schedules, entrypoint rework"
```

---

### Task 9: Platform `scheduler:` toggle + Docker provider wiring

**Files:**
- Modify: `packages/python/vystak/src/vystak/schema/platform.py` (add `scheduler` field)
- Modify: `packages/python/vystak-provider-docker/src/vystak_provider_docker/nodes/heartbeat.py` (volume + port)
- Modify: `packages/python/vystak-provider-docker/src/vystak_provider_docker/provider.py` (`apply_heartbeat` → generalized, `_get_container` env)
- Modify: `packages/python/vystak-provider-docker/src/vystak_provider_docker/nodes/agent.py` (inject `VYSTAK_SCHEDULER_URL` / `VYSTAK_AGENT_CANONICAL`)
- Modify: `packages/python/vystak-cli/src/vystak_cli/commands/apply.py` (spawn condition, ~line 462)
- Test: extend existing provider/CLI unit tests (`grep -rl "apply_heartbeat" packages/python/*/tests/`)

**Interfaces:**
- Consumes: everything above.
- Produces:
  - `Platform.scheduler: SchedulerConfig | None` where `class SchedulerConfig(BaseModel): enabled: bool = False` (in `platform.py`; YAML: `scheduler: {enabled: true}`).
  - `DockerProvider.apply_scheduler(agents_with_schedules, channels, *, platform=None)` — new name; `apply_heartbeat` becomes a one-line alias calling it (existing callers/tests keep working).
  - Scheduler container: volume `vystak-scheduler-data` → `/data`, port `{"8081/tcp": ("127.0.0.1", 9797)}`.
  - Agent containers: env `VYSTAK_SCHEDULER_URL=http://vystak-heartbeat:8081` and `VYSTAK_AGENT_CANONICAL=<canonical_name>` whenever the platform will have a scheduler.

- [ ] **Step 1: Write failing tests**
  - Platform schema: `Platform(..., scheduler={"enabled": True}).scheduler.enabled is True`; default `None`.
  - Provider (mock docker client, follow `test_network.py` patching style): `apply_scheduler` provisions when an agent has only `schedules`; `DockerHeartbeatNode.provision` runs the container with a `vystak-scheduler-data` volume and the 127.0.0.1:9797 port binding.
  - apply.py orchestration: the pre-filter includes agents where `heartbeat or schedules`, and runs when `platform.scheduler.enabled` even with zero declaring agents (unit-test the extracted helper — see Step 3).

- [ ] **Step 2: Run to verify failures**

- [ ] **Step 3: Implement**

`platform.py`:

```python
class SchedulerConfig(BaseModel):
    enabled: bool = False
...
    scheduler: SchedulerConfig | None = None
```

`nodes/heartbeat.py` — in `provision()`, add before `containers.run`:

```python
            try:
                self._client.volumes.get("vystak-scheduler-data")
            except docker.errors.NotFound:
                self._client.volumes.create("vystak-scheduler-data")
```

and to `containers.run(...)`:

```python
                volumes={"vystak-scheduler-data": {"bind": "/data", "mode": "rw"}},
                ports={"8081/tcp": ("127.0.0.1", 9797)},
```

`destroy()` keeps the volume (persistence across redeploys is the point; the release-test conftest cleans it — Task 12).

`provider.py` — rename `apply_heartbeat` body to `apply_scheduler(self, agents_with_schedules, channels, *, platform=None)`; keep `apply_heartbeat = apply_scheduler`-style alias method:

```python
    def apply_heartbeat(self, agents_with_heartbeat, channels, *, platform=None):
        return self.apply_scheduler(agents_with_heartbeat, channels, platform=platform)
```

Inside, drop the early-return-on-empty (an empty list is now legal when `platform.scheduler.enabled`), pass ALL channels' addresses (it already does), and pass agent addresses for every agent in the list.

`apply.py` (~line 462) — extract the filter into a helper for unit-testing:

```python
def _agents_needing_scheduler(agent_entries) -> list:
    return [a for a in agent_entries
            if getattr(a["agent"], "heartbeat", None) is not None
            or getattr(a["agent"], "schedules", [])]
```

and change the condition to `if agents_with_schedules or (platform and platform.scheduler and platform.scheduler.enabled):`, calling `provider.apply_scheduler(...)` (keep the `hasattr` guard pattern). Echo text: `"Scheduler: provisioning vystak-heartbeat container"`.

`nodes/agent.py` — where env is assembled (~line 230, next to `VYSTAK_WORKSPACE_HOST`), the node needs a constructor flag. Add `scheduler_enabled: bool = False` keyword to `DockerAgentNode.__init__`, and in env assembly:

```python
            if self._scheduler_enabled:
                env["VYSTAK_SCHEDULER_URL"] = "http://vystak-heartbeat:8081"
                env["VYSTAK_AGENT_CANONICAL"] = self._agent.canonical_name
```

(Adapt attribute names to the node's actual members — read `agent.py` lines 23–90 first.) The provider passes `scheduler_enabled=True` when the deployment will have a scheduler; the flag is computed in `apply.py` and threaded through the provider's agent-deploy call — find where `DockerAgentNode` is constructed (`grep -n "DockerAgentNode(" provider.py`) and add the kwarg.

Note: adding env changes the container's runtime environment but NOT the agent hash (env is not hashed) — verify with `uv run pytest packages/python/vystak/ -k hash` that nothing regresses.

- [ ] **Step 4: Run provider + CLI + full python tests**

Run: `uv run pytest packages/python/vystak-provider-docker/tests/ packages/python/vystak-cli/tests/ -q && just test-python`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak/src/vystak/schema/platform.py packages/python/vystak-provider-docker/ packages/python/vystak-cli/
git commit -m "feat(docker): scheduler volume/port, platform toggle, agent env wiring"
```

---

### Task 10: `vystak schedules` CLI

**Files:**
- Create: `packages/python/vystak-cli/src/vystak_cli/commands/schedules.py`
- Modify: `packages/python/vystak-cli/src/vystak_cli/commands/__init__.py`, `packages/python/vystak-cli/src/vystak_cli/cli.py` (register)
- Test: `packages/python/vystak-cli/tests/test_schedules_cmd.py`

**Interfaces:**
- Consumes: scheduler REST API at `http://127.0.0.1:9797` (env override `VYSTAK_SCHEDULER_URL`).
- Produces: `vystak schedules list|add|show|pause|resume|remove`.

- [ ] **Step 1: Write failing tests** with `click.testing.CliRunner` and `httpx` mocked via `respx` if the repo uses it — check `uv run python -c "import respx"`; if absent, monkeypatch an internal `_client()` factory returning a `httpx.Client(transport=httpx.MockTransport(handler))`. Cover: `list` renders a table row per task; `add --agent a.agents.default --name r --cron "0 9 * * 1" --prompt hi` POSTs the right JSON and prints the id; `remove <id>` DELETEs; `pause`/`resume` PATCH `{"enabled": false/true}`; a 409 response surfaces the server's `detail` message and exits 1; connection-refused prints "scheduler is not running — is anything deployed with schedules?" and exits 1.

- [ ] **Step 2: Run to verify failure**

- [ ] **Step 3: Implement**

```python
# packages/python/vystak-cli/src/vystak_cli/commands/schedules.py
"""vystak schedules — manage runtime scheduled tasks via the scheduler API."""

import json
import os

import click
import httpx

DEFAULT_URL = "http://127.0.0.1:9797"


def _client() -> httpx.Client:
    return httpx.Client(base_url=os.environ.get("VYSTAK_SCHEDULER_URL", DEFAULT_URL),
                        timeout=10)


def _die(resp: httpx.Response) -> None:
    try:
        detail = resp.json().get("detail", resp.text)
    except Exception:
        detail = resp.text
    click.echo(f"error: {detail}", err=True)
    raise SystemExit(1)


@click.group()
def schedules():
    """Manage scheduled tasks (declarative tasks are read-only here)."""


@schedules.command("list")
@click.option("--agent", default=None)
@click.option("--all", "show_all", is_flag=True, help="Include completed/missed/cancelled.")
def list_cmd(agent, show_all):
    try:
        with _client() as c:
            resp = c.get("/tasks", params={k: v for k, v in
                         {"agent": agent}.items() if v})
    except httpx.ConnectError:
        click.echo("scheduler is not running — is anything deployed with schedules?",
                   err=True)
        raise SystemExit(1)
    if resp.status_code != 200:
        _die(resp)
    rows = resp.json()["tasks"]
    if not show_all:
        rows = [r for r in rows if r["status"] == "active"]
    for r in rows:
        shape = r["task"].get("cron") or r["task"].get("at") or r["task"].get("every")
        click.echo(f"{r['id'][:8]}  {r['agent']:<30} {r['name']:<20} "
                   f"{r['source']:<11} {r['status']:<9} {shape}  "
                   f"next={r['next_fire_at'] or '-'}")


@schedules.command("add")
@click.option("--agent", required=True, help="Agent canonical_name.")
@click.option("--name", required=True)
@click.option("--cron", default=None)
@click.option("--at", "at_", default=None, help="ISO-8601 one-shot time.")
@click.option("--every", default=None, help="e.g. 30s, 20m, 2h, 1d.")
@click.option("--timezone", default="UTC")
@click.option("--prompt", default=None)
@click.option("--channel", "target_channel", default=None)
@click.option("--thread", "target_thread", default=None)
def add_cmd(agent, name, cron, at_, every, timezone, prompt,
            target_channel, target_thread):
    body = {"agent": agent, "name": name, "cron": cron, "at": at_,
            "every": every, "timezone": timezone, "prompt": prompt,
            "target_channel": target_channel, "target_thread": target_thread,
            "created_by": "cli"}
    body = {k: v for k, v in body.items() if v is not None}
    with _client() as c:
        resp = c.post("/tasks", json=body)
    if resp.status_code != 201:
        _die(resp)
    click.echo(resp.json()["id"])


@schedules.command("show")
@click.argument("task_id")
def show_cmd(task_id):
    with _client() as c:
        resp = c.get(f"/tasks/{task_id}")
    if resp.status_code != 200:
        _die(resp)
    click.echo(json.dumps(resp.json(), indent=2))


def _patch(task_id: str, payload: dict) -> None:
    with _client() as c:
        resp = c.patch(f"/tasks/{task_id}", json=payload)
    if resp.status_code != 200:
        _die(resp)
    click.echo("ok")


@schedules.command("pause")
@click.argument("task_id")
def pause_cmd(task_id):
    _patch(task_id, {"enabled": False})


@schedules.command("resume")
@click.argument("task_id")
def resume_cmd(task_id):
    _patch(task_id, {"enabled": True})


@schedules.command("remove")
@click.argument("task_id")
def remove_cmd(task_id):
    with _client() as c:
        resp = c.delete(f"/tasks/{task_id}")
    if resp.status_code != 204:
        _die(resp)
    click.echo("removed")
```

Register in `commands/__init__.py` + `cli.py` (`cli.add_command(schedules_cmd)`) following the existing import/alias pattern. Add `httpx` to vystak-cli's pyproject deps if not already present (`grep httpx packages/python/vystak-cli/pyproject.toml`).

Note `--at` uses ISO-8601 absolute times; relative forms ("in 2 hours") are the agent tool's job (the LLM computes the timestamp), not the CLI's.

- [ ] **Step 4: Run CLI tests + commit**

Run: `uv run pytest packages/python/vystak-cli/tests/ -q`
Expected: PASS

```bash
git add packages/python/vystak-cli/
git commit -m "feat(cli): vystak schedules command group"
```

---

### Task 11: `schedule_task` agent tool in the template

**Files:**
- Create: `packages/python/vystak-template-langchain-python/_vystak/runtime/schedules.py`
- Modify: `packages/python/vystak-template-langchain-python/_vystak/runtime/app_factory.py` (add to tool assembly, lines 91–119/165)
- Modify: `packages/python/vystak-template-langchain-python/_vystak/runtime/a2a_native/executor.py` (turn-metadata ContextVar)
- Modify: `packages/python/vystak-channel-runtime/src/vystak_channel_runtime/runtime.py` (add `channel_canonical` + `thread_id` to outbound A2A metadata)
- Test: `packages/python/vystak-template-langchain-python/tests/test_schedule_tools.py`

**Interfaces:**
- Consumes: scheduler REST API via env `VYSTAK_SCHEDULER_URL`; agent identity via `VYSTAK_AGENT_CANONICAL` (Task 9).
- Produces:
  - `_vystak.runtime.schedules.build_schedule_tools(agent) -> list` — returns `[]` when `VYSTAK_SCHEDULER_URL` unset; else three LangChain `@tool` functions: `schedule_task(name, cron=None, at=None, every=None, prompt=None, timezone="UTC", deliver_here=True)`, `list_scheduled_tasks()`, `cancel_scheduled_task(task_id)`.
  - `_vystak.runtime.schedules.CURRENT_TURN_METADATA: ContextVar[dict]` — set by the a2a executor per request; `deliver_here=True` reads `channel_canonical`/`thread_id` from it.

- [ ] **Step 1: Write failing tests**

Follow `tests/test_workspace_tools.py` for the template-test conventions (how `_vystak` is imported in tests). Cover: (a) no env → `build_schedule_tools` returns `[]`; (b) with env + mocked httpx transport: `schedule_task(name="r", every="1h", prompt="check")` POSTs `{agent: $VYSTAK_AGENT_CANONICAL, name, every, prompt, created_by: "agent:..."}` and returns the id string; (c) `deliver_here=True` with `CURRENT_TURN_METADATA` set to `{"channel_canonical": "c.channels.d", "thread_id": "t9"}` includes `target_channel`/`target_thread` in the POST body; (d) `deliver_here=True` with empty metadata omits both and the returned message notes results will not be delivered to a channel; (e) `list_scheduled_tasks` GETs with `agent=` filter — the tool never sees other agents' tasks; (f) `cancel_scheduled_task` DELETEs and maps 409 to a readable error string (tools return strings, never raise).

- [ ] **Step 2: Run to verify failure**

- [ ] **Step 3: Implement `schedules.py`**

```python
"""Agent-side scheduling tools — thin client of the platform scheduler API."""

from __future__ import annotations

import os
from contextvars import ContextVar
from typing import Any

import httpx
from langchain_core.tools import tool

CURRENT_TURN_METADATA: ContextVar[dict] = ContextVar("vystak_turn_metadata",
                                                     default={})


def build_schedule_tools(agent: Any) -> list[Any]:
    base_url = os.environ.get("VYSTAK_SCHEDULER_URL")
    canonical = os.environ.get("VYSTAK_AGENT_CANONICAL")
    if not base_url or not canonical:
        return []

    def _client() -> httpx.Client:
        return httpx.Client(base_url=base_url, timeout=10)

    @tool
    def schedule_task(name: str, cron: str | None = None, at: str | None = None,
                      every: str | None = None, prompt: str | None = None,
                      timezone: str = "UTC", deliver_here: bool = True) -> str:
        """Create a scheduled task for yourself. Exactly one of cron (5-field
        cron), at (ISO-8601 one-shot), or every ('30s'/'20m'/'2h'/'1d') must be
        set. `prompt` is what you will be asked when it fires. With
        deliver_here=True your reply is delivered back to this conversation."""
        body: dict = {"agent": canonical, "name": name, "timezone": timezone,
                      "created_by": f"agent:{canonical}"}
        for k, v in (("cron", cron), ("at", at), ("every", every),
                     ("prompt", prompt)):
            if v is not None:
                body[k] = v
        note = ""
        if deliver_here:
            meta = CURRENT_TURN_METADATA.get()
            if meta.get("channel_canonical") and meta.get("thread_id"):
                body["target_channel"] = meta["channel_canonical"]
                body["target_thread"] = meta["thread_id"]
            else:
                note = (" (no originating channel/thread known — results will "
                        "be logged, not delivered)")
        try:
            with _client() as c:
                resp = c.post("/tasks", json=body)
        except httpx.HTTPError as e:
            return f"scheduler unreachable: {e}"
        if resp.status_code != 201:
            return f"failed ({resp.status_code}): {resp.text}"
        return f"scheduled task {resp.json()['id']}{note}"

    @tool
    def list_scheduled_tasks() -> str:
        """List your own scheduled tasks (active and past)."""
        try:
            with _client() as c:
                resp = c.get("/tasks", params={"agent": canonical})
        except httpx.HTTPError as e:
            return f"scheduler unreachable: {e}"
        rows = resp.json().get("tasks", [])
        if not rows:
            return "no scheduled tasks"
        return "\n".join(
            f"{r['id']} {r['name']} [{r['status']}] "
            f"{r['task'].get('cron') or r['task'].get('at') or r['task'].get('every')} "
            f"next={r['next_fire_at'] or '-'}"
            for r in rows)

    @tool
    def cancel_scheduled_task(task_id: str) -> str:
        """Cancel one of your scheduled tasks by id."""
        try:
            with _client() as c:
                got = c.get(f"/tasks/{task_id}")
                if got.status_code == 200 and got.json()["agent"] != canonical:
                    return "not your task"
                resp = c.delete(f"/tasks/{task_id}")
        except httpx.HTTPError as e:
            return f"scheduler unreachable: {e}"
        if resp.status_code != 204:
            return f"failed ({resp.status_code}): {resp.text}"
        return "cancelled"

    return [schedule_task, list_scheduled_tasks, cancel_scheduled_task]
```

Wire into `app_factory.py` next to `build_workspace_tools` (both assembly sites, lines ~119 and ~165):

```python
from _vystak.runtime.schedules import build_schedule_tools
...
    schedule_tools = build_schedule_tools(agent)
...
        tools=user_tools + workspace_tools + subagent_tools + skill_tools + schedule_tools,
```

Executor (`a2a_native/executor.py`): at the top of `execute()`, extract the incoming message's metadata dict (via `context.message.metadata` — verify the exact attribute on `RequestContext` in the a2a-sdk version pinned here) and `CURRENT_TURN_METADATA.set(metadata or {})` before running the graph.

Channel runtime (`vystak_channel_runtime/runtime.py`): where the agent is invoked with metadata (the call sites passing `metadata=` into `AgentClient` methods — `grep -n "metadata" runtime.py`), merge in `{"channel_canonical": <the channel's canonical name>, "thread_id": <thread id>}` using the values the runtime already tracks for delivery. Add one unit test in `vystak-channel-runtime`'s tests asserting the merged keys.

Note (template dev-loop): the template is snapshotted into the CLI wheel — after editing, refresh with `uv sync --reinstall-package vystak-cli` before any live deploy test.

- [ ] **Step 4: Run template + channel-runtime tests, lint, commit**

Run: `uv run pytest packages/python/vystak-template-langchain-python/tests/ packages/python/vystak-channel-runtime/tests/ -q && just lint-python`
Expected: PASS / clean

```bash
git add packages/python/vystak-template-langchain-python/ packages/python/vystak-channel-runtime/
git commit -m "feat(template): schedule_task agent tools with originating-thread delivery"
```

---

### Task 12: Release test — `test_schedules.py`

**Files:**
- Create: `packages/python/vystak-provider-docker/tests/release/test_schedules.py`
- Modify: `packages/python/vystak-provider-docker/tests/release/conftest.py` (add `scheduler_clean` fixture removing the `vystak-scheduler-data` volume, mirroring `postgres_clean`)

**Interfaces:**
- Consumes: the whole feature; `project` / `docker_required` fixtures (existing conftest).
- Produces: `release_integration`-marked cells.

- [ ] **Step 1: Read two neighbors first** — `test_heartbeat_v2.py` and one `test_D*_` cell — and copy their project-scaffold + apply/destroy structure exactly (sentinel `.env`, `vystak apply` via subprocess or the harness helper they use).

- [ ] **Step 2: Write the test** (three cells, one file):

```python
import pytest

pytestmark = [pytest.mark.release_integration]

VYSTAK_YAML = """\
providers: [...]        # copy the provider/platform/channel scaffold from
platforms: [...]        # test_heartbeat_v2.py verbatim, chat channel routing
agents:                 # to agent 'sched-bot'
  - name: sched-bot
    ...
    schedules:
      - name: tick
        every: 30s
        prompt: "Reply with the word TICK."
        target_channel: chat-main.channels.dev
        target_thread: sched-room
"""

def test_declarative_schedule_fires(project, docker_required, scheduler_clean):
    # apply; poll the chat channel's thread (or scheduler API last_result)
    # up to ~90s for a fire: GET http://127.0.0.1:9797/tasks →
    # the 'tick' task has last_fire_at set. destroy via fixture.

def test_runtime_oneshot_fires_and_completes(project, docker_required, scheduler_clean):
    # apply the same project; POST /tasks {agent:…, name:"once",
    # at:<now+10s>, prompt:"Reply DONE."}; poll GET /tasks/{id} until
    # status == "completed" and last_fire_at set (≤60s).

def test_runtime_task_survives_scheduler_restart(project, docker_required, scheduler_clean):
    # apply; POST a runtime cron task; docker restart vystak-heartbeat;
    # GET /tasks still lists it (source=runtime, status=active).
```

Fill every body concretely using the neighbor cells' polling helpers; the assertions above are the contract.

- [ ] **Step 3: Run it**

Run: `uv run pytest packages/python/vystak-provider-docker/tests/release/test_schedules.py -v -m release_integration`
Expected: PASS (requires local Docker; ~2–4 min). Also re-run the guard cell:
`uv run pytest packages/python/vystak-provider-docker/tests/release/test_heartbeat_v2.py -v -m release_integration` — must stay green.

- [ ] **Step 4: Commit**

```bash
git add packages/python/vystak-provider-docker/tests/release/
git commit -m "test(release): scheduled-tasks lifecycle cells"
```

---

### Task 13: Example + docs + todos cleanup

**Files:**
- Create: `examples/docker-schedules/vystak.yaml`, `examples/docker-schedules/README.md`, `examples/docker-schedules/.env.example`
- Create: `docs/schedules.md`
- Modify: `docs/heartbeat.md` (one paragraph up top linking to schedules.md as the general mechanism)
- Modify: `CLAUDE.md` (add `docker-schedules` to the Examples list; mention `vystak schedules` in Core packages CLI line)
- Modify: `todos.md` (no schedule-related entry exists — no change needed; verify)

**Interfaces:** none produced; consumes everything.

- [ ] **Step 1: Write the example** — copy `examples/heartbeat-agent/` as the base; the agent declares one `schedules:` entry (`cron: "0 9 * * 1"`, digest prompt, chat channel target) with placeholder API keys per repo convention (`your-anthropic-api-key-here`). README walks through: `vystak apply`, `vystak schedules list`, `vystak schedules add --agent … --every 30m --prompt …`, the agent-tool flow ("ask the agent: remind me in 2 hours to check the deploy"), `vystak schedules remove`.

- [ ] **Step 2: Write `docs/schedules.md`** — structure mirrors `docs/heartbeat.md`: quick start (declarative YAML), configuration reference table (all `ScheduledTask` fields), the three shapes with examples, runtime scheduling (CLI + REST + agent tool), reconciliation rules (declarative vs runtime, apply behavior), missed-fire policy incl. the 24h grace window, ack contract pointer to heartbeat.md.

- [ ] **Step 3: Verify example loads**

Run: `uv run python -c "from vystak.schema.multi_loader import load_multi_yaml; load_multi_yaml(open('examples/docker-schedules/vystak.yaml').read()); print('ok')"`
(Adapt the call signature to `load_multi_yaml`'s real one — check how other example-validation tests invoke it, or add this example to an existing examples-load test if one exists: `grep -rl "examples" packages/python/*/tests/ | head`.)
Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add examples/docker-schedules/ docs/schedules.md docs/heartbeat.md CLAUDE.md
git commit -m "docs+example: scheduled tasks (docker-schedules)"
```

---

### Task 14: Postgres store backend (spec: optional Postgres)

**Files:**
- Create: `packages/python/vystak-heartbeat/src/vystak_heartbeat/schedule_store_pg.py`
- Modify: `packages/python/vystak-heartbeat/src/vystak_heartbeat/__main__.py` (store factory by `cfg["store"]["type"]`)
- Modify: `packages/python/vystak-heartbeat/src/vystak_heartbeat/plugin.py` (accept `store_cfg` param; provider passes `{"type": "postgres", "dsn": …}` when the project declares Postgres — find how `sessions-postgres` threads its DSN: `grep -rn "connection_string" packages/python/vystak-provider-docker/src | head`)
- Test: `packages/python/vystak-heartbeat/tests/test_schedule_store_pg.py` (marked `docker`, spins a throwaway postgres container like the existing `-m docker` tests do — copy their fixture)

**Interfaces:**
- Produces: `PgScheduleStore(dsn)` implementing the exact `SqliteScheduleStore` method set (Task 5's interface block). The store tests from Task 5 are parametrized to run against both backends (extract the test class bodies into a shared mixin or parametrized `store` fixture; SQLite always runs, PG only under `-m docker`).

- [ ] **Step 1: Parametrize Task 5's tests** over a `store` fixture with params `["sqlite", pytest.param("pg", marks=pytest.mark.docker)]`.

- [ ] **Step 2: Run** — sqlite param passes, pg param errors (module missing).

- [ ] **Step 3: Implement `schedule_store_pg.py`** with asyncpg, same DDL translated (TEXT → TEXT, `UNIQUE (agent_canonical, name)`, JSONB for payload is fine), same method semantics; unique-violation → `NameCollisionError` (catch `asyncpg.UniqueViolationError`).

- [ ] **Step 4: Run both params**

Run: `uv run pytest packages/python/vystak-heartbeat/tests/test_schedule_store.py -v` (sqlite) and `uv run pytest packages/python/vystak-heartbeat/tests/ -m docker -v` (pg)
Expected: PASS

- [ ] **Step 5: Wire the factory + provider DSN pass-through, run full suite, commit**

Run: `just test-python && just lint-python`
Expected: PASS / clean

```bash
git add packages/python/vystak-heartbeat/ packages/python/vystak-provider-docker/
git commit -m "feat(scheduler): optional Postgres schedule store"
```

---

## Final verification (after all tasks)

- [ ] `just ci-live` — all four live gates green.
- [ ] Full release regression: `uv run pytest packages/python/vystak-provider-docker/tests/release/ -v -m "release_smoke or release_integration"` — including `test_heartbeat_v2.py` and the new `test_schedules.py`.
- [ ] Scan staged diffs for secrets per CLAUDE.md before every commit (public repo).
